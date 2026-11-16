"""twin#76: (1) a model server's key carried to a twin by reference, never by value; (2) a session with no screen
gets a headless browser, whose screenshots work; (3) the /twin use route asks the owner in the DM for each approval.
Invented names and values only; the OS secret store is a mocked one, the Telegram chat a fake asker."""
from __future__ import annotations

import sys
import time
from types import SimpleNamespace

import pytest

from twin_testlib import central, config, home, service  # noqa: F401
from test_ux_flows import _client, _pair, fake  # noqa: F401
from test_setup_download_and_twin_facts import SOUL, profile, twin  # noqa: F401
from test_batch import world, TWINS, P  # noqa: F401
from test_secret_ref import MemStore
from hermes_plugins.grok_bot_twin.twin import endpoints, gui, model_key, one_prompt, profile_safety, secret_ref
from hermes_plugins.grok_bot_twin.twin import tg_route, yamlio

VALUE = "sk-" + "Hq3Wv" * 6  # invented, key-shaped
OWNER = "1234567"


# ---- 1. the key, by reference ------------------------------------------------------------------------------------
def _cfg(entry: str) -> str:
    return f"model:\n  default: grok-4.7\n  provider: openrouter\ncustom_providers:\n- name: Homebox\n" \
           f"  base_url: http://127.0.0.1:8000/v1\n  model: local-model\n{entry}"


@pytest.fixture
def mem(monkeypatch):
    s = MemStore()
    monkeypatch.setattr(secret_ref, "_override", [s])
    return s


@pytest.fixture
def server(home, monkeypatch):
    monkeypatch.setattr(endpoints, "PROBE", lambda url: ["local-model"] if "127.0.0.1" in url else None)
    endpoints._cache.clear()

    def setup(entry: str, env: str = "") -> None:
        (home / "config.yaml").write_text(_cfg(entry), encoding="utf-8")
        if env:
            (home / ".env").write_text(env, encoding="utf-8")
    return setup


def _twin_files(home, pid):
    d = home / "profiles" / pid
    doc = yamlio.module().safe_load((d / "config.yaml").read_text(encoding="utf-8"))
    env = (d / ".env").read_text(encoding="utf-8") if (d / ".env").exists() else ""
    return doc, env, (d / "config.yaml").read_text(encoding="utf-8")


def test_key_from_the_source_profile_by_reference(world, home, server, mem):
    server("  key_env: HOMEBOX_KEY\n", env=f"OTHER=1\nHOMEBOX_KEY={VALUE}\n")
    pid = TWINS[0][0]
    res = world.set_model(pid, "local-model", endpoint="Homebox")
    assert res["state"] == "set" and res["key"] == {"name": "HOMEBOX_KEY", "from": "source profile"}
    doc, env, raw = _twin_files(home, pid)
    assert doc["model"]["api_key"] == "${HOMEBOX_KEY}" and VALUE not in raw  # the reference, never the value
    assert f"HOMEBOX_KEY={VALUE}" in env and "OTHER" not in env  # only that one key, in the twin's own .env
    assert mem.data == {"HOMEBOX_KEY": VALUE} and VALUE not in str(res)
    line = model_key.note(res["key"])
    assert line == "; model key kept by reference (HOMEBOX_KEY, from the source profile)" and VALUE not in line


def test_literal_key_in_the_model_setup_is_moved_into_the_store(world, home, server, mem):
    server(f"  api_key: {VALUE}\n")
    pid = TWINS[0][0]
    res = world.set_model(pid, "local-model", endpoint="Homebox")
    assert res["key"] == {"name": "HOMEBOX_API_KEY", "from": "model setup"}
    doc, env, raw = _twin_files(home, pid)
    assert doc["model"]["api_key"] == "${HOMEBOX_API_KEY}" and VALUE not in raw
    assert mem.data == {"HOMEBOX_API_KEY": VALUE}


def test_env_reference_in_setup_and_value_already_in_the_store(world, home, server, mem):
    server("  api_key: ${env:HOMEBOX_KEY}\n")
    mem.data["HOMEBOX_KEY"] = VALUE
    pid = TWINS[0][0]
    res = world.set_model(pid, "local-model", endpoint="Homebox")
    assert res["key"] == {"name": "HOMEBOX_KEY", "from": "secret store"}
    assert _twin_files(home, pid)[0]["model"]["api_key"] == "${HOMEBOX_KEY}"


def test_no_store_still_gets_the_key_to_the_twin_by_reference(world, home, server):  # conftest: no OS store
    """Rehearsal 17 Nov / round 4: with no OS store (the Keychain locked over SSH) the key was not kept and needed a
    hand edit. The value is already in the source profile's own .env: it goes straight to the twin's own .env."""
    server("  key_env: HOMEBOX_KEY\n", env=f"HOMEBOX_KEY={VALUE}\nOTHER=1\n")
    pid = TWINS[0][0]
    res = world.set_model(pid, "local-model", endpoint="Homebox")
    assert res["key"] == {"name": "HOMEBOX_KEY", "from": "source profile", "store": "locked"}
    doc, env, raw = _twin_files(home, pid)
    assert doc["model"]["api_key"] == "${HOMEBOX_KEY}" and VALUE not in raw
    assert f"HOMEBOX_KEY={VALUE}" in env and "OTHER" not in env
    assert oct((home / "profiles" / pid / ".env").stat().st_mode & 0o777) == "0o600" or sys.platform == "win32"
    line = model_key.note(res["key"])
    assert line.startswith("; model key kept by reference (HOMEBOX_KEY, from the source profile;") and VALUE not in line
    assert "locked" in line and VALUE not in str(res)


class LockedStore(MemStore):
    """A Keychain that is there but refuses to keep anything (locked, an SSH session)."""

    def put(self, name, value):
        raise secret_ref.NoStore("the Keychain refused to keep it (is it locked?)")


def test_locked_store_still_gets_the_key_to_the_twin(world, home, server, monkeypatch, caplog):
    monkeypatch.setattr(secret_ref, "_override", [LockedStore()])
    server(f"  api_key: {VALUE}\n")  # a literal key in the model setup
    pid = TWINS[0][0]
    with caplog.at_level("DEBUG"):
        res = world.set_model(pid, "local-model", endpoint="Homebox")
    assert res["key"] == {"name": "HOMEBOX_API_KEY", "from": "model setup", "store": "locked"}
    doc, env, raw = _twin_files(home, pid)
    assert doc["model"]["api_key"] == "${HOMEBOX_API_KEY}" and VALUE not in raw and f"HOMEBOX_API_KEY={VALUE}" in env
    assert VALUE not in caplog.text and VALUE not in str(res)


def test_no_value_anywhere_keeps_nothing_and_says_why(world, home, server):  # conftest: no OS store
    server("  key_env: HOMEBOX_KEY\n", env="OTHER=1\n")
    pid = TWINS[0][0]
    res = world.set_model(pid, "local-model", endpoint="Homebox")
    assert res["key"]["name"] == "HOMEBOX_KEY" and "no value" in res["key"]["not_kept"]
    doc, env, raw = _twin_files(home, pid)
    assert "api_key" not in doc["model"] and "HOMEBOX_KEY" not in env
    assert model_key.note(res["key"]).startswith("; model key HOMEBOX_KEY not kept (")


def test_one_prompt_pass_line_says_the_key_went_by_reference_with_the_store_locked():
    res = {"ok": True, "counts": {}, "test": {"passed": 1, "total": 1}, "profile": "acme-support", "created": True,
           "model_key": {"name": "HOMEBOX_KEY", "from": "source profile", "store": "locked"}}
    line = one_prompt._line("Acme Support", res)
    assert line.startswith("PASS") and "model key kept by reference (HOMEBOX_KEY, from the source profile;" in line
    assert "twin's own private .env" in line


def test_a_server_without_a_key_gets_none(world, home, server, mem):
    server("")
    res = world.set_model(TWINS[0][0], "local-model", endpoint="Homebox")
    assert "key" not in res and mem.data == {}


def test_one_prompt_pass_line_names_the_key():
    res = {"ok": True, "counts": {}, "test": {"passed": 1, "total": 1}, "profile": "acme-support", "created": True,
           "model_key": {"name": "HOMEBOX_KEY", "from": "model setup"}}
    line = one_prompt._line("Acme Support", res)
    assert line.startswith("PASS") and "model key kept by reference (HOMEBOX_KEY, from the model setup)" in line


# ---- 2. no screen: headless --------------------------------------------------------------------------------------
SSH = {"SSH_CONNECTION": "a b c d", "HOME": "/x"}


def test_has_gui_by_platform():
    assert gui.has_gui({}, "darwin", probe=lambda: "Aqua")
    assert not gui.has_gui(SSH, "darwin", probe=lambda: "Background")
    assert gui.has_gui(SSH, "darwin", probe=lambda: "Aqua")  # ssh into a logged-in window session
    assert not gui.has_gui({}, "linux") and gui.has_gui({"DISPLAY": ":0"}, "linux")
    assert gui.has_gui({"WAYLAND_DISPLAY": "wayland-0"}, "linux")
    assert gui.has_gui({}, "win32") and not gui.has_gui({"SSH_CLIENT": "x"}, "win32")


def test_fit_browser_only_without_a_screen():
    c = {"browser": {"headed": True}}
    assert gui.fit_browser(c, {}, "darwin", probe=lambda: "Aqua") == "" and c["browser"]["headed"] is True
    assert gui.fit_browser(c, SSH, "darwin", probe=lambda: "Background") == gui.NOTE
    assert c["browser"]["headed"] is False
    assert gui.fit_browser({"browser": {"headed": False}}, SSH, "darwin", probe=lambda: "x") == ""
    assert gui.fit_browser({}, SSH, "darwin", probe=lambda: "x") == ""


def test_apply_default_makes_the_browser_headless_over_ssh(home, monkeypatch):
    prof = home / "profiles" / "acme-support"
    prof.mkdir(parents=True)
    (prof / "config.yaml").write_text("browser:\n  headed: true\n", encoding="utf-8")
    monkeypatch.setattr(gui, "has_gui", lambda *a, **k: False)
    got = profile_safety.apply_default("acme-support", prof)
    assert got["headless"] == gui.NOTE
    assert profile_safety.load_config(prof)["browser"]["headed"] is False
    monkeypatch.setattr(gui, "has_gui", lambda *a, **k: True)
    (prof / "config.yaml").write_text("browser:\n  headed: true\n", encoding="utf-8")
    assert profile_safety.apply_default("acme-support", prof)["headless"] == ""
    assert profile_safety.load_config(prof)["browser"]["headed"] is True


# ---- 3. /twin use: approvals asked in the owner's DM -------------------------------------------------------------
def _route(home):
    (home / ".env").write_text(f"TELEGRAM_BOT_TOKEN=123:AAAAinvented\nTELEGRAM_ALLOWED_USERS={OWNER}\n",
                               encoding="utf-8")
    (home / "config.yaml").write_text("model: x\n", encoding="utf-8")
    tg_route.turn_on(["acme-support"])


def _fake_turn(monkeypatch, seen: dict):
    """A Hermes turn with one step that waits for approval, answered through on_wait/answer as tasks_turn does."""
    from hermes_plugins.grok_bot_twin.twin import tasks_turn

    def fake(profile, text, should_stop, on_wait, answer, limit_s=None):
        on_wait({"command": "rm -r ./build", "description": "delete the build folder"})
        end = time.monotonic() + 5
        choice = None
        while choice is None and time.monotonic() < end:
            choice = answer()
            time.sleep(0.01)
        on_wait(None)
        seen["choice"] = choice
        return {"ok": True, "reply": "ran it" if choice == "once" else "not approved",
                "not_approved": None if choice == "once" else "approval_denied"}
    monkeypatch.setattr(tasks_turn, "run_turn", fake)


def _src(chat_id="42"):
    return SimpleNamespace(user_id=OWNER, chat_type="dm", chat_id=chat_id)


@pytest.mark.parametrize("picked,choice,reply", [("once", "once", "ran it"), ("deny", "deny", "not approved"),
                                                 (None, "deny", "not approved")])
def test_use_route_asks_the_owner_in_the_dm(home, monkeypatch, picked, choice, reply):
    _route(home)
    asked = []

    def ask(question, choices):
        asked.append((question, [c["value"] for c in choices]))
        return picked
    monkeypatch.setattr(tg_route, "owner_asker", lambda: ask)
    seen: dict = {}
    _fake_turn(monkeypatch, seen)
    assert tg_route.handle("use acme-support", "telegram", _src()).startswith("This chat now talks to")
    assert tg_route.handle("say tidy the build", "telegram", _src()) == f"[acme-support] {reply}"
    assert seen["choice"] == choice
    assert len(asked) == 1 and asked[0][1] == ["once", "deny"]
    assert "rm -r ./build" in asked[0][0] and "needs your approval" in asked[0][0]


def test_approval_text_is_redacted(monkeypatch):
    from hermes_plugins.grok_bot_twin.twin import model_check
    monkeypatch.setattr(model_check, "redact", lambda s: s.replace("hostx", "[host]"))
    t = tg_route.approval_text("acme-support", {"command": "curl http://hostx:1/", "description": ""})
    assert "hostx" not in t and "[host]" in t


def test_no_asker_still_denies(home, monkeypatch):
    seen: dict = {}
    _fake_turn(monkeypatch, seen)
    assert tg_route._run_turn("acme-support", "x")["reply"] == "not approved" and seen["choice"] == "deny"


def test_owner_asker_is_none_outside_hermes(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "hermes_cli.plugin_choices", None)  # no Hermes: the route falls back to deny
    assert tg_route.owner_asker() is None


def test_literal_key_never_overwrites_a_different_key_of_the_same_name(world, home, server, mem):
    server(f"  api_key: {VALUE}\n")
    mem.data["HOMEBOX_API_KEY"] = "another-key-entirely"
    pid = TWINS[0][0]
    res = world.set_model(pid, "local-model", endpoint="Homebox")
    assert res["key"]["name"] == "HOMEBOX_API_KEY" and "different key" in res["key"]["not_kept"]
    assert mem.data == {"HOMEBOX_API_KEY": "another-key-entirely"} and VALUE not in str(res)


def test_set_preset_says_the_browser_went_headless_and_how_to_undo_it(home, monkeypatch):
    # review rc052 #10: set_preset computed the note and dropped it; the note names the way back
    prof = home / "profiles" / "acme-support"
    prof.mkdir(parents=True)
    (prof / "config.yaml").write_text("browser:\n  headed: true\n", encoding="utf-8")
    monkeypatch.setattr(gui, "has_gui", lambda *a, **k: False)
    got = profile_safety.set_preset("acme-support", "standard", home=prof)
    assert got["headless"] == gui.NOTE and "browser.headed: true" in gui.NOTE
    assert "headless" not in profile_safety.records()["acme-support"]
    monkeypatch.setattr(gui, "has_gui", lambda *a, **k: True)
    (prof / "config.yaml").write_text("browser:\n  headed: true\n", encoding="utf-8")
    assert profile_safety.set_preset("acme-support", "standard", home=prof)["headless"] == ""


def test_batch_models_names_a_key_that_was_not_kept(world, home, server):  # conftest: no OS store
    """Rehearsal 17 Nov: `finish` reads batch_models, which dropped set_model's key result, so a key that was not
    kept was never said. Each result now carries the key's name and why (never its value)."""
    server("  key_env: HOMEBOX_KEY\n", env="OTHER=1\n")  # (no value anywhere: a key with a value now goes by .env)
    got = world.batch_models([TWINS[0][0]], "local-model", "Homebox")["results"][0]
    assert got["state"] == "set" and got["key"]["name"] == "HOMEBOX_KEY" and got["key"]["not_kept"]
    assert VALUE not in str(got)
