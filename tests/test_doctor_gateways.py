"""Doctor's twin gateways check: read-only (only `gateway status`), ends with ONE PASS/FAIL line naming every offline
twin and the command to fix it. Invented twins only (acme-support, recipe-planner, garden-helper); fake runner only."""
from __future__ import annotations

from types import SimpleNamespace

from twin_testlib import home, svc  # noqa: F401
from hermes_plugins.grok_bot_twin.twin import behaviour, cli, gateways, zt_cli

UP = "Gateway: running (pid 4242)\n  telegram: connected as @acme_support_bot\n"


def _fake(states: dict, calls: list):
    def run(argv, timeout):
        calls.append(argv)
        assert argv[0] == "/fake/hermes" and argv[1] == "-p" and argv[3:] == ["gateway", "status"], argv
        st = states[argv[2]]
        if isinstance(st, Exception):
            raise st
        return st
    return run


def test_all_running_with_telegram_up_is_one_pass_line():
    calls = []
    run = _fake({"acme-support": (0, UP, ""), "recipe-planner": (0, UP.encode(), b"")}, calls)
    line = gateways.doctor_line(gateways.check_all(["acme-support", "recipe-planner", "default"], "/fake/hermes", run))
    assert line.startswith("PASS") and "acme-support" in line and "recipe-planner" in line and "\n" not in line
    assert all(c[3:] == ["gateway", "status"] for c in calls) and len(calls) == 2  # read-only, default skipped


def test_stopped_gateway_and_silent_telegram_are_named_with_the_fix():
    calls = []
    run = _fake({"acme-support": (0, UP, ""),
                 "recipe-planner": (1, "Gateway: not running\n", ""),
                 "garden-helper": (0, "Gateway: running\n  telegram: disconnected (retrying)\n", "")}, calls)
    res = gateways.check_all(["acme-support", "recipe-planner", "garden-helper"], "/fake/hermes", run)
    line = gateways.doctor_line(res)
    assert line.startswith("FAIL") and "\n" not in line
    assert "recipe-planner (gateway not running)" in line and "garden-helper (Telegram not connected)" in line
    assert "hermes -p recipe-planner gateway restart" in line and "hermes -p garden-helper gateway restart" in line
    assert "acme-support" not in line
    assert not any(v in c for c in calls for v in ("restart", "start", "stop"))


def test_status_that_cannot_be_read_is_offline_and_unreported_telegram_still_passes():
    run = _fake({"acme-support": TimeoutError("slow"), "recipe-planner": (0, "Gateway: running\n", "")}, [])
    res = gateways.check_all(["recipe-planner"], "/fake/hermes", run)
    assert gateways.doctor_line(res).startswith("PASS") and "did not report Telegram" in gateways.doctor_line(res)
    res = gateways.check_all(["acme-support"], "/fake/hermes", _fake({"acme-support": OSError("x")}, []))
    assert gateways.doctor_line(res).startswith("FAIL") and "acme-support (gateway not running)" in gateways.doctor_line(res)


def test_no_twins_passes_and_missing_hermes_fails():
    assert gateways.doctor_line(gateways.check_all([], None, None)).startswith("PASS")
    line = gateways.doctor_line(gateways.check_all(["acme-support"], "", None))
    assert line.startswith("FAIL") and "not checked" in line


def test_doctor_ends_with_the_gateway_line(svc, monkeypatch, capsys):  # noqa: F811
    calls = []
    monkeypatch.setattr(zt_cli, "twin_profiles", lambda s: ("acme-support",))
    monkeypatch.setattr(gateways, "_run", _fake({"acme-support": (1, "Gateway: stopped\n", "")}, calls))
    monkeypatch.setattr(behaviour, "hermes_path", lambda: "/fake/hermes")
    cli.cmd_doctor(SimpleNamespace(repair_pack=False))
    last = capsys.readouterr().out.rstrip("\n").splitlines()[-1]
    assert last.startswith("FAIL twin gateways") and "hermes -p acme-support gateway restart" in last
    assert calls and all(c[3:] == ["gateway", "status"] for c in calls)
