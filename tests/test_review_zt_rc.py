"""The zero-touch RC review's findings (H1-H3, M1-M7, L1-L6, privacy): one test per fix, each failing without it.
No network, no Grok app, no Telegram: every outside call is a fake. Invented bots and twins only."""
from __future__ import annotations

import json
import re
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from twin_testlib import home, svc  # noqa: F401
from test_from_hermes_export import ACME, ask_answer, export, fenced, play, run, stub, world  # noqa: F401
from test_service_engine_deltas import rig  # noqa: F401
from hermes_plugins.grok_bot_twin.twin import (auto_setup, bot_export as BE, chat_sync, engine as E, from_hermes,
                                               grok_engine as ge, hermes_make, one_prompt, profile_safety as ps,
                                               store, tg_route)
from hermes_plugins.grok_bot_twin.twin.connect import BadInput

ROOT = Path(__file__).resolve().parents[1]
OWNER = "100200300"
TOKEN = "123456:" + "B" * 30
BASE = """model:
  provider: custom
  base_url: http://127.0.0.1:8000/v1
  default: local-model
toolsets: [terminal, web, memory]
mcp_servers:
  kb: {url: http://127.0.0.1:1/mcp}
approvals:
  mode: 'off'
"""


def _prof(name: str, config: str = BASE, soul: str = "Plan weekly meals.") -> Path:
    h = store.profile_home(name)
    h.mkdir(parents=True, exist_ok=True)
    (h / "config.yaml").write_text(config, encoding="utf-8")
    (h / "SOUL.md").write_text(soul, encoding="utf-8")
    return h


class Eng:
    """A fake Grok engine for the chat-sync tick: counts windows; reads fail (exit 1)."""

    def __init__(self):
        self.windows = 0
        self.reads = 0

    def window(self, ttl, idle):
        self.windows += 1
        return ge.Result(ge.DONE, {"reused": True})

    def read(self, bot_id, cursor, *a):
        self.reads += 1
        return ge.Result(ge.OTHER, {}, "FAIL: no such bot")

    def restore(self):
        return ge.Result(ge.DONE, {})


# ---- H1 ------------------------------------------------------------------------------------------------------
def test_h1_remove_drops_chat_sync_enrolment_and_telegram_route(rig):
    svc = rig.svc
    pid = svc.create(["b-acme-0001"])["pairs"][0]["pair_id"]
    prof = svc._registry()[pid]["hermes"]["profile"]
    chat_sync.enrol(pid, "pull", "b-acme-0001")
    tg_route._save({"gateway": "default", "owner_ids": [OWNER], "twins": {prof: True}, "current": {"k": prof}})
    svc.remove(pid, False)
    assert pid not in chat_sync.status()["twins"]
    assert prof not in (tg_route.state().get("twins") or {}) and not tg_route.state()["current"]


def test_h1_pull_tick_drops_unknown_twins_before_opening_a_window(svc, monkeypatch):
    chat_sync.enrol("gone-twin", "pull", "b-gone")
    monkeypatch.setattr(svc, "_registry", lambda: {})
    eng = Eng()
    monkeypatch.setattr(ge, "from_service", lambda s: eng)
    assert chat_sync.pull_tick(svc) == 0 and eng.windows == 0


def test_h1_a_failed_pull_waits_a_full_interval(svc, monkeypatch):
    reg = {"meals": {"pair_id": "meals", "grok": {"id": "b-meals", "name": "Meal Planner"},
                     "hermes": {"profile": "meals"}}}
    monkeypatch.setattr(svc, "_registry", lambda: reg)
    chat_sync.enrol("meals", "pull", "b-meals")
    eng = Eng()
    monkeypatch.setattr(ge, "from_service", lambda s: eng)
    import time
    now = time.time()
    assert chat_sync.pull_tick(svc, now) == 1 and eng.reads == 1
    assert chat_sync.status()["twins"]["meals"]["last"]["failed"] is True
    assert chat_sync.pull_tick(svc, now + 120) == 0 and eng.windows == 1  # no second window within minutes()


# ---- H2 ------------------------------------------------------------------------------------------------------
NEEDS = "needs botport 0.3.0 or newer (the Grok engine); the botport_release_tag setting chooses 0.2.1"


def test_h2_the_pin_has_the_engine_and_only_an_older_chosen_release_fails(svc, monkeypatch):
    assert E.EXPECTED_BOTPORT_TAG.startswith("v0.3.") and E.engine_pinned() and E.engine_pinned("v0.3.0")
    assert not E.engine_pinned("v0.2.1") and E.engine_needed_line("v0.2.1") == NEEDS
    monkeypatch.setattr(E, "configured_tag", lambda: "v0.2.1")  # (the owner chose an older release)
    assert auto_setup.run(object(), say=lambda s: None) == (1, f"FAIL: hermes twin setup --auto: {NEEDS}")

    def gone(s):
        raise ge.Unavailable("this botport has no Grok engine yet (botport grok)")
    monkeypatch.setattr(ge, "from_service", gone)
    ran = []
    res = from_hermes.run(svc, ["Acme Support"], setup_first=lambda s: ran.append(1) or (0, "PASS"))
    assert not res["ok"] and NEEDS in res["line"] and ran == []
    for doc in ("AGENTS.md", "docs/BOTPORT.md", "README.md"):
        assert "pins 0.2.1" not in " ".join((ROOT / doc).read_text(encoding="utf-8").split()), doc


def test_h2_pin_bump_is_one_step_and_done(tmp_path):
    sys.path.insert(0, str(ROOT / "tools"))
    try:
        import pin_botport
    finally:
        sys.path.remove(str(ROOT / "tools"))
    text = (ROOT / "twin" / "engine.py").read_text(encoding="utf-8")
    assert "TODO(botport" not in text and "tools/pin_botport.py --tag" in text
    bumped = pin_botport.set_expected_tag(text, "v0.3.1")
    assert 'EXPECTED_BOTPORT_TAG = "v0.3.1"' in bumped and bumped.count("EXPECTED_BOTPORT_TAG = ") == 1
    pins = json.loads((ROOT / "twin" / "botport_pins.json").read_text(encoding="utf-8"))
    assert E.EXPECTED_BOTPORT_TAG in json.dumps(pins)


# ---- H3 ------------------------------------------------------------------------------------------------------
def test_h3_docs_and_help_match_the_code():
    from hermes_plugins.grok_bot_twin.twin import cli, config
    log = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    unreleased = " ".join(log.split("## 0.5.0 (", 1)[1].split("\n## ", 1)[0].split())
    assert config.DEFAULTS["chat_sync_minutes"] == chat_sync.DEFAULT_MINUTES == 360
    assert "default 360" in unreleased and "default 60" not in unreleased
    assert "none of the twins" not in unreleased and "goes into each of those twins" in unreleased
    assert "waits for its PASS" not in unreleased and "Without the engine, nothing changes" not in unreleased
    one = " ".join((ROOT / "docs" / "ONE-PROMPT.md").read_text(encoding="utf-8").split())
    assert "stays out of every twin" not in one and "goes into each of those twins" in one
    assert "--wait after you answered" not in cli.HELP_TEXT and "exports itself" in " ".join(cli.HELP_TEXT.split())


# ---- M1 ------------------------------------------------------------------------------------------------------
def test_m1_add_fails_closed_when_safe_defaults_cannot_be_applied(rig, monkeypatch):
    svc = rig.svc

    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(ps, "apply_default", boom)
    res = svc.create(["b-acme-0001"])
    pid = res["pairs"][0]["pair_id"]
    prof = svc._registry()[pid]["hermes"]["profile"]
    assert res["notes"][0].startswith("FAIL: safe profile defaults not applied") and ps.is_unsafe(prof)
    with pytest.raises(BadInput, match="safe profile defaults were not applied"):
        svc.approve(pid, "routine:morning")
    (store.hermes_root() / ".env").write_text(f"TELEGRAM_BOT_TOKEN={TOKEN}\nTELEGRAM_ALLOWED_USERS={OWNER}\n", encoding="utf-8")
    assert "safe profile defaults were not applied" in tg_route.turn_on([prof])


# ---- M2 ------------------------------------------------------------------------------------------------------
def test_m2_stop_restores_after_an_owner_preset_and_keeps_a_named_backup_otherwise(home):
    h = _prof("meals")
    ps.apply_default("meals")
    ps.set_preset("meals", "standard", allow=["web"])  # the owner's own command: still put back on stop
    got = ps.forget("meals")
    assert got["restored"] and (h / "config.yaml").read_text(encoding="utf-8") == BASE and not (h / ps.BACKUP_NAME).exists()
    ps.apply_default("meals")
    (h / "config.yaml").write_text(BASE + "display: {}\n", encoding="utf-8")  # the owner edited it since: left alone
    got = ps.forget("meals")
    assert not got["restored"] and got["backup"] == str(h / ps.BACKUP_NAME) and (h / ps.BACKUP_NAME).is_file()
    assert "meals" not in ps.records()


def test_m2_record_stays_when_the_restore_fails_and_keep_data_stop_restores(rig, monkeypatch):
    h = _prof("meals")
    ps.apply_default("meals")
    real = store.atomic_write_text
    monkeypatch.setattr(store, "atomic_write_text", lambda *a, **k: (_ for _ in ()).throw(OSError("ro")))
    with pytest.raises(OSError):
        ps.forget("meals")
    assert "meals" in ps.records() and (h / ps.BACKUP_NAME).is_file()
    monkeypatch.setattr(store, "atomic_write_text", real)
    svc = rig.svc
    pid = svc.create(["b-acme-0001"])["pairs"][0]["pair_id"]
    prof = svc._registry()[pid]["hermes"]["profile"]
    assert prof in ps.records()
    out = svc.remove(pid, False, keep_data=True)
    assert prof not in ps.records() and any(x.startswith("Its Hermes bot's config.yaml") for x in out["stays"])


# ---- M3 ------------------------------------------------------------------------------------------------------
def test_m3_standard_drops_web_file_and_mcp_until_the_owner_widens(home):
    h = _prof("meals")
    assert ps.apply_default("meals")["preset"] == "parity"  # (twin#71: standard is the owner's choice now)
    ps.set_preset("meals", "standard")
    c = ps.load_config(h)
    assert c["toolsets"] == ["memory"] and c["mcp_servers"] == {}
    assert {"web", "x_search", "file", "image_gen"} <= set(c["agent"]["disabled_toolsets"])
    (h / "config.yaml").write_text(BASE, encoding="utf-8")
    assert "mcp_servers" in ps.check("meals")["problems"]
    ps.set_preset("meals", "standard", allow=["mcp"])
    assert ps.check("meals")["ok"] and "kb" in ps.load_config(h)["mcp_servers"]


# ---- M4 ------------------------------------------------------------------------------------------------------
def test_m4_a_messaging_chat_cannot_start_twinning_or_setup(svc, monkeypatch):
    from hermes_plugins.grok_bot_twin.twin import config, tasks
    monkeypatch.setattr(tasks, "asked_turn", lambda **kw: False)
    ran = []
    monkeypatch.setattr(from_hermes, "run", lambda *a, **k: ran.append(1) or {"ok": True, "line": "PASS", "bots": []})
    monkeypatch.setattr(hermes_make, "make", lambda *a: ran.append(2) or {"verdict": "PASS"})
    out = json.loads(from_hermes.twin_from_hermes({"bot_name": "Acme Support"}, platform="telegram"))
    assert not out["ok"] and "messaging chat" in out["line"]
    assert "messaging chat" in json.loads(hermes_make.twin_make({"bot_name": "Acme Support"},
                                                                platform="telegram"))["verdict"]
    monkeypatch.setenv("HERMES_SESSION_PLATFORM", "telegram")
    assert "messaging chat" in json.loads(from_hermes.twin_from_hermes({"bot_name": "Acme Support"}))["line"]
    assert ran == []
    config.set_override({"setup_from_messaging": True})
    assert json.loads(from_hermes.twin_from_hermes({"bot_name": "Acme Support"}, platform="telegram"))["ok"]


# ---- M5 ------------------------------------------------------------------------------------------------------
def test_m5_route_answers_only_on_the_gateway_profile(home, monkeypatch):
    store.hermes_root().mkdir(parents=True, exist_ok=True)
    (store.hermes_root() / ".env").write_text(f"TELEGRAM_BOT_TOKEN={TOKEN}\nTELEGRAM_ALLOWED_USERS={OWNER}\n", encoding="utf-8")
    assert tg_route.turn_on(["acme-support"]).startswith("PASS")
    monkeypatch.setattr(tg_route, "_turn", lambda p, t: {"ok": True, "reply": "hi"})
    dm = dict(user_id=OWNER, chat_type="dm", chat_id="42")
    assert tg_route.handle("to acme-support x", "telegram", SimpleNamespace(**dm, profile=None)) == "[acme-support] hi"
    assert tg_route.handling_profile(SimpleNamespace(**dm, profile="work")) == "work"
    assert "only on the Telegram bot it was turned on for" in tg_route.handle(
        "to acme-support x", "telegram", SimpleNamespace(**dm, profile="work"))
    from hermes_plugins.grok_bot_twin.twin import config  # (this process is profile work's own Hermes)
    monkeypatch.setattr(config, "_own_home", lambda: str(store.hermes_root() / "profiles" / "work"))
    assert tg_route.handling_profile(SimpleNamespace(**dm)) == "work"
    assert tg_route.handle("to acme-support x", "telegram", SimpleNamespace(**dm)) != "[acme-support] hi"


# ---- M6 ------------------------------------------------------------------------------------------------------
def test_m6_reach_refuses_a_twin_profile_and_a_real_folder_copy(home, tmp_path):
    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir()
    _prof("meals")
    with pytest.raises(auto_setup.Stop, match="twin's own Hermes bot"):
        auto_setup.reach("meals", run=lambda a, t: (0, b"", b""), hermes="/x/hermes", plugin_dir=plugin_dir,
                         twins=("meals",))
    h = _prof("work", "model: x\nplugins:\n  enabled: [grok-bot-twin]\n")
    (h / "plugins" / "grok-bot-twin").mkdir(parents=True)  # an older copy, not a link to this one
    with pytest.raises(auto_setup.Stop, match="another copy"):
        auto_setup.reach("work", run=lambda a, t: (0, b"", b""), hermes="/x/hermes", plugin_dir=plugin_dir)


# ---- M7 ------------------------------------------------------------------------------------------------------
def test_m7_a_tick_never_runs_while_from_hermes_holds_the_engine(svc, monkeypatch):
    reg = {"meals": {"pair_id": "meals", "grok": {"id": "b-meals", "name": "Meal Planner"},
                     "hermes": {"profile": "meals"}}}
    monkeypatch.setattr(svc, "_registry", lambda: reg)
    chat_sync.enrol("meals", "pull", "b-meals")
    eng = Eng()
    monkeypatch.setattr(ge, "from_service", lambda s: eng)
    held, done = threading.Event(), threading.Event()

    def export_running():
        with one_prompt.engine_lock():
            held.set()
            done.wait(10)
    t = threading.Thread(target=export_running)
    t.start()
    try:
        assert held.wait(10)
        assert chat_sync.pull_tick(svc) == 0 and eng.windows == 0
    finally:
        done.set()
        t.join()
    assert chat_sync.pull_tick(svc) == 1 and eng.windows == 1


# ---- L1-L6 ---------------------------------------------------------------------------------------------------
def test_l1_policy_is_looked_for_where_the_engine_botport_keeps_it(tmp_path, monkeypatch):
    other = tmp_path / "elsewhere"
    other.mkdir()
    (other / "grok-policy.toml").write_text("preset = 'strict'\n", encoding="utf-8")
    monkeypatch.setenv("BOTPORT_HOME", str(other))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert auto_setup.policy_saved() is False
    (tmp_path / ".botport").mkdir()
    (tmp_path / ".botport" / "grok-policy.toml").write_text("preset = 'strict'\n", encoding="utf-8")
    assert auto_setup.policy_saved() is True


def test_l2_a_refused_export_file_is_still_cleaned_up(svc, world, stub):
    fetched = {"rc": 0, "stdout": {}, "write": {"name": BE.EXPORT_FILE, "content": json.dumps(export()),
                                                "sha256": "0" * 64}}
    play(stub, [ask_answer("file", file={"name": BE.EXPORT_FILE, "path": "/x"}), ask_answer("DONE", key="t10s1")],
         files=[fetched])
    res = run(svc, stub)
    assert not res["ok"] and "refused" in res["line"]
    asks = [a for a in stub.calls() if a[1] == "ask"]
    assert len(asks) == 2 and asks[1][3] == BE.CLEANUP


def test_l3_another_bots_skill_cannot_block_the_bots_own_of_the_same_name():
    theirs = {"name": "widget-faq", "description": "x", "body": "someone else's", "mine": False}
    own = {"name": "widget-faq", "description": "Widget FAQ", "body": "# Widget FAQ", "mine": True}
    clean = BE.validate(export(skills=[theirs, own]), "Acme Support")
    assert [(s["name"], s["mine"]) for s in clean["skills"]] == [("widget-faq", True)]
    assert clean["skipped"] == ["widget-faq"]


def test_l4_the_tool_counts_other_bots_skills_instead_of_naming_them(svc, world, stub):
    play(stub, ask_answer(fenced(export())))
    res = run(svc, stub)
    assert res["ok"] and "team-notes" in res["line"]
    shown = from_hermes.for_model(res)
    assert "team-notes" not in json.dumps(shown), json.dumps(shown)[:3000]
    assert "not imported: 1" in shown["line"]


def test_l5_only_the_newest_dated_config_copies_are_kept(home):
    h = _prof("meals")
    for i in range(8):
        (h / f"config.yaml.pre-safety-20000101-00000{i}").write_text("old", encoding="utf-8")
    ps.write_config(h, {"model": "x"})
    left = sorted(p.name for p in h.glob("config.yaml.pre-safety-*"))
    assert len(left) == ps.BACKUPS_KEPT and "config.yaml.pre-safety-20000101-000007" in left


def test_l6_the_pass_line_says_when_a_live_case_passed_on_a_retry():
    res = {"ok": True, "counts": {}, "profile": "meals", "created": True,
           "test": {"passed": 5, "total": 5, "retried": 1}}
    assert "1 case(s) passed only on a retry" in one_prompt._line("Meal Planner", res)


# ---- privacy -------------------------------------------------------------------------------------------------
def test_privacy_no_private_references_or_real_twin_names():
    texts = {p: p.read_text(encoding="utf-8") for d in ("twin", "tests") for p in (ROOT / d).glob("*.py")
             if p.name != Path(__file__).name}
    for p, text in texts.items():
        for bad in ("ROUTINE-TRUTH", "lane B", "REAL-TWINS-PLAN", "twin-live41", "live 16 Nov"):
            assert bad not in text, (p.name, bad)
    assert not re.search(r"/twin (to|use) ea\b", texts[ROOT / "twin" / "tg_route.py"])
    assert '["ea"]' not in texts[ROOT / "tests" / "test_zero_touch.py"]
