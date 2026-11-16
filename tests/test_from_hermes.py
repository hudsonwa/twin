"""Phase P2: the one prompt sent from Hermes (`hermes twin from-hermes`, twin_from_hermes), continuous chat sync
(twin/chat_sync.py, both modes) and the engine adapter (twin/grok_engine.py).

The engine is a stub `botport grok` (fake_grok_engine.py) that replays JSON answers in the shapes of the P0
interface sketch; when the scenario says so it appends what `hermes twin from-grok` / `chat-sync` would log when the
bot ran them. Invented bots only (Acme Support, Recipe Planner).
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

from twin_testlib import home, svc  # noqa: F401
from hermes_plugins.grok_bot_twin.twin import chat_sync, config, from_hermes, grok_engine as ge, history as H
from hermes_plugins.grok_bot_twin.twin import one_prompt
from hermes_plugins.grok_bot_twin.twin import transcripts as tr

STUB = Path(__file__).resolve().parent / "fake_grok_engine.py"
ACME = {"id": "11111111-1111-4111-8111-111111111111", "name": "Acme Support", "main": False, "state": "idle"}
RECIPE = {"id": "22222222-2222-4222-8222-222222222222", "name": "Recipe Planner", "main": False, "state": "idle"}
TWIN_LINE = ("PASS: Acme Support twinned to Hermes (profile acme-support): 1 skills, 1 memories, 0 routines added "
             "switched off; matches what the bot sent; behaviour test 2/2.")
SYNC_LINE = "PASS: Acme Support chat sync: 3 new message(s) in Hermes chats \"From Grok: …\""


def bots_answer(*bots):
    return {"rc": 0, "stdout": {"bots": list(bots), "proof": f"PASS: {len(bots)} bots; matches sidebar"}}


def reply(text, key="t9s1", bot=ACME):
    return {"bot": {**bot, "last_key": key}, "state": "idle", "waited_s": 12.0,
            "messages": [{"key": "t8u", "role": "user", "kind": "text", "text": "Clone yourself… TWIN: <x>"},
                         {"key": key, "role": "bot", "kind": "text", "text": text}],
            "proof": "PASS: reply received; bot idle 8 s"}


def logged(tool, result="PASS", bot="Acme Support", **kw):
    return {"tool": tool, "bot": bot, "result": result, **kw}


GOOD_ASK = {"rc": 0, "stdout": reply(f"TWIN: {TWIN_LINE}\nSYNC: {SYNC_LINE}\nROUTINE: made"),
            "log": [logged(one_prompt.TOOL, pair_id="acme-support"),
                    logged(chat_sync.TOOL, counts={"conversations": 1, "new_messages": 3})]}


ALWAYS = {"rc": 0, "stdout": {"installed": True, "running": True, "local_tool_permission": "always"}}


class Stub:
    """The stub engine on disk plus its scenario; `eng` is a GrokEngine that runs it as a real subprocess."""

    def __init__(self, tmp_path, home):
        if sys.platform == "win32":  # (the stub is a #! script, and the real engine is botport's: no Windows build)
            pytest.skip("the Grok engine (botport grok) reads the Grok app; Windows has no botport and only follows")
        self.dir = tmp_path / "stub"
        self.dir.mkdir()
        exe = self.dir / "botport"
        exe.write_text(f"#!{sys.executable}\n" + STUB.read_text(encoding="utf-8"), encoding="utf-8")
        exe.chmod(0o755)
        self.scen, self.argv = self.dir / "scenario.json", self.dir / "argv.jsonl"
        calls = one_prompt._folder() / "calls.jsonl"
        self.eng = ge.GrokEngine(str(exe), env={"PATH": "/usr/bin:/bin", "FAKE_GROK_SCENARIO": str(self.scen),
                                                "FAKE_GROK_CALLS": str(calls), "FAKE_GROK_ARGV": str(self.argv)})

    def play(self, **answers):
        answers.setdefault("status", [ALWAYS])  # (the Mac's Grok setting reads Always allow unless a test says not)
        answers.setdefault("restore", [{"rc": 0, "stdout": {"proof": "PASS: restored; checked process args and port file"}}])
        self.scen.write_text(json.dumps(answers), encoding="utf-8")
        seen = Path(str(self.scen) + ".seen")
        if seen.exists():
            seen.unlink()
        return self

    def calls(self):
        return [json.loads(x) for x in self.argv.read_text(encoding="utf-8").splitlines()] if self.argv.exists() else []


@pytest.fixture
def stub(tmp_path, home):
    config.set_override({"botport_path": str(tmp_path / "no-botport-here"), "chat_sync_mode": "routine",
                         "from_hermes_route": "shell"})  # (the old route; the export route: test_from_hermes_export.py)
    return Stub(tmp_path, home)


def run(svc, stub, names=("Acme Support",), **kw):
    return from_hermes.run(svc, list(names) if names else None, eng=stub.eng, **kw)


# ---- the adapter ---------------------------------------------------------------------------------------------
def test_adapter_exit_codes_and_proof():
    r = ge.parse(0, b'{"proof": "PASS: ok; check"}', b"", False)
    assert r.ok and r.proof == "PASS: ok; check"
    assert ge.parse(0, b"not json", b"", False).exit == ge.OTHER
    assert ge.parse(5, b"", b"FAIL: port closed; run botport grok launch", False).exit == ge.UNAVAILABLE
    assert ge.parse(5, b"", b"FAIL: port closed", False).proof == "FAIL: port closed"
    assert ge.parse(3, b'{"proof": {"pass": false, "what": "waiting", "check": "card"}}', b"", False).proof == \
        "FAIL: waiting; card"
    assert ge.parse(0, b"{}", b"", True).exit == ge.OTHER
    assert ge.parse(42, b"{}", b"", False).exit == ge.OTHER


def test_adapter_command_line_is_the_sketch(stub):
    stub.play(ask=[{"rc": 0, "stdout": reply("TWIN: x")}])
    stub.eng.ask(ACME["id"], "hello", 120, 8)
    argv = stub.calls()[-1]
    assert argv[:3] == ["grok", "ask", ACME["id"]] and argv[3] == "hello"
    assert "--json" in argv and argv[argv.index("--timeout") + 1] == "120" and argv[argv.index("--settle") + 1] == "8"
    stub.play(wait=[{"rc": 0, "stdout": reply("x")}])
    stub.eng.wait(ACME["id"], "t1", 60, 8)
    w = stub.calls()[-1]
    assert w[:3] == ["grok", "wait", ACME["id"]] and w[w.index("--since") + 1] == "t1" and "--settle" in w


def test_engine_missing_is_a_fail_naming_both_ways_out(svc, home, monkeypatch):
    from hermes_plugins.grok_bot_twin.twin import engine as E
    monkeypatch.setattr(E, "configured_tag", lambda: "v0.2.1")  # (an older release chosen: no engine to set up)
    res = from_hermes.run(svc, ["Acme Support"])
    assert not res["ok"] and res["line"].startswith("FAIL: Acme Support: needs botport 0.3.0 or newer")
    assert "Clone yourself to Hermes" in res["line"]


def test_botport_without_the_grok_engine_is_missing(svc, home, monkeypatch):
    class BP:
        def _verify(self):
            return "/x/botport", {}

        def _env(self):
            return {}
    monkeypatch.setattr(svc, "botport", lambda: BP())
    monkeypatch.setattr(ge.GrokEngine, "status", lambda self: ge.parse(2, b'{"ok": false}', b"", False))
    with pytest.raises(ge.Unavailable, match="no Grok engine"):
        ge.from_service(svc)


# ---- from-hermes, mode routine (a) ---------------------------------------------------------------------------
def test_routine_mode_pass_is_checked_on_this_computer(svc, stub):
    stub.play(bots=[bots_answer(ACME, RECIPE)], ask=[GOOD_ASK])
    res = run(svc, stub)
    assert res["ok"], res["line"]
    line = res["line"]
    assert line.startswith("PASS: Acme Support: twinned through the engine") and TWIN_LINE in line
    assert f"routine \"{chat_sync.ROUTINE_NAME}\" every 360 min (the bot confirmed the routine;" in line
    assert "about 28 turns a week per bot" in line
    assert "first sync landed, 3 new message(s)" in line and "one-prompt log has the PASS" in line
    prompt = [a for a in stub.calls() if a[1] == "ask"][0][3]
    assert prompt.startswith("Clone yourself to Hermes") and chat_sync.command_for("Acme Support") in prompt
    assert "CreateRoutine" in prompt and "TWIN:" in prompt and "SYNC:" in prompt
    assert chat_sync.status()["twins"]["acme-support"]["mode"] == "routine"


def test_routine_check_is_the_bots_word_until_p3(svc, stub):
    stub.play(bots=[bots_answer(ACME)], ask=[{**GOOD_ASK, "stdout": reply(f"TWIN: {TWIN_LINE}\nSYNC: {SYNC_LINE}\n"
                                                                          "ROUTINE: FAIL CreateRoutine refused")}])
    res = run(svc, stub)
    assert not res["ok"] and "did not confirm the routine (FAIL CreateRoutine refused)" in res["line"]
    assert not any(a[1] == "routines" for a in stub.calls())


def test_adapter_reads_the_frozen_shapes():
    wrapped = json.dumps({"exit": 0, "proof": "PASS: reply received; dom-rows",
                          "untrusted_bot_content": {"messages": [{"key": "k1", "role": "bot", "text": "hi"}]}})
    r = ge.parse(0, wrapped.encode(), b"", False)
    assert ge.messages_of(r)[0]["text"] == "hi" and r.proof.startswith("PASS")
    err = ge.parse(1, b'{"exit": 1, "proof": "", "error": {"code": "ambiguous", "message": "two bots match"}}', b"",
                   False)
    assert err.exit == ge.OTHER and err.proof == "FAIL: two bots match"
    assert ge.has_engine(ge.parse(5, b'{"exit": 5, "proof": "FAIL: not running; ps"}', b"", False))
    assert not ge.has_engine(ge.parse(1, b'{"ok": false, "schema": "botport.twin.v1"}', b"", False))


def test_bot_says_pass_but_nothing_ran_here_is_a_fail(svc, stub):
    stub.play(bots=[bots_answer(ACME)], ask=[{**GOOD_ASK, "log": []}])
    res = run(svc, stub)
    assert not res["ok"] and "has no PASS for it since the ask" in res["line"]


def test_first_sync_missing_is_a_fail(svc, stub):
    stub.play(bots=[bots_answer(ACME)], ask=[{**GOOD_ASK, "log": GOOD_ASK["log"][:1]}])
    res = run(svc, stub)
    assert not res["ok"] and "chat sync's first run did not land here" in res["line"]


def test_bots_fail_line_is_passed_on(svc, stub):
    fail = "FAIL: Acme Support: behaviour test 1/2. The twin was put back as it was before this call."
    stub.play(bots=[bots_answer(ACME)], ask=[{"rc": 0, "stdout": reply(f"TWIN: {fail}"),
                                              "log": [logged(one_prompt.TOOL, "FAIL")]}])
    res = run(svc, stub)
    assert not res["ok"] and "twin: Acme Support: behaviour test 1/2" in res["line"]


def test_unknown_or_ambiguous_bot(svc, stub):
    stub.play(bots=[bots_answer(ACME, RECIPE)])
    assert "no Grok bot of that name" in run(svc, stub, ["Nobody"])["line"]
    stub.play(bots=[bots_answer(ACME, {**RECIPE, "name": "acme support"})])
    assert "more than one Grok bot" in run(svc, stub)["line"]


def test_port_closed_is_the_fallback_fail(svc, stub):
    stub.play(bots=[{"rc": 5, "stdout": {}, "stderr": "FAIL: port closed; run botport grok launch"}])
    res = run(svc, stub)
    assert not res["ok"] and res.get("fallback") and "Clone yourself to Hermes" in res["line"]
    stub.play(bots=[bots_answer(ACME)], ask=[{"rc": 5, "stdout": {}, "stderr": "FAIL: port closed"}])
    res = run(svc, stub)
    assert not res["ok"] and "botport grok launch" in res["line"]


def test_untested_grok_version_names_the_canary(svc, stub):
    untested = {"rc": 4, "stdout": {"error": {"code": "refused", "message": "Grok Bot 9.9.9 is not a tested version; "
                                              "writes are blocked by unknown_version_writes until the canary passes",
                                              "hint": "botport grok canary (or --trust-version under preset fast)"}},
                "stderr": "FAIL: ask; Grok Bot 9.9.9 is not a tested version"}
    stub.play(bots=[bots_answer(ACME)], ask=[untested])
    res = run(svc, stub)
    assert not res["ok"] and "run botport grok canary on this Mac" in res["line"] and not res.get("waiting")


def test_policy_refusal(svc, stub):
    stub.play(bots=[bots_answer(ACME)], ask=[{"rc": 4, "stdout": {}, "stderr": "FAIL: refused; bots_scope"}])
    assert "botport's policy refused it (refused; bots_scope)" in run(svc, stub)["line"]


def test_waiting_for_approval_then_wait_picks_up_the_same_run(svc, stub):
    waiting = {"rc": 3, "stdout": {"bot": {**ACME, "state": "needs_input", "last_key": "t9s0", "needs_input":
                                           {"kind": "approval", "reason": "Run a command on your local computer"}},
                                   "messages": [], "state": "needs_input"}}
    stub.play(bots=[bots_answer(ACME)], ask=[waiting])
    res = run(svc, stub)
    assert not res["ok"] and res.get("waiting")
    assert "waiting for an approval in Grok (Run a command on your local computer)" in res["line"]
    assert "--wait" in res["line"]
    stub.play(bots=[bots_answer(ACME)], wait=[GOOD_ASK])
    res = run(svc, stub, wait_only=True)
    assert res["ok"], res["line"]
    w = [a for a in stub.calls() if a[1] == "wait"][-1]
    assert w[w.index("--since") + 1] == "t9s0"
    assert not any(a[1] == "ask" for a in stub.calls()[-2:])
    again = run(svc, stub, wait_only=True)
    assert not again["ok"] and "no earlier run of this bot is waiting" in again["line"]


def test_still_working_waits_again(svc, stub):
    working = {"rc": 2, "stdout": {"bot": {**ACME, "state": "working", "last_key": "t9s0"}, "messages": [
        {"key": "t9s0", "role": "bot", "kind": "text", "text": "On it."}]}}
    stub.play(bots=[bots_answer(ACME)], ask=[working], wait=[GOOD_ASK])
    assert run(svc, stub)["ok"]
    stub.play(bots=[bots_answer(ACME)], ask=[working], wait=[working])
    res = run(svc, stub, timeout_s=1)
    assert not res["ok"] and "still working" in res["line"]


def test_all_bots_one_after_another(svc, stub):
    recipe_fail = {"rc": 0, "stdout": reply("TWIN: FAIL: Recipe Planner: no such tool.", bot=RECIPE)}
    stub.play(bots=[bots_answer(ACME, RECIPE)], ask=[GOOD_ASK, recipe_fail])
    res = run(svc, stub, names=None, all_bots=True)
    assert not res["ok"] and res["line"].startswith("FAIL: 1/2 Grok bots twinned through the engine")
    asked = [a[2] for a in stub.calls() if a[1] == "ask"]
    assert asked == [ACME["id"], RECIPE["id"]]


def test_mode_off_twins_without_sync(svc, stub):
    config.set_override({"botport_path": "/nonexistent", "chat_sync_mode": "off", "from_hermes_route": "shell"})
    stub.play(bots=[bots_answer(ACME)], ask=[{**GOOD_ASK, "log": GOOD_ASK["log"][:1]}])
    res = run(svc, stub)
    assert res["ok"] and "Chat sync" not in res["line"]
    prompt = [a for a in stub.calls() if a[1] == "ask"][0][3]
    assert "CreateRoutine" not in prompt


def test_default_mode_is_pull():
    config.set_override({})
    assert chat_sync.DEFAULT_MODE == "pull" and chat_sync.mode() == "pull"


@pytest.mark.parametrize("perm,shown", [("ask", "Ask every time"), ("never", "Never allow"),
                                        (None, "nothing Hermes could read")])
def test_routine_is_refused_unless_grok_reads_always_allow(svc, stub, perm, shown):
    st = {"rc": 0, "stdout": {"running": True, **({"local_tool_permission": perm} if perm else {})}}
    stub.play(status=[st], bots=[bots_answer(ACME)], ask=[GOOD_ASK])
    res = run(svc, stub)
    assert not res["ok"] and f"Always allow, and it reads {shown}" in res["line"]
    assert "Hermes never changes that setting" in res["line"] and "chat_sync_mode pull" in res["line"]
    assert not any(a[1] == "ask" for a in stub.calls())  # refused before the bot is asked anything


def test_routine_mode_refuses_less_than_an_hour_with_the_reason(svc, stub, tmp_path):
    config.set_override({"botport_path": str(tmp_path / "no-botport-here"), "chat_sync_mode": "routine",
                         "from_hermes_route": "shell", "chat_sync_minutes": 15})
    stub.play(bots=[bots_answer(ACME)], ask=[GOOD_ASK])
    res = run(svc, stub)
    assert not res["ok"] and "chat sync by routine runs at most once an hour" in res["line"]
    assert "chat_sync_minutes is 15" in res["line"] and "about 672 turns a week" in res["line"]
    assert not any(a[1] == "ask" for a in stub.calls())  # refused before the bot is asked anything
    assert chat_sync.routine_refusal(60) == "" and chat_sync.weekly_turns(60) == 168


def test_enabling_routine_prints_the_weekly_estimate_first(svc, stub, monkeypatch, capsys):
    import argparse
    config.set_override({"botport_path": "/nonexistent", "chat_sync_mode": "routine", "from_hermes_route": "shell",
                         "chat_sync_minutes": 60})
    monkeypatch.setattr(from_hermes, "run", lambda *a, **kw: {"ok": True, "line": "PASS: done", "bots": []})
    a = argparse.Namespace(bot="Acme Support", bots=None, only=None, all=False, wait=False, timeout=60, route=None,
                           file=False, shared_skills=False, json=False)
    assert from_hermes.cmd(a) == 0
    out = capsys.readouterr().out
    assert out.index("about 168 turns a week per bot") < out.index("PASS: done")


def test_routine_prompt_sends_a_window_and_the_mac_tracks_what_is_new():
    text = chat_sync.routine_prompt("Acme Support", 60)
    assert "ALL the messages of the last 75 minutes" in text and "Hermes keeps track" in text


# ---- the Hermes tool -----------------------------------------------------------------------------------------
def test_tool_arguments_and_names(svc, stub, monkeypatch):
    out = json.loads(from_hermes.twin_from_hermes({}))
    assert not out["ok"] and "bot_name, or all" in out["line"]
    assert "named exactly" in json.loads(from_hermes.twin_from_hermes({"bot_name": "all"}))["line"]
    from hermes_plugins.grok_bot_twin.twin import tasks
    monkeypatch.setattr(tasks, "asked_turn", lambda **kw: True)
    assert "another computer" in json.loads(from_hermes.twin_from_hermes({"bot_name": "Acme Support"}))["line"]
    monkeypatch.setattr(tasks, "asked_turn", lambda **kw: False)
    monkeypatch.setattr(from_hermes, "run", lambda svc, names, all_bots=False, **kw: {
        "ok": True, "line": "PASS: 2/2 Grok bots twinned", "bots": [{"ok": True, "line": "PASS: Acme Support"},
                                                                   {"ok": True, "line": "PASS: Recipe Planner"}]})
    out = from_hermes.twin_from_hermes({"all": True})
    assert "Acme" not in out and "Recipe" not in out and json.loads(out)["ok"]


# ---- chat sync (a): what the routine runs --------------------------------------------------------------------
@pytest.fixture
def twin(svc, monkeypatch):
    reg = {"acme-support": {"pair_id": "acme-support", "grok": {"id": ACME["id"], "name": "Acme Support"},
                            "hermes": {"profile": "acme-support"}, "driver": "bot"}}
    monkeypatch.setattr(svc, "_registry", lambda: {k: dict(v) for k, v in reg.items()})
    imported = []

    def fake(tail, profile):
        if tail[:2] == ["sessions", "import"]:
            lines = [json.loads(x) for x in Path(tail[-1]).read_text(encoding="utf-8").splitlines()]
            imported.append([x["message"]["content"] for x in lines[1:]])
            return 0, f"Imported Claude Code session as 20001231_120000_{len(imported):08x}\n"
        return 0, ""
    monkeypatch.setattr(tr, "_run_hermes", fake)
    return imported


def conv(*msgs, cid="c-1", title="Widgets", started="2000-01-02T00:00:00Z"):
    out = {"title": title, "started": started, "messages": [
        {"role": r, "text": t, "time": 946771200 + 60 * i} for i, r, t in msgs]}
    if cid:
        out["id"] = cid
    return out


def test_routine_runs_add_only_new_messages(svc, twin):
    a = chat_sync.from_bot(svc, ["Acme Support"], "Acme Support",
                           [conv((0, "user", "Price of a widget?"), (1, "assistant", "Two euros."))])
    assert a["ok"] and a["history"]["new_messages"] == 2 and a["line"].startswith("PASS: Acme Support chat sync: 2")
    b = chat_sync.from_bot(svc, ["Acme Support"], "Acme Support",  # overlap: message 1 again, then 2 new
                           [conv((1, "assistant", "Two euros."), (2, "user", "And ten?"), (3, "assistant", "Twenty."))])
    assert b["history"]["new_messages"] == 2 and twin[-1] == ["And ten?", "Twenty."]
    c = chat_sync.from_bot(svc, ["Acme Support"], "Acme Support",
                           [conv((3, "assistant", "Twenty."))])
    assert c["ok"] and c["history"]["new_messages"] == 0 and len(twin) == 2


def test_same_messages_under_a_new_title_or_no_id_are_not_duplicated(svc, twin):
    chat_sync.from_bot(svc, ["Acme Support"], "Acme Support", [conv((0, "user", "Hi"), (1, "assistant", "Hello."))])
    again = chat_sync.from_bot(svc, ["Acme Support"], "Acme Support",
                               [conv((0, "user", "Hi"), (1, "assistant", "Hello."), cid=None, title="Greeting",
                                     started="2000-01-02T00:00:30Z")])
    assert again["history"]["new_messages"] == 0 and len(twin) == 1


def test_seen_is_filled_from_an_archive_older_than_it(svc, twin):
    chat_sync.from_bot(svc, ["Acme Support"], "Acme Support", [conv((0, "user", "Hi"), (1, "assistant", "Hello."))])
    db = tr._private_dir(tr.folder()) / H.DB_NAME
    with sqlite3.connect(str(db)) as c:
        c.execute("DELETE FROM seen")
        c.execute("DELETE FROM seen_filled")
    again = chat_sync.from_bot(svc, ["Acme Support"], "Acme Support",
                               [conv((0, "user", "Hi"), (1, "assistant", "Hello."), cid="other")])
    assert again["history"]["new_messages"] == 0
    raw = db.read_bytes()
    assert b"Hello." not in raw


def test_routine_command_refuses_other_bots_and_arguments(svc, twin, monkeypatch, capsys):
    res = chat_sync.from_bot(svc, ["Acme Support"], "Recipe Planner", [])
    assert not res["ok"] and "not the one after --bot" in res["line"]
    from hermes_plugins.grok_bot_twin.twin import cli
    import io
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"bot_name": "Acme Support", "history": [],
                                                              "profile": "default"})))
    rc = cli.handle(cli_args(["chat-sync", "--bot", "Acme Support"]))
    assert rc == 1 and "chat-sync takes only bot_name, history" in capsys.readouterr().out
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"history": [conv((0, "user", "Hi"))]})))
    rc = cli.handle(cli_args(["chat-sync", "--bot", "Acme Support"]))
    assert rc == 0 and capsys.readouterr().out.startswith("PASS: Acme Support chat sync: 1 new")


def test_no_twin_yet(svc, home, monkeypatch):
    monkeypatch.setattr(svc, "_registry", lambda: {})
    res = chat_sync.from_bot(svc, ["Acme Support"], "Acme Support", [])
    assert not res["ok"] and "no Hermes twin yet" in res["line"]


def cli_args(argv):
    import argparse
    from hermes_plugins.grok_bot_twin.twin import cli
    p = argparse.ArgumentParser()
    cli.setup(p)
    return p.parse_args(argv)


# ---- chat sync (b): this computer pulls ----------------------------------------------------------------------
def read_answer(*msgs):
    return {"rc": 0, "stdout": {"messages": [{"key": k, "role": r, "kind": "text", "text": t, "at": at}
                                             for k, r, t, at in msgs], "proof": "PASS: 2 messages up to t2"}}


WINDOW_OPEN = {"rc": 0, "stdout": {"pid": 4242, "opened_at": "2000-01-02T00:00:00Z", "expires_at": "2000-01-02T00:10:00Z",
                                   "proof": "PASS: launch; port open for 10m"}}


def test_pull_mode_reads_through_the_engine_with_a_cursor(svc, twin, stub):
    config.set_override({"botport_path": "/nonexistent", "chat_sync_mode": "pull", "from_hermes_route": "shell"})
    stub.play(bots=[bots_answer(ACME)], ask=[{**GOOD_ASK, "log": GOOD_ASK["log"][:1]}],
              read=[read_answer(("t1", "user", "Hi", "2000-01-02T00:00:00Z"),
                                ("t2", "bot", "Hello.", "2000-01-02T00:00:05Z")),
                    read_answer(("t2", "bot", "Hello.", "2000-01-02T00:00:05Z"),
                                ("t3", "event", "routine changed", "2000-01-02T00:00:06Z"),
                                ("t4", "user", "Bye", "2000-01-02T00:01:00Z"))])
    res = run(svc, stub)
    assert res["ok"], res["line"]
    assert "this computer reads the chat every 360 min; first sync landed, 2 new message(s)" in res["line"]
    assert "CreateRoutine" not in [a for a in stub.calls() if a[1] == "ask"][0][3]
    second = chat_sync.pull_one(svc, stub.eng, "acme-support")
    assert second["ok"] and second["history"]["new_messages"] == 1 and twin[-1] == ["Bye"]
    reads = [a for a in stub.calls() if a[1] == "read"]
    assert "--since" not in reads[0] and reads[1][reads[1].index("--since") + 1] == "t2"
    assert chat_sync.status()["twins"]["acme-support"]["cursor"] == "t4"


def test_pull_tick_runs_only_in_pull_mode_and_when_due(svc, twin, stub, monkeypatch):
    chat_sync.enrol("acme-support", "pull", ACME["id"])
    monkeypatch.setattr(ge, "from_service", lambda s: stub.eng)
    stub.play(read=[read_answer(("t1", "user", "Hi", "2000-01-02T00:00:00Z"))], launch=[WINDOW_OPEN],
              restore=[{"rc": 0, "stdout": {}}])
    config.set_override({"botport_path": "/nonexistent", "chat_sync_mode": "routine"})
    assert chat_sync.pull_tick(svc) == 0
    config.set_override({"botport_path": "/nonexistent", "chat_sync_mode": "pull", "from_hermes_route": "shell"})
    assert chat_sync.pull_tick(svc) == 1
    assert chat_sync.pull_tick(svc) == 0  # not due again for chat_sync_minutes
    import time
    assert chat_sync.pull_tick(svc, now=time.time() + 361 * 60) == 1


def test_settings_are_validated():
    config.set_override({"chat_sync_mode": "sideways", "chat_sync_minutes": 1})
    assert chat_sync.mode() == chat_sync.DEFAULT_MODE and chat_sync.minutes() == 15
    config.set_override({"chat_sync_mode": "PULL", "chat_sync_minutes": 99999})
    assert chat_sync.mode() == "pull" and chat_sync.minutes() == 1440
    config.set_override(None)


# ---- twin#52: idle-only port windows ------------------------------------------------------------------------------
def _window_setup(stub, monkeypatch, **answers):
    chat_sync.enrol("acme-support", "pull", ACME["id"])
    monkeypatch.setattr(ge, "from_service", lambda s: stub.eng)
    config.set_override({"botport_path": "/nonexistent", "chat_sync_mode": "pull", "from_hermes_route": "shell"})
    answers.setdefault("read", [read_answer(("t1", "user", "Hi", "2000-01-02T00:00:00Z"))])
    answers.setdefault("restore", [{"rc": 0, "stdout": {}}])
    stub.play(**answers)


def _cmds(stub):
    return [a[1] for a in stub.calls()]


def test_window_opens_when_idle_pulls_then_restores(svc, twin, stub, monkeypatch):
    _window_setup(stub, monkeypatch, launch=[WINDOW_OPEN])
    assert chat_sync.pull_tick(svc) == 1
    assert _cmds(stub) == ["launch", "read", "restore"]
    launch = stub.calls()[0]
    assert launch[launch.index("--for") + 1] == "10m" and launch[launch.index("--when-idle") + 1] == "10"
    assert chat_sync.status()["window_skipped"] is None


def test_mac_in_use_skips_without_reading_and_retries_later(svc, twin, stub, monkeypatch):
    import time
    _window_setup(stub, monkeypatch, launch=[{"rc": 2, "stdout": {}, "stderr": "FAIL: launch; the Mac was used 1 "
                                                                               "min ago; try again later"}])
    assert chat_sync.pull_tick(svc) == 0
    assert _cmds(stub) == ["launch"]  # no read, no restore: nothing was opened, nobody interrupted
    assert chat_sync.status()["window_skipped"]["why"] == "in use"
    assert chat_sync.pull_tick(svc, now=time.time() + 10 * 60) == 0 and _cmds(stub) == ["launch"]  # not yet
    stub.play(launch=[WINDOW_OPEN], read=[read_answer(("t1", "user", "Hi", "2000-01-02T00:00:00Z"))],
              restore=[{"rc": 0, "stdout": {}}])
    assert chat_sync.pull_tick(svc, now=time.time() + 31 * 60) == 1
    assert chat_sync.status()["window_skipped"] is None


def test_a_reused_port_is_not_restored(svc, twin, stub, monkeypatch):
    _window_setup(stub, monkeypatch, launch=[{"rc": 0, "stdout": {"reused": True, "proof": "PASS: port already open "
                                                                                          "until 10:00; reused; no restart"}}])
    assert chat_sync.pull_tick(svc) == 1
    assert _cmds(stub) == ["launch", "read"]


def test_port_window_setting_never_launches(svc, twin, stub, monkeypatch):
    _window_setup(stub, monkeypatch)
    config.set_override({"botport_path": "/nonexistent", "chat_sync_mode": "pull", "chat_sync_window": "port"})
    assert chat_sync.pull_tick(svc) == 1
    assert _cmds(stub) == ["read"]


def test_window_settings_are_validated():
    config.set_override({"chat_sync_window": "always", "chat_sync_idle_minutes": 0})
    assert chat_sync.window() == "idle" and chat_sync.idle_minutes() == 1
    config.set_override(None)
    assert chat_sync.minutes() == 360 and chat_sync.mode() == "pull"
