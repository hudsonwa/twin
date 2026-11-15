"""`hermes twin sync "NAME" --from-file|--stdin` and `sync_both.sync_bot`: both sides level, memory included.

Invented bots only (Acme Support). botport is stood in by a fake runner that records each call and plays botport
v0.2.1's reports (apply, sync --direction h2g writing the Hermes bundle, drift both ways).
"""
from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stderr, redirect_stdout

import pytest

from twin_testlib import cli, home, service, svc  # noqa: F401
from hermes_plugins.grok_bot_twin.twin import engine as E
from hermes_plugins.grok_bot_twin.twin import store, sync_both

STATE = {"instructions": "Answer Acme support questions briefly.",
         "skills": [{"name": "refunds", "description": "Refund steps", "instructions": "Check the order first."}],
         "memory": ["The owner prefers short answers.", "password: hunter2-Secret-99"],
         "user_facts": ["Lives in Lisbon."]}


class FakeBotport:
    def __init__(self, central, facts=(), skills=(), conflict=None, proof=None):
        self.calls, self.central = [], central
        self.facts, self.skills, self.conflict = list(facts), dict(skills), conflict
        self.proof = proof or {"in_sync": True, "items": [], "h2g": {"items": []}}

    def __call__(self, args):
        self.calls.append(args)
        cmd = args[0]
        prof = next(a.split("=", 1)[1] for a in args if a.startswith("--profile="))
        if (store.profile_home(prof) / "botport.mirror.json").exists():  # as real botport v0.2.1 refuses
            raise E.EngineError("exit_2", f"botport {cmd} failed: Hermes bot {prof} is a mirrored profile")
        if cmd == "drift" and "--direction=g2h" in args:
            items = [{"area": "skill", "path": f"skills/grok-twin/{self.conflict}", "status": "conflict"}] \
                if self.conflict else []
            return {"in_sync": not items, "items": items, "_rc": 1 if items else 0}
        if cmd == "apply":
            return {"items": [{"area": "memory", "path": "x", "status": "update"}], "_rc": 3 if self.conflict else 0}
        if cmd == "sync":
            out = self.central / "sync" / "acme-support" / "hermes-out"
            (out / "memory").mkdir(parents=True, exist_ok=True)
            (out / "memory" / "memory.jsonl").write_text(
                "".join(json.dumps({"tier": "note", "source": "hermes", "fact": f}) + "\n" for f in self.facts))
            for n, t in self.skills.items():
                (out / "normalized" / "skills" / n).mkdir(parents=True, exist_ok=True)
                (out / "normalized" / "skills" / n / "SKILL.md").write_text(t)
            return {"h2g": {"items": []}, "_rc": 0}
        return dict(self.proof, _rc=0 if self.proof.get("in_sync") else 1)


@pytest.fixture
def twin(svc, monkeypatch):
    svc._save_registry({"acme-support": {"pair_id": "acme-support", "grok": {"id": "g-acme", "name": "Acme Support"},
                                         "hermes": {"profile": "acme-support"}, "created_at": "2026-11-01T00:00:00Z"}})
    monkeypatch.setattr(svc, "engine_for", lambda pid: pytest.fail("the fake runner stands in for botport"))
    return svc


def test_clean_both_ways_passes_and_calls_botport_in_order(twin):
    fake = FakeBotport(twin.central)
    res = sync_both.sync_bot(twin, "acme-support", STATE, runner=fake)
    assert res["ok"] and res["line"] == "PASS: drift clean both ways"
    assert [(c[0], next((x for x in c if x.startswith("--direction")), "")) for c in fake.calls] == [
        ("drift", "--direction=g2h"), ("apply", ""), ("sync", "--direction=h2g"), ("drift", "")]
    assert all("--no-cron" in c and "--profile=acme-support" in c for c in fake.calls)
    assert "--adopt" in fake.calls[1]
    spec = (twin.central / "sync" / "acme-support" / "botport.toml").read_text()
    assert 'profile = "acme-support"' in spec and "[hermes_export]" in spec


def test_input_becomes_grok_bot_export_with_secrets_scrubbed(twin):
    sync_both.sync_bot(twin, "acme-support", json.dumps(STATE), runner=FakeBotport(twin.central))
    doc = json.loads((twin.central / "sync" / "acme-support" / "grok-state.json").read_text())
    bot = doc["bots"][0]
    assert doc["format"] == "grok-bot-export" and doc["version"] == 1 and bot["name"] == "Acme Support"
    assert bot["memories"] == ["The owner prefers short answers."] and bot["user_facts"] == ["Lives in Lisbon."]
    assert bot["skills"][0]["name"] == "refunds" and "hunter2" not in json.dumps(doc)


def test_grok_bot_export_document_is_taken_as_is(twin):
    exp = {"format": "grok-bot-export", "version": 1, "bots": [{"name": "Acme Support", "memories": ["A fact."]}]}
    sync_both.sync_bot(twin, "acme-support", exp, runner=FakeBotport(twin.central))
    doc = json.loads((twin.central / "sync" / "acme-support" / "grok-state.json").read_text())
    assert doc["bots"][0]["memories"] == ["A fact."]
    with pytest.raises(E.EngineError):
        sync_both.sync_bot(twin, "acme-support", {"format": "grok-bot-export", "bots": []},
                           runner=FakeBotport(twin.central))


def test_hermes_learned_goes_back_as_bundle_for_grok(twin):
    fake = FakeBotport(twin.central, facts=["Ships on Fridays."], skills={"triage": "# triage\nSort tickets."},
                       proof={"in_sync": False, "items": [], "h2g": {"items": [
                           {"area": "memory", "path": "memories/MEMORY.md", "status": "create"},
                           {"area": "skill", "path": "skills/triage", "status": "create"}]}})
    res = sync_both.sync_bot(twin, "acme-support", STATE, runner=fake)
    fg = res["for_grok"]
    assert fg["format"] == "twin-sync-for-grok/1" and "UpdateMemory" in fg["how"]
    assert fg["memory"] == [{"tier": "note", "fact": "Ships on Fridays."}]
    assert fg["skills"] == [{"name": "triage", "text": "# triage\nSort tickets."}]
    assert res["ok"] and res["line"].startswith("PASS: Grok -> Hermes level; Hermes -> Grok: 1 fact(s) and 1 skill")
    kept = json.loads((twin.central / "sync" / "acme-support" / "for-grok.json").read_text())
    assert kept == fg


def test_both_sides_edited_keeps_hermes_and_grok_copy_as_restore_point(twin):
    skill = store.profile_home("acme-support") / "skills" / "grok-twin" / "refunds"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# refunds\nHermes edit.")
    fake = FakeBotport(twin.central, conflict="refunds", proof={"in_sync": False, "h2g": {"items": []}, "items": [
        {"area": "skill", "path": "skills/grok-twin/refunds", "status": "conflict"}]})
    res = sync_both.sync_bot(twin, "acme-support", STATE, runner=fake)
    assert res["ok"] and res["grok_to_hermes"]["conflicts"] == ["refunds"]
    assert {"name": "refunds", "text": "# refunds\nHermes edit."} in res["for_grok"]["skills"]
    point = twin.central / "sync" / "acme-support" / "restore" / res["restore_point"] / "refunds.grok.json"
    assert json.loads(point.read_text())["instructions"] == "Check the order first."


def test_difference_nobody_carries_fails(twin):
    fake = FakeBotport(twin.central, proof={"in_sync": False, "h2g": {"items": []}, "items": [
        {"area": "soul", "path": "SOUL.md", "status": "update"}]})
    res = sync_both.sync_bot(twin, "acme-support", STATE, runner=fake)
    assert not res["ok"] and res["line"].startswith("FAIL: drift is not clean (1 item differ")


def test_twin_without_hermes_bot_refuses(svc):
    svc._save_registry({"acme-support": {"pair_id": "acme-support", "grok": {"name": "Acme Support"}, "hermes": {}}})
    with pytest.raises(E.EngineError):
        sync_both.sync_bot(svc, "acme-support", STATE, runner=FakeBotport(svc.central))


def test_runner_accepts_conflict_exit_and_refuses_errors(monkeypatch, tmp_path):
    class Eng:
        hermes_home = tmp_path

        def _verify(self):
            return "/bin/botport", {}

        def _env(self):
            return {}
    seen = []

    def fake_run(argv, timeout, env=None):
        seen.append(argv)
        return rc, json.dumps({"items": []}).encode(), b"botport: ERROR: bad spec", False
    monkeypatch.setattr(E, "run_capped", fake_run)
    run = sync_both._botport_runner(Eng())
    for rc in (0, 1, 3):
        assert run(["apply", "--bundle=x"])["_rc"] == rc
    assert seen[0][:2] == ["/bin/botport", "apply"] and "--json" in seen[0]
    rc = 2
    with pytest.raises(E.EngineError) as exc:
        run(["apply"])
    assert "bad spec" in exc.value.message


# ---------------------------------------------------------------------------------------------- the command

def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = cli.main(argv)
    return rc, out.getvalue(), err.getvalue()


def test_cli_last_line_is_the_verdict(twin, monkeypatch, tmp_path):
    f = tmp_path / "state.json"
    f.write_text(json.dumps(STATE))
    monkeypatch.setattr(cli, "_svc", lambda: twin)
    monkeypatch.setattr(sync_both, "_botport_runner", lambda eng: FakeBotport(twin.central, facts=["Ships on Fridays."]))
    monkeypatch.setattr(twin, "engine_for", lambda pid: None)
    rc, out, _ = run(["sync", "Acme Support", "--from-file", str(f)])
    lines = out.strip().splitlines()
    assert rc == 0 and lines[-1].startswith('PASS: sync of "Acme Support": Grok -> Hermes level')
    assert "Held back as suspected secrets: 1 fact(s)" in out and "Ships on Fridays." in out
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(STATE)))
    rc, out, _ = run(["sync", "Acme Support", "--stdin", "--json"])
    body = out.strip().rsplit("\n", 1)
    assert rc == 0 and json.loads(body[0])["for_grok"]["memory"][0]["fact"] == "Ships on Fridays."
    assert body[1].startswith("PASS:")


def test_cli_failure_is_one_fail_line(twin, monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "_svc", lambda: twin)
    f = tmp_path / "state.json"
    f.write_text("not json")
    rc, out, _ = run(["sync", "Acme Support", "--from-file", str(f)])
    assert rc == 1 and out.strip().splitlines()[-1] == 'FAIL: sync of "Acme Support": That is not JSON.'


def test_sync_without_state_is_still_check(monkeypatch):
    seen = []
    monkeypatch.setattr(cli, "cmd_sync", lambda a: seen.append((a.pair, a.pair_opt)) or 0)
    assert run(["sync"])[0] == 0 and run(["sync", "--pair", "acme-support"])[0] == 0
    assert seen == [(None, None), (None, "acme-support")]


def test_hermes_to_grok_is_scrubbed_too(twin, capsys):
    """H3: a Hermes fact or skill line that looks like a secret never reaches for-grok.json or the CLI output."""
    key = "sk-ant-api03-" + "Q" * 40
    fake = FakeBotport(twin.central, facts=["Ships on Fridays.", f"The deploy token is {key}"],
                       skills={"deploy": f"# deploy\nUse api_key={key}\nThen tell the owner."},
                       proof={"in_sync": False, "items": [], "h2g": {"items": [
                           {"area": "skill", "path": "skills/deploy", "status": "create"}]}})
    res = sync_both.sync_bot(twin, "acme-support", STATE, runner=fake)
    fg = res["for_grok"]
    assert fg["memory"] == [{"tier": "note", "fact": "Ships on Fridays."}]
    assert fg["skills"][0]["name"] == "deploy" and "Then tell the owner." in fg["skills"][0]["text"]
    assert res["scrubbed"]["to_grok_facts_left_out"] == 1 and res["scrubbed"]["to_grok_lines_hidden"] == 1
    kept = (twin.central / "sync" / "acme-support" / "for-grok.json").read_text()
    assert key not in kept and key not in json.dumps(res)


def test_default_profile_is_refused(svc):
    """L1: sync_bot never writes the Hermes root's own bot."""
    svc._save_registry({"acme-support": {"pair_id": "acme-support", "grok": {"name": "Acme Support"},
                                         "hermes": {"profile": "default"}}})
    ran = []
    with pytest.raises(E.EngineError) as exc:
        sync_both.sync_bot(svc, "acme-support", STATE, runner=lambda a: ran.append(a) or {})
    assert "default" in exc.value.message and not ran


def test_owned_profile_is_made_bot_driven_before_botport_is_asked(twin, monkeypatch):
    prof = store.ensure_dir(store.profile_home("acme-support"))
    (prof / "botport.mirror.json").write_text("{}")  # `botport twin create` made it: spec commands refuse it
    with pytest.raises(E.EngineError, match="mirrored profile"):
        FakeBotport(twin.central)(["apply", "--profile=acme-support"])
    removed = []

    class Eng:
        def remove(self, pid):
            removed.append(pid)
            (prof / "botport.mirror.json").unlink()

    monkeypatch.setattr(twin, "engine_for", lambda pid: Eng())
    res = sync_both.sync_bot(twin, "acme-support", STATE, runner=FakeBotport(twin.central))
    assert res["ok"] and removed == ["acme-support"]
    assert twin._registry()["acme-support"]["driver"] == "bot"
    sync_both.sync_bot(twin, "acme-support", STATE, runner=FakeBotport(twin.central))
    assert removed == ["acme-support"]  # once


def test_env_is_written_only_when_the_sync_passes(twin, monkeypatch):
    """S3: a FAILed sync leaves no new .env line (the value stays in the OS store only)."""
    from hermes_plugins.grok_bot_twin.twin import secret_ref
    written = []
    monkeypatch.setattr(secret_ref.Refs, "to_env", lambda self, home: written.append(home) or 0)
    bad = FakeBotport(twin.central, proof={"in_sync": False, "items": [{"area": "skill", "path": "skills/x",
                                                                        "status": "update"}], "h2g": {"items": []}})
    assert not sync_both.sync_bot(twin, "acme-support", STATE, runner=bad)["ok"] and written == []
    assert sync_both.sync_bot(twin, "acme-support", STATE, runner=FakeBotport(twin.central))["ok"] and len(written) == 1
    assert sync_both.sync_bot(twin, "acme-support", STATE, runner=FakeBotport(twin.central), write_env=False)["ok"]
    assert len(written) == 1
