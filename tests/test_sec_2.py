"""SEC-2: the owner-only switches ask for a yes typed at a real terminal (tasks.owner_confirms, the one guard).

Before, `to-grok allow|apply`, `secret share --to-grok|--linked` and `requests on` only checked that no chat's
variables were set: `env -u HERMES_SESSION_ID ... --yes` from a model, or a Grok bot's own shell (which never has
them), went through. Now each asks at the controlling terminal itself and goes ahead only on a typed yes there; no
terminal (a tool's subprocess, a bot's shell, `setsid`) is a refusal, and --yes skips nothing. Invented twins and
values only; the terminal is a pretend one (tasks._open_terminal), never this computer's.
"""
from __future__ import annotations

import io
import subprocess
import sys

import pytest

from twin_testlib import cli, home, service, svc  # noqa: F401
from hermes_plugins.grok_bot_twin.twin import h2g, h2g_service, secret_cli, secret_ref, tasks, tasks_api
from test_secret_ref import mem, run_cli  # noqa: F401

SECRET = "ACME_API_KEY"
VALUE = "sk-" + "Pq8Wn" * 6  # invented, key-shaped


def _no_terminal():
    raise OSError(6, "Device not configured")  # what opening /dev/tty says without a controlling terminal


def _terminal(monkeypatch, answer):
    """A pretend controlling terminal that types `answer` (None: there is none). Returns what it was asked."""
    asked: list = []

    class Screen(io.StringIO):
        def close(self):
            asked.append(self.getvalue())
            super().close()

    monkeypatch.setattr(tasks, "_open_terminal",
                        _no_terminal if answer is None else (lambda: (io.StringIO(answer + "\n"), Screen())))
    return asked


@pytest.fixture
def sample(svc, monkeypatch):  # noqa: F811
    """The sample twin, with one change waiting in the preview (the owner allowed the name, at the terminal)."""
    for var in tasks.SESSION_VARS:
        monkeypatch.delenv(var, raising=False)
    svc.demo_action("start")
    _terminal(monkeypatch, "yes")
    assert cli.main(["to-grok", "Acme Support", "allow", "name"]) == 0
    t = svc.demo._twin("acme-support")
    t["name"] = "Acme Support Desk"
    svc.demo._write_twin("acme-support", t)
    return svc


def _grok_name(svc):  # noqa: F811
    fake = h2g.FakeGrokWriter(svc.central / h2g.FAKE_FILE)
    return fake.read(svc._h2g_bot("acme-support"))["name"]


def _calls(svc):  # noqa: F811
    cid = svc.to_grok_preview("acme-support")["change_id"]
    return {"to-grok apply": (lambda: cli.main(["to-grok", "Acme Support", "apply", cid]),
                              lambda: _grok_name(svc) == "Acme Support"),
            "to-grok allow": (lambda: cli.main(["to-grok", "Acme Support", "allow", "description"]),
                              lambda: svc.to_grok_info("acme-support")["allowed"] == ["name"]),
            "secret share --to-grok": (lambda: run_cli("secret", "share", SECRET, "--to-grok", "--yes")[0],
                                       lambda: not secret_ref.load()[SECRET]["to_grok"]),
            "secret share --linked": (lambda: run_cli("secret", "share", SECRET, "--linked", "--yes")[0],
                                      lambda: not secret_ref.load()[SECRET]["linked"]),
            "requests on": (lambda: cli.main(["requests", "on"]), lambda: tasks.switch()["on"] is False)}


@pytest.fixture
def guarded(sample, mem):  # noqa: F811
    secret_ref.keep(SECRET, VALUE)
    return _calls(sample)


def test_SEC_2_without_a_controlling_terminal_each_owner_only_step_is_refused_and_changes_nothing(guarded, monkeypatch,
                                                                                                  capsys):
    _terminal(monkeypatch, None)  # no HERMES_SESSION_* at all (scrubbed with env -u, or a Grok bot's shell)
    for name, (run, unchanged) in guarded.items():
        assert run() != 0, name
        assert unchanged(), name
    assert capsys.readouterr().err.count(tasks.OWNER_ONLY) == 3
    rc, out = run_cli("secret", "share", SECRET, "--to-grok", "--yes")
    assert rc == 1 and tasks.OWNER_ONLY in out and VALUE not in out
    with pytest.raises(SystemExit) as exc:  # to-grok never had a --yes, and has none now
        cli.main(["to-grok", "Acme Support", "allow", "description", "--yes"])
    assert exc.value.code != 0


def test_SEC_2_a_typed_yes_goes_ahead_and_any_other_answer_is_refused(guarded, monkeypatch, capsys):
    for answer in ("no", "", "y", "yes please"):
        asked = _terminal(monkeypatch, answer)
        for name, (run, unchanged) in guarded.items():
            assert run() != 0 and unchanged(), (answer, name)
        assert len(asked) == len(guarded) and all("Type yes" in q for q in asked)
    asked = _terminal(monkeypatch, " YES ")
    for name, (run, unchanged) in guarded.items():
        assert run() == 0 and not unchanged(), name
    assert len(asked) == len(guarded)  # one question each, asked at the terminal (not on stdout)
    assert "Make this change to Acme Support in Grok?" in asked[0] and "Allow the sync bot to change" in asked[1] and "Mirror" not in asked[1]
    assert f"Share {SECRET} with the Grok bot" in asked[2] and "linked computers" in asked[3]
    assert "Type yes" not in capsys.readouterr().out


def test_SEC_2_a_chat_is_refused_before_the_terminal_is_opened(guarded, monkeypatch):
    def opened():
        raise AssertionError("the terminal was opened for a chat's command")
    monkeypatch.setattr(tasks, "_open_terminal", opened)
    for var, value in (("HERMES_SESSION_ID", "a-chat-0001"), ("HERMES_SESSION_PLATFORM", "telegram")):
        monkeypatch.setenv(var, value)
        for name, (run, unchanged) in guarded.items():
            assert run() != 0 and unchanged(), (var, name)
        monkeypatch.delenv(var)
    monkeypatch.setattr(tasks, "asked_turn", lambda *a, **k: True)  # the turn of a request from another computer
    for name, (run, unchanged) in guarded.items():
        assert run() != 0 and unchanged(), name


def test_SEC_2_the_twins_page_route_asks_nothing_at_a_terminal(sample, monkeypatch):
    monkeypatch.setattr(tasks, "_open_terminal", _no_terminal)
    assert "description" in sample.to_grok_allow("acme-support", ["name", "description"], True)["allowed"]
    p = sample.to_grok_preview("acme-support")
    assert sample.to_grok_apply("acme-support", p["change_id"], True)["state"] in ("done", "sent")


def test_SEC_2_one_guard_and_a_real_process_without_a_terminal_is_refused(home):  # noqa: F811
    from pathlib import Path
    root = Path(tasks.__file__).resolve().parents[1]
    for path in list((root / "twin").glob("*.py")) + list((root / "dashboard").glob("*.py")):
        assert "_owner_terminal" not in path.read_text(encoding="utf-8"), path.name
    assert "owner_confirms(" in Path(h2g_service.__file__).read_text(encoding="utf-8")
    assert "owner_confirms(" in Path(tasks_api.__file__).read_text(encoding="utf-8")
    assert "owner_confirms(" in Path(secret_cli.__file__).read_text(encoding="utf-8")
    # the real opener, in a new session (no controlling terminal: what `setsid` or a bot's shell gives)
    code = ("import sys, types; sys.modules['hermes_plugins'] = types.ModuleType('hermes_plugins'); "
            "sys.modules['hermes_plugins'].__path__ = []; import importlib.util as u; "
            "s = u.spec_from_file_location('hermes_plugins.grok_bot_twin', sys.argv[1], "
            "submodule_search_locations=[sys.argv[2]]); m = u.module_from_spec(s); "
            "sys.modules[s.name] = m; s.loader.exec_module(m); "
            "from hermes_plugins.grok_bot_twin.twin import tasks; print(tasks.owner_confirms('Go?'))")
    if sys.platform == "win32":
        pytest.skip("a new session without a console is a POSIX test")
    cp = subprocess.run([sys.executable, "-c", code, str(root / "__init__.py"), str(root)], capture_output=True,
                        text=True, timeout=60, start_new_session=True, stdin=subprocess.DEVNULL, encoding="utf-8")
    assert cp.stdout.strip().splitlines()[-1:] == ["False"], cp.stdout + cp.stderr
