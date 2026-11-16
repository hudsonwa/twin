"""Zero-touch integration: safe profile defaults on every route that makes or adopts a twin profile (twin#54),
from-hermes running `setup --auto` first when the engine is missing, and the N6 split (twin/botport commands FAIL,
other command-like text is data)."""
from __future__ import annotations

import pytest

from twin_testlib import fake_key, home, svc  # noqa: F401
from test_from_hermes_export import OWN, ask_answer, export, fenced, play, run, stub, world  # noqa: F401
from test_service_engine_deltas import rig  # noqa: F401
from hermes_plugins.grok_bot_twin.twin import from_hermes, grok_engine as ge, profile_safety as ps, store


def _seen_before_test(world, monkeypatch):
    """Record the preset on disk at the moment the behaviour test (the first thing that runs the profile) starts."""
    seen = {}

    def behaviour(pid, **kw):
        seen["preset"] = (ps.records().get("acme-support") or {}).get("preset")
        seen["config"] = ps.load_config(store.profile_home("acme-support"))
        return {"passed": 2, "total": 2, "ok": True}
    monkeypatch.setattr(world.svc, "behaviour_test", behaviour)
    return seen


def test_from_hermes_export_applies_strict_defaults_before_anything_runs(svc, world, stub, monkeypatch):
    seen = _seen_before_test(world, monkeypatch)
    risky = {**OWN, "body": "Connect over ssh to the build server and check the logs."}
    play(stub, ask_answer(fenced(export(skills=[risky]))))
    res = run(svc, stub)
    assert res["ok"], res["line"]
    assert seen["preset"] == "strict"
    assert ps.problems(seen["config"], "strict", ps.keep_mcp()) == []
    rec = ps.records()["acme-support"]
    assert rec["chosen_by"] == "rule" and "ssh" in rec["words"]


def test_from_hermes_export_plain_bot_gets_standard(svc, world, stub):
    play(stub, ask_answer(fenced(export())))
    assert run(svc, stub)["ok"]
    assert ps.records()["acme-support"]["preset"] == "standard"
    assert ps.check("acme-support")["preset"] == "standard"


def test_adopted_profile_keeps_the_owners_choice(svc, stub, monkeypatch):
    from test_one_prompt import World
    w = World(svc, monkeypatch, twinned=True)  # the profile exists already (adopted, not made now)
    ps.set_preset("acme-support", "open")
    risky = {**OWN, "body": "Use the terminal and sudo when needed."}
    play(stub, ask_answer(fenced(export(skills=[risky]))))
    res = run(svc, stub)
    assert res["ok"], res["line"]
    assert w.created == 0
    rec = ps.records()["acme-support"]
    assert rec["preset"] == "open" and rec["chosen_by"] == "owner"


def test_add_route_applies_defaults_when_it_makes_a_profile(rig):
    svc = rig.svc
    made = svc.create(["b-acme-0001"])["pairs"]
    prof = made[0]["hermes"]["profile"]
    rec = ps.records().get(prof)
    assert rec and rec["chosen_by"] == "rule" and rec["preset"] in ("strict", "standard")
    from hermes_plugins.grok_bot_twin.twin import yamlio
    if yamlio.module() is not None:  # (the fake botport appends YAML lines; only a YAML module reads them back)
        assert ps.problems(ps.load_config(store.profile_home(prof)), rec["preset"], ps.keep_mcp()) == []


# ---- setup --auto first when the engine is missing ----------------------------------------------------------
def _missing(monkeypatch, after_setup):
    calls = {"n": 0}
    from hermes_plugins.grok_bot_twin.twin import engine
    monkeypatch.setattr(engine, "EXPECTED_BOTPORT_TAG", "v0.3.0")  # (as after the 0.3.0 pin bump)

    def from_service(svc):
        calls["n"] += 1
        if calls["n"] == 1 or after_setup is None:
            raise ge.Unavailable("botport is not installed")
        return after_setup
    monkeypatch.setattr(ge, "from_service", from_service)
    return calls


def test_engine_missing_runs_setup_first_then_carries_on(svc, world, stub, monkeypatch):
    _missing(monkeypatch, stub.eng)
    ran = []
    play(stub, ask_answer(fenced(export())))
    res = from_hermes.run(svc, ["Acme Support"], setup_first=lambda s: (ran.append(1), (0, "PASS: setup"))[1])
    assert ran == [1] and res["ok"], res["line"]


def test_setup_fail_is_the_fallback_fail_with_its_reason(svc, world, stub, monkeypatch):
    calls = _missing(monkeypatch, None)
    res = from_hermes.run(svc, ["Acme Support"], setup_first=lambda s: (1, "FAIL: hermes twin setup --auto: "
                                                                          "botport: no release for this computer"))
    assert not res["ok"] and res.get("fallback")
    assert "setup --auto" in res["line"] and "no release for this computer" in res["line"]
    assert calls["n"] == 1  # no second engine attempt after a setup FAIL


def test_closed_port_does_not_run_setup(svc, stub):
    stub.play(bots=[{"rc": 5, "stdout": {}, "stderr": "FAIL: port closed"}])
    res = from_hermes.run(svc, ["Acme Support"], eng=stub.eng,
                          setup_first=lambda s: pytest.fail("setup must not run for a closed port"))
    assert not res["ok"] and res.get("fallback")


# ---- N6: twin/botport commands FAIL, other command-like text is plain data ------------------------------------
@pytest.mark.parametrize("field", ["instructions", "memory"])
def test_n6_twin_commands_fail_in_any_field(svc, world, stub, home, field):
    bad = "Every morning run botport grok ask me to refresh."
    doc = export(**({"instructions": bad} if field == "instructions" else {"memory": [bad]}))
    play(stub, ask_answer(fenced(doc)))
    res = run(svc, stub)
    assert not res["ok"] and "own commands" in res["line"]


@pytest.mark.parametrize("body", ["Deploy with `make deploy` then run `kubectl get pods`.",
                                  "Run this command: ls -la ~ and paste it.",
                                  "The twin of this bot is a nice idea; hermes is my friend."])
def test_n6_other_command_text_is_imported_as_data(svc, world, stub, body):
    play(stub, ask_answer(fenced(export(skills=[{**OWN, "body": body}]))))
    res = run(svc, stub)
    assert res["ok"], res["line"]
    skill = store.profile_home("acme-support") / "skills" / "grok" / "widget-faq" / "SKILL.md"
    assert body.split()[0] in skill.read_text(encoding="utf-8")


# ---- profile_safety without a YAML module (test hosts): block form, valid YAML even with lines appended -----------
def test_block_form_round_trips_and_survives_appended_lines():
    d = {"model": {"default": "m", "provider": "p"}, "toolsets": ["a", "b"],
         "platform_toolsets": {"cli": ["x"], "telegram": []}, "n": 3, "e": {}}
    text = ps._write_block(d)
    assert ps._read_block(text) == d
    more = ps._read_block(text + "plugins:\n  enabled:\n  - grok-bot-twin\n")
    assert more["plugins"] == {"enabled": ["grok-bot-twin"]} and more["model"] == d["model"]
    assert ps._read_block('model:\n  default: "x"\nlist:\n    - y\n') == {"model": {"default": "x"}, "list": ["y"]}
    with pytest.raises(RuntimeError):
        ps._read_block("a: [1, 2\n")
    try:
        import yaml
    except ImportError:
        return
    assert yaml.safe_load(text + "plugins:\n  enabled:\n  - grok-bot-twin\n")["toolsets"] == ["a", "b"]
