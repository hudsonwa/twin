"""The adapter (twin/grok_engine.py) against the REAL botport Grok engine, on its fake transport.

Needs a botport built with the `grok` feature and its scrubbed fixtures; skipped when either is missing (the Linux
test runner has neither). Point at them with:
  TWIN_GROK_ENGINE_BIN  the built botport binary
  TWIN_GROK_FIXTURES    crates/botport-grok/tests/fixtures/app-1.1.0 of that botport checkout
The fake transport keeps its state for one process only, so every case is one `ask` (GROK-ENGINE-INTERFACES.md).
"""
from __future__ import annotations

import os
import json
import shutil
from pathlib import Path

import pytest

from twin_testlib import home, svc  # noqa: F401
from hermes_plugins.grok_bot_twin.twin import from_hermes, grok_engine as ge

# a botport with the Grok engine, and its crates/botport-grok/tests/fixtures/app-1.1.0 folder (skipped without them)
BIN = Path(os.environ.get("TWIN_GROK_ENGINE_BIN") or "/nonexistent/botport")
FIX = Path(os.environ.get("TWIN_GROK_FIXTURES") or "/nonexistent/fixtures")
pytestmark = pytest.mark.skipif(not (BIN.is_file() and (FIX / "roster.json").is_file()),
                                reason="no botport with the Grok engine, or no fixtures, on this computer")
MAIN = "Main Bot"  # the fixtures' first (main) bot, whose chat transcript-idle.json is


def engine(tmp_path, turn=None, fix=None):
    extra = ["--transport", "fake", "--fixtures", str(fix or FIX), "--no-log"] + (["--turn", turn] if turn else [])
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "BOTPORT_HOME": str(tmp_path / ".botport")}
    return ge.GrokEngine(str(BIN), env=env, extra=extra)


def test_engine_is_found_by_its_status_answer(tmp_path):
    assert ge.has_engine(engine(tmp_path).status())


def test_bots(tmp_path):
    res = engine(tmp_path).bots()
    assert res.ok and res.proof.startswith("PASS"), res
    names = [b["name"] for b in ge.bots_of(res)]
    assert MAIN in names and all(b["id"] for b in ge.bots_of(res))


def test_ask_reply_ready(tmp_path):
    res = engine(tmp_path, "reply-ready").ask(MAIN, "Are you ready?", 60, 1)
    assert res.exit == ge.DONE and res.proof.startswith("PASS"), (res.exit, res.proof, res.data.get("error"))
    assert any("READY" in m["text"] for m in ge.messages_of(res) if m["role"] == "bot")
    assert ge.last_key(res)


def test_ask_needs_approval_is_exit_3(tmp_path):
    res = engine(tmp_path, "needs-approval").ask(MAIN, "Run the command", 60, 1)
    assert res.exit == ge.NEEDS_USER, (res.exit, res.proof)
    assert ge.needs_input_of(res).startswith(("an approval in Grok", "an answer in Grok"))


def test_ask_still_working_is_exit_2(tmp_path):
    res = engine(tmp_path, "long-reply").ask(MAIN, "Write a lot", 3, 1)
    assert res.exit == ge.STILL_WORKING, (res.exit, res.proof)


def test_unknown_bot_is_exit_1(tmp_path):
    res = engine(tmp_path).ask("No Such Bot Here", "hi", 5, 1)
    assert res.exit == ge.OTHER and res.proof.startswith("FAIL")


def test_from_hermes_end_to_end_without_a_pass_line_is_a_fail(svc, tmp_path):
    """The whole from-hermes path through the real engine: the turn replies "READY", not a PASS line, so the bot's
    word is missing and the run is a FAIL that says so (nothing ran on this computer either)."""
    res = from_hermes.run(svc, [MAIN], eng=engine(tmp_path, "reply-ready"), how="shell")
    assert not res["ok"] and "did not report a PASS or FAIL line" in res["line"], res["line"]


def test_from_hermes_needs_approval_through_the_real_engine(svc, tmp_path):
    res = from_hermes.run(svc, [MAIN], eng=engine(tmp_path, "needs-approval"), how="shell")
    assert not res["ok"] and res.get("waiting") and "--wait" in res["line"], res["line"]


def fixtures_with(tmp_path, **roster):
    """A copy of the scrubbed fixtures with roster.json fields changed (app_version, localToolPermission)."""
    d = tmp_path / "fix"
    shutil.copytree(FIX, d)
    r = json.loads((d / "roster.json").read_text(encoding="utf-8"))
    r.update(roster)
    (d / "roster.json").write_text(json.dumps(r), encoding="utf-8")
    return d


def test_status_reads_the_local_tool_permission(tmp_path):
    assert ge.local_permission(engine(tmp_path).status()) == "ask"  # (the fixtures' setting)
    fix = fixtures_with(tmp_path, localToolPermission="always")
    assert ge.local_permission(engine(tmp_path, fix=fix).status()) == "always"


def test_routine_mode_is_refused_under_ask_and_offered_under_always(svc, tmp_path):
    from hermes_plugins.grok_bot_twin.twin import config
    config.set_override({"botport_path": "/nonexistent", "chat_sync_mode": "routine"})
    res = from_hermes.run(svc, [MAIN], eng=engine(tmp_path, "reply-ready"), how="shell")
    assert not res["ok"] and "it reads Ask every time" in res["line"], res["line"]
    fix = fixtures_with(tmp_path, localToolPermission="always")
    res = from_hermes.run(svc, [MAIN], eng=engine(tmp_path, "reply-ready", fix=fix), how="shell")
    assert "Always allow" not in res["line"] and "did not report a PASS or FAIL line" in res["line"], res["line"]


def test_untested_version_write_is_exit_4_naming_the_canary(svc, tmp_path):
    fix = fixtures_with(tmp_path, app_version="9.9.9")
    res = engine(tmp_path, "reply-ready", fix=fix).ask(MAIN, "hi", 30, 1)
    assert res.exit == ge.REFUSED, (res.exit, res.proof)
    assert ge.refused_why(res) == ge.CANARY
    out = from_hermes.run(svc, [MAIN], eng=engine(tmp_path, "reply-ready", fix=fix), how="shell")
    assert not out["ok"] and "run botport grok canary" in out["line"], out["line"]
    out = from_hermes.run(svc, [MAIN], eng=engine(tmp_path, "reply-ready", fix=fix))  # (the export route: same)
    assert not out["ok"] and "run botport grok canary" in out["line"], out["line"]


# ---- P3 (botport feat/grok-engine-p3): routines, files fetch, and the export route of from-hermes --------------
def p3(eng):
    """Skip when this botport predates P3 (no routines/files commands)."""
    res = eng.routines(MAIN)
    if res.exit == ge.OTHER and "unknown" in (res.proof + json.dumps(res.data.get("error") or {})).lower():
        pytest.skip("this botport has no P3 commands (routines, files)")
    return res


def test_routines_list_is_read_by_the_engine(tmp_path):
    res = p3(engine(tmp_path))
    got = ge.routines_of(res)
    assert res.ok and got, (res.exit, res.proof)
    assert all(r["name"] and r["schedule"] for r in got)


def with_attachment(tmp_path, name="twin-export.json"):
    """The fixtures with one synthetic file the main bot sent in chat (the transcript entry P0 recorded)."""
    d = fixtures_with(tmp_path)
    t = json.loads((d / "transcript-idle.json").read_text(encoding="utf-8"))
    last = t["chat"]["entries"][-1]
    t["chat"]["entries"].append({"kind": "send-message", "id": "t46s1", "message": {
        "type": "attachment", "url": "file:///home/box/agent-data/assets/synthetic-1.bin", "file_name": name,
        "source_path": f"/workspace/{name}", "alt": name}, "timestampMs": last["timestampMs"] + 1000,
        "requestId": last.get("requestId"), "seq": last["seq"] + 1})
    (d / "transcript-idle.json").write_text(json.dumps(t), encoding="utf-8")
    return d


def test_a_sent_file_shows_in_read_and_fetch_never_leaves_a_partial_file(tmp_path):
    fix = with_attachment(tmp_path)
    eng = engine(tmp_path, fix=fix)
    p3(eng)
    msgs = ge.messages_of(eng.read(MAIN, None, 50))
    assert msgs[-1].get("file") == {"name": "twin-export.json"}, msgs[-1]
    out = tmp_path / "out"
    out.mkdir()
    res = eng.fetch(MAIN, msgs[-1]["key"], str(out))
    # (the fake transport's preview has no bytes for a fixture-only file: the CLI fails, and saves nothing)
    assert res.exit == ge.OTHER and res.proof.startswith("FAIL") and ge.saved_of(res) is None
    assert list(out.iterdir()) == []


def test_from_hermes_export_route_through_the_real_engine(svc, tmp_path):
    """status, read, routines and ask through the real engine: the turn answers "READY", which is no export, so the
    run is a FAIL that says so and nothing is written."""
    p3(engine(tmp_path))
    res = from_hermes.run(svc, [MAIN], eng=engine(tmp_path, "reply-ready"))
    assert not res["ok"] and "the export was refused: the reply holds no ```json block" in res["line"], res["line"]
    assert "nothing was written in Hermes" in res["line"]


def test_from_hermes_export_route_needs_approval_is_a_fail_nothing_clicked(svc, tmp_path):
    p3(engine(tmp_path))
    res = from_hermes.run(svc, [MAIN], eng=engine(tmp_path, "needs-approval"))
    assert not res["ok"] and "nothing was clicked" in res["line"], res["line"]
