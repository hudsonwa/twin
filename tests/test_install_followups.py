"""twin#75: install follow-ups. Invented twins only (acme-support, recipe-planner); no real gateway is ever started,
stopped or asked: every Hermes call goes to a fake runner."""
from __future__ import annotations

import argparse
import ast
import json
import subprocess
from pathlib import Path

import pytest

from twin_testlib import home, svc  # noqa: F401
from hermes_plugins.grok_bot_twin.twin import auto_setup, config, gateways, model_check, zt_cli

ROOT = Path(__file__).resolve().parent.parent


# ---- 1. no Python 3.10-only call in the tools or the plugin ------------------------------------------------------
def test_no_write_text_newline_argument_anywhere():
    """Path.write_text(newline=) is Python 3.10+; macOS' system Python is 3.9 (tools/stamp_build.py failed there)."""
    bad = []
    for path in [*(ROOT / "twin").rglob("*.py"), *(ROOT / "tools").rglob("*.py")]:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "write_text"
                    and any(k.arg == "newline" for k in node.keywords)):
                bad.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert not bad, bad


def test_stamp_build_writes_the_stamp(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("stamp_build", ROOT / "tools" / "stamp_build.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    repo = tmp_path / "repo"
    (repo / "twin").mkdir(parents=True)
    (repo / "twin" / "x.py").write_text("x = 1\n", encoding="utf-8")
    git = ["git", "-C", str(repo), "-c", "user.name=Test", "-c", "user.email=test@example.invalid"]
    subprocess.run([*git, "init", "-q"], check=True, timeout=30)
    subprocess.run([*git, "add", "-A"], check=True, timeout=30)
    subprocess.run([*git, "commit", "-qm", "one"], check=True, timeout=30)
    got = mod.stamp(repo, repo)
    raw = (repo / "twin" / "BUILD").read_bytes()
    assert raw.endswith(b"}\n") and b"\r" not in raw and json.loads(raw) == got and len(got["commit"]) == 40


# ---- 2. check-model inside a twin's profile ----------------------------------------------------------------------
@pytest.fixture
def two_twins(monkeypatch):
    checked = []
    monkeypatch.setattr(zt_cli, "_svc", lambda: object())
    monkeypatch.setattr(zt_cli, "twin_profiles", lambda s: ("acme-support", "recipe-planner"))
    monkeypatch.setattr(model_check, "check", lambda prof: checked.append(prof) or {"ok": True, "line": f"PASS {prof}"})
    return checked


def test_check_model_in_a_twin_profile_uses_that_twin(two_twins, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "hermes_home", lambda: str(tmp_path / "profiles" / "recipe-planner"))
    monkeypatch.setattr(config, "profile_name", lambda home: Path(home).name)
    assert zt_cli.cmd_check_model(argparse.Namespace(twin=None, json=False)) == 0
    assert two_twins == ["recipe-planner"]


def test_check_model_outside_a_twin_profile_still_asks_which(two_twins, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "hermes_home", lambda: str(tmp_path))
    monkeypatch.setattr(config, "profile_name", lambda home: "default")
    monkeypatch.setattr(zt_cli, "_only", lambda s: (_ for _ in ()).throw(zt_cli.EngineError("usage", "say which")))
    with pytest.raises(zt_cli.EngineError):
        zt_cli.cmd_check_model(argparse.Namespace(twin=None, json=False))
    assert two_twins == []


# ---- 3. gateway restart helper (fake runner only) ----------------------------------------------------------------
class FakeHermes:
    """Gateways by profile: True running, False stopped. `restart_kills`: profiles whose restart is interrupted
    (times out and leaves the gateway stopped). `start_fails`: profiles whose start does nothing."""

    def __init__(self, running, restart_kills=(), start_fails=()):
        self.running, self.restart_kills, self.start_fails = dict(running), set(restart_kills), set(start_fails)
        self.calls = []

    def __call__(self, argv, timeout):
        assert argv[0] == "/fake/hermes" and argv[1] == "-p" and argv[3] == "gateway"
        prof, verb = argv[2], argv[4]
        self.calls.append((prof, verb))
        if verb == "status":
            return (0, b"Gateway is running (pid 4242)", b"") if self.running.get(prof) else (
                1, b"Gateway is not running", b"")
        if verb == "restart":
            self.running[prof] = False
            if prof in self.restart_kills:
                raise subprocess.TimeoutExpired(argv, timeout)
            self.running[prof] = True
            return 0, b"", b""
        if verb == "start":
            if prof not in self.start_fails:
                self.running[prof] = True
            return 0, b"", b""
        raise AssertionError(verb)


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


def _restart(fake, profiles=("acme-support", "recipe-planner", "widget-desk")):
    c = Clock()
    return gateways.restart_running(profiles, hermes="/fake/hermes", run=fake, wait_s=10, sleep=c.sleep, clock=c)


def test_every_gateway_running_before_runs_again_and_stopped_ones_stay_stopped():
    fake = FakeHermes({"acme-support": True, "recipe-planner": True, "widget-desk": False})
    res = _restart(fake)
    assert res == {"restarted": ["acme-support", "recipe-planner"], "offline": [], "left": [], "skipped": ""}
    assert fake.running == {"acme-support": True, "recipe-planner": True, "widget-desk": False}
    assert ("widget-desk", "restart") not in fake.calls and ("widget-desk", "start") not in fake.calls


def test_an_interrupted_restart_is_started_again():
    fake = FakeHermes({"acme-support": True}, restart_kills={"acme-support"})
    res = _restart(fake, ("acme-support",))
    assert res["restarted"] == ["acme-support"] and fake.running["acme-support"] is True
    assert ("acme-support", "start") in fake.calls


def test_a_gateway_that_will_not_start_is_named_offline_in_the_pass_line():
    fake = FakeHermes({"acme-support": True, "recipe-planner": True}, restart_kills={"recipe-planner"},
                      start_fails={"recipe-planner"})
    res = _restart(fake, ("acme-support", "recipe-planner"))
    assert res["offline"] == ["recipe-planner"] and res["restarted"] == ["acme-support"]
    words = gateways.note(res)
    assert "OFFLINE twin gateway(s)" in words and "recipe-planner" in words
    assert "hermes -p recipe-planner gateway start" in words


class SlowHermes(FakeHermes):
    """Every restart call takes `cost` seconds on the shared clock."""

    def __init__(self, running, clock, cost):
        super().__init__(running)
        self.clock, self.cost = clock, cost

    def __call__(self, argv, timeout):
        if argv[4] == "restart":
            self.clock.t += self.cost
        return super().__call__(argv, timeout)


def test_time_cap_leaves_the_remaining_twins_as_they_were_and_names_them():
    c = Clock()
    fake = SlowHermes({"acme-support": True, "recipe-planner": True, "widget-desk": True}, c, cost=100)
    res = gateways.restart_running(("acme-support", "recipe-planner", "widget-desk"), hermes="/fake/hermes",
                                   run=fake, wait_s=10, sleep=c.sleep, clock=c, total_s=150)
    assert res["restarted"] == ["acme-support", "recipe-planner"] and res["left"] == ["widget-desk"]
    assert not any(p == "widget-desk" for p, _ in fake.calls)  # not checked, not stopped
    assert fake.running["widget-desk"] is True
    words = gateways.note(res)
    assert "time cap" in words and "hermes -p widget-desk gateway restart" in words


def test_default_cap_and_shorter_per_twin_wait():
    assert gateways.TOTAL_S == 180.0 and gateways.WAIT_S < 120.0


def test_cap_zero_touches_nothing():
    fake = FakeHermes({"acme-support": True})
    c = Clock()
    res = gateways.restart_running(("acme-support",), hermes="/fake/hermes", run=fake, sleep=c.sleep, clock=c,
                                   total_s=0)
    assert res["left"] == ["acme-support"] and fake.calls == []


def test_setup_cli_passes_the_cap(monkeypatch):
    seen = []
    monkeypatch.setattr(zt_cli, "_svc", lambda: None)
    monkeypatch.setattr(zt_cli, "twin_profiles", lambda svc: ("acme-support",))
    monkeypatch.setattr(gateways, "restart_running", lambda profs, total_s: seen.append(total_s) or {})
    monkeypatch.setattr(auto_setup, "run", lambda svc, open_port, link_profile, gateways: (gateways(), (0, "PASS"))[1])
    p = argparse.ArgumentParser()
    zt_cli.add_setup_flags(p)
    for argv in ([], ["--gateway-restart-cap", "60"]):
        a = p.parse_args(argv)
        a.install_line = False
        assert zt_cli.cmd_setup_auto(a) == 0
    assert seen == [gateways.TOTAL_S, 60.0]


def test_the_default_profile_is_never_restarted():
    fake = FakeHermes({"default": True})
    assert _restart(fake, ("default",))["restarted"] == [] and fake.calls == []


def test_without_hermes_nothing_runs():
    def never(argv, timeout):
        raise AssertionError("no call")
    res = gateways.restart_running(("acme-support",), hermes="", run=never)
    assert res["skipped"] and "not restarted" in gateways.note(res)


def test_setup_pass_line_names_an_offline_twin(monkeypatch):
    monkeypatch.setattr(auto_setup, "engine_pinned", lambda: True)
    monkeypatch.setattr(auto_setup, "ensure_botport", lambda svc, fetch=None: {
        "downloaded": False, "version": "0.3.3", "tag": "v0.3.3", "sha": "abc"})
    monkeypatch.setattr(auto_setup, "active_profile", lambda: "default")
    monkeypatch.setattr(auto_setup, "reach", lambda *a, **k: "already")
    monkeypatch.setattr(auto_setup, "twin_profiles", lambda svc: ())
    monkeypatch.setattr(auto_setup, "path_note", lambda svc, runner: "PATH ok")
    monkeypatch.setattr(auto_setup, "engine_check", lambda eng, open_port: {
        "preset": "fast", "set_now": False, "port": "closed", "permission": "unknown"})
    monkeypatch.setattr(auto_setup, "parity_note", lambda svc, say: "")
    from hermes_plugins.grok_bot_twin.twin import origin
    monkeypatch.setattr(origin, "refresh", lambda svc: None)
    fake = FakeHermes({"acme-support": True}, restart_kills={"acme-support"}, start_fails={"acme-support"})
    rc, line = auto_setup.run(object(), engine=object(), say=lambda s: None,
                              gateways=lambda: _restart(fake, ("acme-support",)))
    assert rc == 0 and line.startswith("PASS") and "OFFLINE twin gateway(s), Telegram silent: acme-support" in line
