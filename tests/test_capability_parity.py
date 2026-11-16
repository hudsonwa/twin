"""twin#71: a twin can do what its Grok bot can do (preset parity, the default), on the desktop app and Telegram
alike; risky actions still ask first and the hard floors hold. Invented profiles only (meals, ops-twin,
acme-support)."""
from __future__ import annotations

from pathlib import Path

from twin_testlib import home, svc  # noqa: F401
from hermes_plugins.grok_bot_twin.twin import auto_setup, profile_safety as ps

BASE = """model:
  provider: custom
  base_url: http://127.0.0.1:8000/v1
  default: local-model
toolsets: [terminal, web, memory, cronjob]
platform_toolsets:
  cli: [terminal, file, web, browser, memory]
  telegram: [hermes-telegram, browser, terminal, delegation]
mcp_servers:
  kb: {url: http://127.0.0.1:1/mcp}
approvals:
  mode: 'off'
"""
PARITY = ["browser", "web", "x_search", "terminal", "file", "code_execution", "image_gen", "computer_use"]


def prof(home: Path, name: str, config: str = BASE, soul: str = "Plan weekly meals.") -> Path:
    h = home / "profiles" / name
    h.mkdir(parents=True, exist_ok=True)
    (h / "config.yaml").write_text(config, encoding="utf-8")
    (h / "SOUL.md").write_text(soul, encoding="utf-8")
    return h


def floors(c: dict) -> None:
    a = c["approvals"]
    assert a["mode"] == "manual" and a["cron_mode"] == a["unattended_mode"] == a["single_query_mode"] == "deny"
    assert c["cron"]["allow_agent_scheduling"] is False and c["terminal"]["env_passthrough"] == []
    assert {"cronjob", "delegation"} <= set(c["agent"]["disabled_toolsets"])


# ---- create: parity by default ------------------------------------------------------------------------------------
def test_create_default_is_parity_and_disables_nothing_the_bot_has(home):
    h = prof(home, "meals")
    got = ps.apply_default("meals")
    assert got["preset"] == "parity" and got["chosen_by"] == "rule"
    c = ps.load_config(h)
    assert not set(PARITY) & set(c["agent"]["disabled_toolsets"])
    floors(c)
    assert c["toolsets"] == ["terminal", "web", "memory"]  # (only the floors leave the lists)
    assert c["platform_toolsets"]["cli"] == ["terminal", "file", "web", "browser", "memory"]
    assert list(c["mcp_servers"]) == ["kb"] and c["model"]["default"] == "local-model"
    assert all(x["on"] for x in got["capabilities"])
    res = ps.check("meals")
    assert res["ok"], res
    line = ps.line("meals", res)
    assert line.startswith("PASS: twin meals safety parity (rule), model local; capabilities: browser ✓, web ✓, "
                           "X search ✓, shell ✓ (risky commands ask first), files ✓")
    assert "image generation ✓" in line and "computer use ✓" in line and "off: agent scheduling and delegation" in line


def test_telegram_toolset_path_keeps_every_capability_and_asks_in_the_chat(home):
    """The live report: in Telegram the twin said it had no shell or browser. Hermes' Telegram toolset
    (hermes-telegram) is full access; only the twin's disabled_toolsets narrowed it, on every platform."""
    h = prof(home, "acme-support")
    ps.apply_default("acme-support")
    c = ps.load_config(h)
    assert c["platform_toolsets"]["telegram"] == ["hermes-telegram", "browser", "terminal"]
    assert not {"browser", "terminal", "web", "file"} & set(c["agent"]["disabled_toolsets"])
    assert "platforms" not in c or (c["platforms"].get("telegram") or {}).get("enabled") is not False
    assert c["approvals"]["mode"] == "manual"  # risky commands: Telegram's approval buttons or /approve


def test_risky_words_are_named_not_a_silent_lockdown(home):
    prof(home, "ops-twin", soul="Runs shell commands on the deploy server.")
    got = ps.apply_default("ops-twin")
    assert got["preset"] == "parity" and "shell" in got["words"]
    assert ps.choose(["Runs shell commands"])[0] == "strict"  # (what the owner's opt-in narrowing would pick)


def test_hard_floors_hold_and_a_broken_floor_fails_the_check(home):
    h = prof(home, "meals")
    ps.apply_default("meals")
    c = ps.load_config(h)
    c["approvals"]["mode"] = "off"
    c["cron"]["allow_agent_scheduling"] = True
    c["platform_toolsets"]["telegram"].append("cronjob")
    ps.write_config(h, c)
    bad = ps.check("meals")["problems"]
    assert "approvals.mode" in bad and "cron.allow_agent_scheduling" in bad
    assert "toolsets (scheduling or delegation)" in bad


def test_owner_can_narrow_and_go_back(home):
    h = prof(home, "meals")
    ps.apply_default("meals")
    ps.set_preset("meals", "standard")
    c = ps.load_config(h)
    assert {"browser", "terminal"} <= set(c["agent"]["disabled_toolsets"])
    res = ps.check("meals")
    assert res["ok"] and "browser ✗ (off: the owner chose standard)" in ps.line("meals", res)
    assert ps.apply_default("meals")["preset"] == "standard"  # the owner's choice is kept
    ps.set_preset("meals", "parity")
    assert not {"browser", "terminal"} & set(ps.load_config(h)["agent"]["disabled_toolsets"])


def test_service_create_note_names_capabilities(svc, home, monkeypatch):  # noqa: F811
    prof(home, "meals")
    monkeypatch.setattr(svc, "_profile_home", lambda p: home / "profiles" / p)
    note = svc._safe_defaults("meals")
    assert note.startswith("meals (parity) capabilities: browser ✓, web ✓") and "Telegram alike" in note


# ---- setup --auto: existing twins move once ------------------------------------------------------------------------
def _old_standard(home, name="meals"):
    """A twin the 0.5.0 rule set to standard: its pre-twin copy is kept, the lists were narrowed."""
    h = prof(home, name)
    (h / ps.BACKUP_NAME).write_text(BASE, encoding="utf-8")
    c = ps.want(ps.load_config(h), "standard")
    p = ps.write_config(h, c)
    import hashlib
    ps.record(name, preset="standard", chosen_by="rule", words=[], before_written=True, had_config=True,
              wrote_sha=hashlib.sha256(p.read_bytes()).hexdigest(), wrote_owned=ps.owned_sha(ps.load_config(h)))
    return h


class Svc:
    def __init__(self, *profiles):
        self.profiles = profiles

    def _registry(self):
        return {f"p{i}": {"hermes": {"profile": p}} for i, p in enumerate(self.profiles)}


def test_setup_auto_moves_rule_chosen_twins_once_and_says_what_changed(home):
    h = _old_standard(home)
    assert "browser" in ps.load_config(h)["agent"]["disabled_toolsets"]
    prof(home, "owned")
    ps.set_preset("owned", "standard")  # the owner's own choice: left alone
    said = []
    note = auto_setup.parity_note(Svc("meals", "owned"), said.append)
    assert note.startswith("; twins moved to parity with their Grok bot (risky actions still ask first): meals "
                           "standard -> parity (turned on: browser, web, X search, shell, files, code, image "
                           "generation, computer use)")
    assert "owned" not in note and len(said) == 1
    c = ps.load_config(h)
    assert not set(PARITY) & set(c["agent"]["disabled_toolsets"])
    floors(c)
    # the lists standard narrowed come back from the pre-twin copy (the Telegram path included)
    assert c["platform_toolsets"]["telegram"] == ["hermes-telegram", "browser", "terminal"]
    assert c["toolsets"] == ["terminal", "web", "memory"] and list(c["mcp_servers"]) == ["kb"]
    rec = ps.records()["meals"]
    assert rec["preset"] == "parity" and rec["parity_migrated"] and rec["migrated_from"] == "standard"
    assert ps.check("meals")["ok"]
    assert ps.records()["owned"]["preset"] == "standard"
    assert auto_setup.parity_note(Svc("meals", "owned"), said.append) == ""  # once
    # stop still puts the pre-twin config back (the migration's write is the one safety last wrote)
    assert ps.forget("meals")["restored"] and (h / "config.yaml").read_text(encoding="utf-8") == BASE


def test_rule_chosen_strict_twin_also_moves(home):
    h = prof(home, "ops-twin", soul="ssh to the server")
    (h / ps.BACKUP_NAME).write_text(BASE, encoding="utf-8")
    ps.write_config(h, ps.want(ps.load_config(h), "strict"))
    ps.record("ops-twin", preset="strict", chosen_by="rule", before_written=True, had_config=True)
    got = ps.migrate_to_parity(["ops-twin"])
    assert got[0]["from"] == "strict" and "shell" in got[0]["turned_on"]
    c = ps.load_config(h)
    assert c["toolsets"] == ["terminal", "web", "memory"] and "vision" not in c["agent"]["disabled_toolsets"]
    assert ps.check("ops-twin")["ok"]

