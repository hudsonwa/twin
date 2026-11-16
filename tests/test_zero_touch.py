"""Zero-touch issues 07 (setup --auto), 09 (Telegram through the existing Hermes bot), 10 (safe twin defaults).
No network, no Grok app, no Telegram: every outside call is a fake."""
from __future__ import annotations

import hashlib
import io
import json
import os
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace

import pytest

from twin_testlib import cli, home, slash, svc  # noqa: F401
from hermes_plugins.grok_bot_twin.twin import auto_setup, grok_engine as ge, pins, profile_safety as ps, tg_route

OWNER = "100200300"
OTHER = "999888777"


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = cli.main(argv)
    return rc, out.getvalue(), err.getvalue()


def prof(home: Path, name: str, config: str = "", env: str = "", soul: str = "") -> Path:
    h = home if name == "default" else home / "profiles" / name
    h.mkdir(parents=True, exist_ok=True)
    if config:
        (h / "config.yaml").write_text(config, encoding="utf-8")
    if env:
        (h / ".env").write_text(env, encoding="utf-8")
    if soul:
        (h / "SOUL.md").write_text(soul, encoding="utf-8")
    return h


# ---- 10: safe defaults ---------------------------------------------------------------------------------------------
def test_rule_picks_strict_for_risky_words():
    assert ps.choose(["I watch the futures book and place orders with the broker"])[0] == "strict"
    assert ps.choose(["You may ssh into the build server"])[1][:2] == ["ssh", "server"]
    assert ps.choose(["Plan weekly meals and a shopping list"]) == ("standard", [])
    assert ps.choose(["The shellfish recipe"]) == ("standard", [])  # whole words only


BASE = """model:
  provider: custom
  base_url: http://127.0.0.1:8000/v1
  default: local-model
toolsets: [terminal, web, memory]
platform_toolsets:
  cli: [terminal, file, web, memory]
mcp_servers:
  kb: {url: http://127.0.0.1:1/mcp}
  other: {url: http://127.0.0.1:2/mcp}
approvals:
  mode: 'off'
"""


def test_strict_lockdown_applied_by_rule_and_checked(home):
    h = prof(home, "ops-twin", BASE, soul="Runs shell commands on the deploy server.")
    assert ps.apply_default("ops-twin")["words"][:1] == ["shell"]  # (twin#71: the rule gives parity, names words)
    got = {**ps.set_preset("ops-twin", "strict"), "chosen_by": "owner"}
    assert got["preset"] == "strict"
    c = ps.load_config(h)
    assert c["toolsets"] == ps.STRICT_ALLOWED and c["approvals"]["mode"] == "manual"
    assert c["mcp_servers"] == {} and c["platforms"]["telegram"]["enabled"] is False
    assert c["model"]["default"] == "local-model"  # other keys kept
    assert ps.problems(c, "strict") == []
    if os.name != "nt":  # (Windows has no permission bits; the profile folder is the owner's own)
        assert (os.stat(h / "config.yaml").st_mode & 0o777) == 0o600
    assert any(p.name.startswith("config.yaml.pre-safety-") for p in h.iterdir())
    res = ps.check("ops-twin")
    assert res["ok"] and ps.line("ops-twin", res).startswith("PASS: twin ops-twin safety strict (owner)")
    # idempotent, and the owner's choice holds
    assert ps.apply_default("ops-twin")["preset"] == "strict"


def test_strict_keeps_named_mcp(home):
    from twin_testlib import config
    config.set_override({"botport_path": "/nope", "twin_safe_mcp": ["kb"]})
    prof(home, "ops", BASE, soul="ssh")
    ps.set_preset("ops", "strict")
    assert list(ps.load_config(home / "profiles" / "ops")["mcp_servers"]) == ["kb"]


def test_standard_for_benign_bot_and_one_command_widen(home):
    h = prof(home, "meals", BASE, soul="Plan weekly meals.")
    assert ps.apply_default("meals")["preset"] == "parity"  # (twin#71: standard is the owner's choice now)
    ps.set_preset("meals", "standard")
    c = ps.load_config(h)
    # standard keeps no shell or socket, and by default no web, file or MCP server either (M3)
    assert c["toolsets"] == ["memory"] and c["platform_toolsets"]["cli"] == ["memory"] and not c["mcp_servers"]
    assert set(ps.STANDARD_DENIED) <= set(c["agent"]["disabled_toolsets"])
    assert ps.check("meals")["ok"]
    ps.set_preset("meals", "standard", allow=["web", "mcp"])  # the owner widens one toolset at a time
    assert ps.check("meals")["ok"] and "web" not in ps.load_config(h)["agent"]["disabled_toolsets"]
    assert "file" in ps.load_config(h)["agent"]["disabled_toolsets"]
    rc_rec = ps.set_preset("meals", "open")
    assert rc_rec["chosen_by"] == "owner"
    # the owner's choice holds: the rule does not take it back
    assert ps.apply_default("meals")["preset"] == "open" and ps.check("meals")["ok"]


def test_cloud_model_fails_closed_until_policy(home):
    prof(home, "cloud", "model:\n  provider: xai\n  default: grok\n", soul="notes")
    ps.apply_default("cloud")
    res = ps.check("cloud")
    assert not res["ok"] and res["model"] == "cloud" and "model policy" in ps.line("cloud", res)
    ps.set_model_policy("cloud", "any")
    assert ps.check("cloud")["ok"]


def test_safety_cli_on_a_twin(svc, monkeypatch):
    from hermes_plugins.grok_bot_twin.twin import zt_cli
    home = Path(os.environ["HERMES_HOME"])
    prof(home, "trader", BASE, soul="trading desk helper")
    monkeypatch.setattr(zt_cli, "resolve_profile", lambda s, n: n)
    rc, out, _ = run(["safety", "trader", "--apply"])
    assert rc == 0 and "trader: parity; its text mentions: trading" in out
    assert "safety parity (rule), model local; capabilities: browser ✓" in out
    rc, out, _ = run(["safety", "trader", "standard"])
    assert rc == 0 and "safety standard (owner)" in out


# ---- 07: setup --auto ----------------------------------------------------------------------------------------------
def test_fetch_pinned_checks_sha_before_use(home):
    blob = b"pretend release archive"
    good = hashlib.sha256(blob).hexdigest()
    target = "aarch64-apple-darwin"
    pins.set_table({"releases": {"v9.9.9": {"archives": {pins.asset_name(target): good},
                                            "programs": {target: "0" * 64}}}})
    try:
        seen = []
        path = auto_setup.fetch_pinned("v9.9.9", target, fetch=lambda url, cap: seen.append(url) or blob)
        assert seen == ["https://github.com/hudsonwa/botport/releases/download/v9.9.9/"
                        "botport-aarch64-apple-darwin.tar.gz"]
        assert path.read_bytes() == blob
        assert os.name == "nt" or (os.stat(path).st_mode & 0o777) == 0o600  # (no permission bits on Windows)
        with pytest.raises(auto_setup.Stop, match="does not match the pinned SHA-256"):
            auto_setup.fetch_pinned("v9.9.9", target, fetch=lambda url, cap: b"tampered")
        with pytest.raises(auto_setup.Stop, match="not pinned"):
            auto_setup.fetch_pinned("v9.9.8", target, fetch=lambda url, cap: blob)
    finally:
        pins.set_table(None)


def test_fetch_refuses_plain_http():
    with pytest.raises(auto_setup.Stop, match="https"):
        auto_setup._fetch("http://example.invalid/x", 10)


def test_reach_links_plugin_into_sticky_profile(home, tmp_path):
    (home / "active_profile").write_text("work\n", encoding="utf-8")
    h = prof(home, "work", "model: x\n")
    assert auto_setup.active_profile() == "work"
    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir()
    calls = []

    def runner(argv, timeout):
        calls.append(argv)
        (h / "config.yaml").write_text("model: x\nplugins:\n  enabled: [grok-bot-twin]\n", encoding="utf-8")
        return 0, b"", b""

    assert auto_setup.reach("work", run=runner, hermes="/x/hermes", plugin_dir=plugin_dir,
                              link_other=True) == "linked"
    assert os.path.realpath(h / "plugins" / "grok-bot-twin") == str(plugin_dir.resolve())
    assert calls == [["/x/hermes", "-p", "work", "plugins", "enable", "grok-bot-twin"]]
    assert auto_setup.reach("work", run=runner, hermes="/x/hermes", plugin_dir=plugin_dir,
                              link_other=True) == "had it"
    assert len(calls) == 1


@pytest.mark.skipif(os.name != "nt", reason="directory junctions are a Windows thing")
def test_reach_falls_back_to_a_junction_when_windows_refuses_a_symlink(home, tmp_path, monkeypatch):
    h = prof(home, "work", "model: x\n")
    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir()

    def no_symlink(*a, **k):
        raise OSError(1314, "A required privilege is not held by the client")

    monkeypatch.setattr(os, "symlink", no_symlink)

    def runner(argv, timeout):
        (h / "config.yaml").write_text("model: x\nplugins:\n  enabled: [grok-bot-twin]\n", encoding="utf-8")
        return 0, b"", b""

    assert auto_setup.reach("work", run=runner, hermes="hermes", plugin_dir=plugin_dir,
                              link_other=True) == "linked"
    link = h / "plugins" / "grok-bot-twin"
    assert auto_setup._is_link(link)
    assert os.path.realpath(link).lower() == str(plugin_dir.resolve()).lower()


def test_reach_leaves_a_sticky_owner_profile_alone_unless_asked(home, tmp_path):
    """Audit 2026-11-16: setup --auto linked and enabled the plugin in the owner's sticky profile (one of the
    owner's own bots), which gave that bot the twin toolset. Without --link-profile it is left exactly as it was."""
    h = prof(home, "work", "model: x\n")
    before = (h / "config.yaml").read_bytes()
    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir()
    calls = []
    assert auto_setup.reach("work", run=lambda a, t: calls.append(a) or (0, b"", b""), hermes="/x/hermes",
                            plugin_dir=plugin_dir) == "left alone"
    assert calls == []
    assert not (h / "plugins" / "grok-bot-twin").exists()
    assert (h / "config.yaml").read_bytes() == before


def test_reach_fails_when_enable_fails(home, tmp_path):
    prof(home, "work", "model: x\n")
    (tmp_path / "p").mkdir()
    with pytest.raises(auto_setup.Stop, match="plugins enable"):
        auto_setup.reach("work", run=lambda a, t: (1, b"", b"nope"), hermes="/x/hermes", plugin_dir=tmp_path / "p",
                         link_other=True)


def test_app_path_note(monkeypatch):
    monkeypatch.setattr(auto_setup, "_hermes", lambda: "/abs/hermes")
    monkeypatch.setattr(auto_setup, "app_path", lambda run=None: "/usr/bin:/bin")
    assert auto_setup.path_note(None) == ("Grok app PATH lacks hermes and botport; twin starts them by absolute "
                                          "path")


class FakeEngine:
    def __init__(self, port_open=False, preset="balanced", perm=("ask", "ask")):
        self.port_open, self.preset, self.perm, self.calls = port_open, preset, list(perm), []

    def status(self):
        p = self.perm.pop(0) if len(self.perm) > 1 else self.perm[0]
        return ge.Result(0, {"exit": 0, "proof": "PASS", "installed": True, "port_open": self.port_open,
                             "preset": self.preset, "local_tool_permission": p}, "PASS")

    def policy_show(self):
        return ge.Result(0, {"exit": 0, "proof": "PASS", "policy": {"preset": self.preset}}, "PASS")

    def policy_preset(self, p):
        self.calls.append(("preset", p))
        self.preset = p
        return ge.Result(0, {"exit": 0, "proof": "PASS"}, "PASS")

    def launch(self):
        self.calls.append(("launch",))
        self.port_open = True
        return ge.Result(0, {"exit": 0, "proof": "PASS"}, "PASS")


def test_engine_sets_fast_only_when_unset_and_never_launches_by_default():
    e = FakeEngine()
    got = auto_setup.engine_check(e, saved=False)
    assert got == {"preset": "fast", "set_now": True, "port": "opens on demand", "permission": "ask"}
    assert e.calls == [("preset", "fast")]
    e = FakeEngine(preset="careful")
    with pytest.raises(auto_setup.Stop, match="--open-port"):
        auto_setup.engine_check(e, saved=True)  # the owner's preset is kept, and said
    e = FakeEngine(preset="careful")
    assert auto_setup.engine_check(e, open_port=True, saved=True)["port"] == "open"
    assert e.calls == [("launch",)]


def test_engine_fails_when_grok_setting_changes():
    with pytest.raises(auto_setup.Stop, match="Execution setting changed"):
        auto_setup.engine_check(FakeEngine(port_open=True, perm=("ask", "always")), saved=True)


def test_engine_missing_is_named():
    class NoEngine:
        def status(self):
            return ge.Result(1, {}, "FAIL")
    with pytest.raises(auto_setup.Stop, match="no Grok engine"):
        auto_setup.engine_check(NoEngine())


def test_run_ends_with_one_pass_line(home, monkeypatch):
    monkeypatch.setattr(auto_setup, "ensure_botport", lambda svc, fetch=None: {
        "version": "0.3.0", "tag": "v0.3.0", "sha": "abc", "downloaded": True})
    monkeypatch.setattr(auto_setup, "engine_pinned", lambda: True)  # (as after the 0.3.0 pin bump)
    monkeypatch.setattr(auto_setup, "reach", lambda p, run=None, twins=(), link_other=False: "had it")
    monkeypatch.setattr(auto_setup, "path_note", lambda svc, run=None: "Grok app PATH has hermes and botport")
    monkeypatch.setattr(auto_setup, "policy_saved", lambda: False)
    said = []
    rc, line = auto_setup.run(object(), engine=FakeEngine(), say=said.append)
    assert rc == 0 and line == ("PASS: hermes twin setup --auto: botport v0.3.0 verified, engine ready (preset fast, "
                                "port opens on demand), reachable from profile default, Grok settings unchanged "
                                "(Execution: ask)")
    assert said[0].startswith("Downloaded and verified botport 0.3.0")


def test_run_fail_line_names_the_step(home, monkeypatch):
    def boom(svc, fetch=None):
        raise auto_setup.Stop("could not download botport v0.3.0 (offline)")
    monkeypatch.setattr(auto_setup, "ensure_botport", boom)
    monkeypatch.setattr(auto_setup, "engine_pinned", lambda: True)  # (as after the 0.3.0 pin bump)
    rc, line = auto_setup.run(object(), say=lambda s: None)
    assert rc == 1 and line == "FAIL: hermes twin setup --auto: botport: could not download botport v0.3.0 (offline)"


def test_cli_setup_auto_and_install_line(svc, monkeypatch):
    seen = {}

    def fake_run(s, open_port=False, link_profile=False, gateways=None):
        seen["gateways"] = gateways
        return 0, f"PASS: x open_port={open_port}"
    monkeypatch.setattr(auto_setup, "run", fake_run)
    rc, out, _ = run(["setup", "--auto", "--open-port"])
    assert rc == 0 and out.strip() == "PASS: x open_port=True"
    assert callable(seen["gateways"])  # twin#75: setup restarts the running twin gateways (never called here)
    rc, out, _ = run(["setup", "--auto", "--no-gateway-restart"])
    assert rc == 0 and seen["gateways"] is None
    monkeypatch.setattr(auto_setup, "plugin_ref", lambda: "a" * 40)
    rc, out, _ = run(["setup", "--install-line"])
    assert out.strip() == (f"hermes plugins install hudsonwa/twin --ref {'a' * 40} --enable && "
                           "hermes twin setup --auto")


# ---- 09: Telegram through the existing bot -------------------------------------------------------------------------
TOKEN = "123456:" + "A" * 30


def test_env_keys_never_returns_the_token(home):
    h = prof(home, "default", env=f"TELEGRAM_BOT_TOKEN={TOKEN}\nTELEGRAM_ALLOWED_USERS={OWNER}\n")
    got = tg_route.env_keys(h)
    assert got == {"token": True, "users": OWNER, "secrets_command": False}
    assert TOKEN not in json.dumps(got)


def test_no_telegram_bot_names_botfather(home):
    prof(home, "default", "model: x\n")
    line = tg_route.turn_on(["acme-support"])
    assert line.startswith("FAIL: telegram: no Hermes profile has a Telegram bot") and "@BotFather" in line


def _gateway(home, users=OWNER):
    prof(home, "default", "model: x\n", env=f"TELEGRAM_BOT_TOKEN={TOKEN}\nTELEGRAM_ALLOWED_USERS={users}\n")


def test_turn_on_reuses_existing_bot_owner_only(home):
    _gateway(home)
    reached = []
    line = tg_route.turn_on(["acme-support"], twin_profiles=("acme-support",), reach=reached.append)
    assert line.startswith("PASS: telegram: twins acme-support reachable through the existing Hermes Telegram bot of profile "
                           "default") and "no new token" in line
    assert reached == ["default"]
    st = tg_route.state()
    assert st["owner_ids"] == [OWNER] and st["token_by"] == "env"
    blob = (Path(os.environ["HERMES_HOME"]) / "plugin-data" / "grok-bot-twin" / "telegram-routes.json").read_text(encoding="utf-8")
    assert TOKEN not in blob and "AAAA" not in blob
    assert not (home / "profiles" / "acme-support" / ".env").exists()  # the twin gets no token


def test_several_allowed_users_need_owner(home):
    _gateway(home, f"{OWNER},{OTHER}")
    assert "--owner ID" in tg_route.turn_on(["acme-support"])
    assert tg_route.turn_on(["acme-support"], owner="5") .startswith("FAIL")
    assert tg_route.turn_on(["acme-support"], owner=OWNER).startswith("PASS")
    assert tg_route.state()["owner_ids"] == [OWNER]


def _src(user=OWNER, chat_type="dm", chat_id="42"):
    return SimpleNamespace(user_id=user, chat_type=chat_type, chat_id=chat_id)


def test_route_owner_dm_only(home, monkeypatch):
    _gateway(home)
    tg_route.turn_on(["acme-support"])
    seen = []
    monkeypatch.setattr(tg_route, "_turn", lambda p, t: seen.append((p, t)) or {"ok": True, "reply": "hi there"})
    assert tg_route.handle("to acme-support what is on today", "telegram", _src()) == "[acme-support] hi there"
    assert seen == [("acme-support", "what is on today")]
    assert tg_route.handle("to acme-support x", "telegram", _src(user=OTHER)) == "Not allowed."
    assert tg_route.handle("to acme-support x", "telegram", _src(chat_type="group")) == "Twins answer in a direct chat only."
    assert tg_route.handle("to acme-support x", "discord", _src()).startswith("The route to twins is for")
    assert tg_route.handle("to other x", "telegram", _src()) == "That twin is not on the Telegram route."
    assert len(seen) == 1


def test_route_switch(home, monkeypatch):
    _gateway(home)
    tg_route.turn_on(["acme-support"])
    monkeypatch.setattr(tg_route, "_turn", lambda p, t: {"ok": True, "reply": t.upper()})
    assert tg_route.handle("say hello", "telegram", _src()) == "Choose a twin first: /twin use NAME"
    assert tg_route.handle("use acme-support", "telegram", _src()).startswith("This chat now talks to the twin acme-support")
    assert tg_route.handle("say hello", "telegram", _src()) == "[acme-support] HELLO"
    assert tg_route.handle("say hello", "telegram", _src(chat_id="43")) == "Choose a twin first: /twin use NAME"
    tg_route.handle("use off", "telegram", _src())
    assert tg_route.handle("say hello", "telegram", _src()) == "Choose a twin first: /twin use NAME"
    assert tg_route.turn_off().startswith("PASS")
    assert tg_route.handle("to acme-support x", "telegram", _src()) == "The Telegram route to twins is off."


def test_turn_answers_every_approval_deny(home, monkeypatch):
    from hermes_plugins.grok_bot_twin.twin import tasks_turn
    got = {}

    def fake(profile, text, should_stop, on_wait, answer, limit_s=None):
        got.update(answer=answer(), stop=should_stop())
        return {"ok": True, "reply": "ok"}
    monkeypatch.setattr(tasks_turn, "run_turn", fake)
    assert tg_route._run_turn("acme-support", "x") == {"ok": True, "reply": "ok"}
    assert got == {"answer": "deny", "stop": None}


def test_slash_routes_on_telegram_and_refuses_locally(svc, monkeypatch):
    from hermes_plugins.grok_bot_twin.twin import zt_cli
    home = Path(os.environ["HERMES_HOME"])
    _gateway(home)
    tg_route.turn_on(["acme-support"])
    monkeypatch.setattr(zt_cli, "resolve_profile", lambda s, n: n)
    monkeypatch.setattr(tg_route, "_turn", lambda p, t: {"ok": True, "reply": "done"})
    assert slash.handle("to acme-support hello", platform="telegram", source=_src()) == "[acme-support] done"
    assert slash.handle("to acme-support hello", platform="cli", source=None).startswith("The route to twins is for")
    # Telegram still cannot start a sync
    assert "only shows status" in slash.handle("check", platform="telegram", source=_src())


def test_cli_telegram_status_and_off(svc):
    rc, out, _ = run(["telegram"])
    assert rc == 0 and out.startswith("Telegram route: off")
    rc, out, _ = run(["telegram", "off"])
    assert rc == 0 and out.startswith("PASS")


def test_new_modules_hold_no_addresses():
    import re
    root = Path(auto_setup.__file__).parent
    text = "".join((root / f).read_text(encoding="utf-8") for f in ("auto_setup.py", "tg_route.py", "profile_safety.py",
                                                    "zt_cli.py"))
    # no host addresses beyond loopback in examples, no numeric chat ids
    assert not re.search(r"\b100\.\d+\.\d+\.\d+\b|\b\d{7,}\b", text)


def test_setup_auto_replaces_an_older_botport_with_the_pinned_release(tmp_path, monkeypatch):
    """Live 0.5.0 RC: a sandbox kept botport 0.2.1 from plugin 0.4.x and setup --auto FAILed "not the release Hermes
    expects" instead of taking the pinned release. It now fetches the pin once and verifies again."""
    from hermes_plugins.grok_bot_twin.twin import auto_setup as A
    from hermes_plugins.grok_bot_twin.twin.engine import EngineError

    class Svc:
        def __init__(self):
            self.helper, self.taken = "0.2.1", []

        def release_tag(self):
            return "v0.3.0"

        def botport(self):
            return object()

        def choose_helper(self, path):
            self.taken.append(path)
            self.helper = "0.3.0"

        def trust_botport(self, _ask, tag):
            if self.helper != "0.3.0":
                raise EngineError("check_failed", "This botport is not the release Hermes expects (0.3.0).")
            return {"attested": True, "version": "0.3.0", "release_tag": tag, "sha256": "ab" * 32}

    f = tmp_path / "botport.tar.gz"
    monkeypatch.setattr(A, "fetch_pinned", lambda tag, fetch=None: (f.write_bytes(b"x"), f)[1])
    s = Svc()
    got = A.ensure_botport(s)
    assert got["downloaded"] and got["version"] == "0.3.0" and s.taken == [str(f)] and not f.exists()

    s2 = Svc()
    s2.choose_helper = lambda p: s2.taken.append(p)  # (the pinned file does not verify either: FAIL, one fetch)
    with pytest.raises(A.Stop, match="not verified"):
        A.ensure_botport(s2)
    assert len(s2.taken) == 1
