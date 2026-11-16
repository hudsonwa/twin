"""`hermes twin quick` (one twin start to finish) and `hermes twin test` (botport's behaviour test).

Invented bots only (Acme Support, Recipe Planner). quick is the existing commands in order: the tests stand each
of them in and check the order, the wait, what is skipped on a second run and the summary. test runs a small fake
botport for the engine (argv, no twin globals, exit codes) and a fake engine for the service (what is kept).
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

from twin_testlib import cli, home, service, svc  # noqa: F401
from hermes_plugins.grok_bot_twin.twin import behaviour, quick_cli, tasks
from hermes_plugins.grok_bot_twin.twin import engine as E


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = cli.main(argv)
    return rc, out.getvalue(), err.getvalue()


# ---------------------------------------------------------------------------------------------- quick

class Steps:
    """Stands in for add, import-exports, finish and compare, and the service calls quick makes itself."""

    def __init__(self, svc, monkeypatch, twinned=False, left=("instructions", "model"), arrives_after=1, rcs=None):
        self.calls, self.twinned, self.left = [], twinned, list(left)
        self.scans, self.arrives_after = 0, arrives_after
        self.rcs = dict(rcs or {})
        monkeypatch.setattr(cli, "_resolve", self._resolve)
        for name in ("cmd_add", "cmd_import_exports", "cmd_finish", "cmd_parity"):
            monkeypatch.setattr(cli, name, self._fake(name))
        monkeypatch.setattr(cli, "import_text", lambda svc, pid, text, a: self._fake("import_text")((text, a)))
        for name in ():
            monkeypatch.setattr(cli, name, self._fake(name))
        monkeypatch.setattr(svc, "batch_info", lambda pids=None: {"twins": [
            {"pair_id": "acme-support", "name": "Acme Support", "left": list(self.left)}]}, raising=False)
        monkeypatch.setattr(svc, "downloads_scan", self._scan, raising=False)
        monkeypatch.setattr(quick_cli, "POLL_S", 0)

    def _resolve(self, svc, given):
        if self.twinned and given.lower() == "acme support":
            return "acme-support"
        raise E.EngineError("usage", "No twin is called that.")

    def _fake(self, name):
        def f(a):
            self.calls.append((name, a))
            rc = self.rcs.get(name, 0)
            if name == "cmd_add" and rc == 0:
                self.twinned = True
            if name == "cmd_import_exports" and rc == 0:
                self.left = [x for x in self.left if x != "instructions"]
            return rc
        return f

    def _scan(self, since, pids, apply):
        assert apply is False and pids == ["acme-support"]  # quick only looks; import-exports imports
        self.scans += 1
        return {"waiting": [] if self.scans >= self.arrives_after else ["acme-support"]}

    def names(self):
        return [n for n, _a in self.calls]


def test_quick_parses(svc):
    a = cli.build_parser().parse_args(["quick", "Acme Support", "--model", "grok-4.7", "--yes"])
    assert (a.twin_command, a.name, a.model, a.yes, a.wait) == ("quick", "Acme Support", "grok-4.7", True, 15)
    with pytest.raises(SystemExit):
        with redirect_stderr(io.StringIO()):
            cli.build_parser().parse_args(["quick", "Acme Support", "--wait", "0"])


def test_quick_runs_every_step_in_order_and_passes(svc, monkeypatch):
    s = Steps(svc, monkeypatch, arrives_after=3)
    rc, out, _err = run(["quick", "Acme Support", "--model", "grok-4.7", "--yes"])
    assert rc == 0, out
    assert s.names() == ["cmd_add", "cmd_import_exports", "cmd_finish", "cmd_parity"]
    assert s.scans == 3
    add, imp, fin, cmp_ = (a for _n, a in s.calls)
    assert add.bot == ["Acme Support"] and add.yes and not add.all
    assert imp.twin == ["Acme Support"] and imp.folder == cli.EXPORTS_DIR_HINT and imp.yes
    assert fin.twins == ["Acme Support"] and fin.model == "grok-4.7" and fin.yes and not fin.all
    assert cmp_.pair == "Acme Support"
    assert "--- paste from the next line ---" in out and out.rstrip().splitlines()[-1] == 'PASS: quick setup of "Acme Support"'
    assert out.count("✗") == 0


def test_quick_again_skips_what_is_done(svc, monkeypatch):
    s = Steps(svc, monkeypatch, twinned=True, left=("model",))
    rc, out, _err = run(["quick", "Acme Support", "--yes"])
    assert rc == 0
    assert s.names() == ["cmd_finish", "cmd_parity"] and s.scans == 0
    assert "already had one" in out and "instructions already in" in out and "paste from" not in out


def test_quick_stops_when_no_export_arrives(svc, monkeypatch):
    s = Steps(svc, monkeypatch, arrives_after=10 ** 9)
    clock = iter(range(0, 10 ** 6, 400))  # each look moves time on 400 s: two looks fit in 15 min
    monkeypatch.setattr(quick_cli, "_clock", lambda: next(clock))
    rc, out, _err = run(["quick", "Acme Support", "--yes"])
    assert rc == 1
    assert s.names() == ["cmd_add"] and s.scans == 3
    assert "FAIL" in out and "no setup export arrived in 15 min" in out


def test_quick_reports_a_failing_compare(svc, monkeypatch):
    Steps(svc, monkeypatch, rcs={"cmd_parity": 1})
    rc, out, _err = run(["quick", "Acme Support", "--yes"])
    assert rc == 1 and "✗ compare with Grok" in out and out.rstrip().splitlines()[-1].startswith("FAIL:")


def test_quick_stops_after_a_refused_add(svc, monkeypatch):
    s = Steps(svc, monkeypatch, rcs={"cmd_add": 1})
    rc, out, _err = run(["quick", "Acme Support"])
    assert rc == 1 and s.names() == ["cmd_add"] and "✗ twin added" in out


def test_quick_is_refused_in_a_requests_chat_turn(svc, monkeypatch):
    s = Steps(svc, monkeypatch)
    monkeypatch.setattr(tasks, "asked_turn", lambda: True)
    rc, _out, err = run(["quick", "Acme Support", "--yes"])
    assert rc == 1 and "another computer" in err and s.calls == []


# ---------------------------------------------------------------------------------------------- engine

FAKE = r'''
import json, os, sys
log = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "calls.jsonl")
with open(log, "a") as f:
    f.write(json.dumps({"argv": sys.argv[1:], "env": sorted(os.environ)}) + "\n")
mode = open(os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "mode")).read().strip()
if mode == "error":
    sys.stderr.write("botport: ERROR: --battery is required\n"); sys.exit(2)
if sys.argv[1] == "battery":
    print(json.dumps({"command": "battery init", "out": "x", "families": {"persona": 1}})); sys.exit(0)
ok = mode == "pass"
res = [{"id": "persona", "family": "persona", "pass": True, "why": []},
       {"id": "memory-1", "family": "memory", "pass": ok, "why": [] if ok else ["no match for 09"]}]
print(json.dumps({"command": "test", "profile": "acme-support", "pass": 1 + ok, "total": 2, "results": res,
                  "file": "f"}))
sys.exit(0 if ok else 1)
'''


@pytest.fixture
def fake_bp(tmp_path, monkeypatch):
    exe = tmp_path / "bin" / "botport"
    exe.parent.mkdir()
    exe.write_text(f"#!{sys.executable} -I\n{FAKE}", encoding="utf-8")
    exe.chmod(0o755)
    eng = E.BotportEngine(str(exe), tmp_path / "hermes-home", tmp_path / "central" / "botport-state")
    monkeypatch.setattr(eng, "_verify", lambda: (str(exe), {}))
    monkeypatch.setenv("FAKE_SECRET_TOKEN", "xai-FAKEFAKEFAKEFAKE0000")

    def mode(m):
        (exe.parent / "mode").write_text(m, encoding="utf-8")

    def calls():
        return [json.loads(x) for x in (exe.parent / "calls.jsonl").read_text(encoding="utf-8").splitlines()]
    mode("pass")
    return eng, mode, calls


def test_engine_test_argv_has_no_twin_globals(fake_bp):
    eng, _mode, calls = fake_bp
    data = eng.behaviour_test("acme-support", "/b/battery.json", "/usr/local/bin/hermes", "/o")
    assert data["pass"] == 2 and data["total"] == 2 and data["_rc"] == 0
    argv = calls()[-1]["argv"]
    assert argv[:5] == ["test", "--profile=acme-support", "--battery=/b/battery.json",
                        "--hermes-bin=/usr/local/bin/hermes", "--out=/o"]
    assert "--json" in argv and any(x.startswith("--hermes-home=") for x in argv)
    assert not any(x.startswith(("--state-dir=", "--grok-app-dir=")) for x in argv)  # botport refuses those here
    assert "FAKE_SECRET_TOKEN" not in calls()[-1]["env"]  # the same minimal environment
    eng.battery_init("/x/export.json", "/k/b.json")
    assert calls()[-1]["argv"][:4] == ["battery", "init", "--bundle=/x/export.json", "--out=/k/b.json"]


def test_engine_test_failure_and_error(fake_bp):
    eng, mode, _calls = fake_bp
    mode("fail")
    data = eng.behaviour_test("acme-support", "/b", "/h", "/o")
    assert data["pass"] == 1 and data["_rc"] == 1
    mode("error")
    with pytest.raises(E.EngineError) as exc:
        eng.behaviour_test("acme-support", "/b", "/h", "/o")
    assert exc.value.code == "exit_2" and "--battery is required" in exc.value.message
    assert "ERROR:" not in exc.value.message


# ---------------------------------------------------------------------------------------------- service + CLI

class FakeEngine:
    def __init__(self, passed=2):
        self.passed, self.calls = passed, []

    def battery_init(self, export, out):
        self.calls.append(("init", export, out))
        Path(out).write_text("{}", encoding="utf-8")
        return {}

    def behaviour_test(self, profile, battery, hermes, out, only=None, timeout=None):
        self.calls.append(("test", profile, battery, hermes, out))
        return {"pass": self.passed, "total": 2, "results": [
            {"id": "persona", "pass": True, "why": []},
            {"id": "memory-1", "pass": self.passed == 2, "why": [] if self.passed == 2 else ["no match for 09"]}]}


@pytest.fixture
def real_twin(svc, monkeypatch, tmp_path):
    svc._save_registry({"acme-support": {"pair_id": "acme-support", "grok": {"id": "g-acme", "name": "Acme Support"},
                                         "hermes": {"profile": "acme-support"}, "created_at": "2026-11-01T00:00:00Z"}})
    fake = FakeEngine()
    monkeypatch.setattr(svc, "engine_for", lambda pid: fake)
    monkeypatch.setattr(behaviour, "hermes_path", lambda: str(tmp_path / "hermes"))
    monkeypatch.setattr(type(svc), "_first_token_s", lambda self, hermes, profile: 1.0, raising=False)
    monkeypatch.setattr(cli, "_twin_names", lambda s: {"acme-support": "Acme Support"})
    export = tmp_path / "acme-export.json"
    export.write_text('{"format": "grok-bot-export", "version": 1, "bots": [{"name": "Acme Support"}]}', encoding="utf-8")
    return fake, export


def test_service_keeps_counts_and_failed_ids_only(svc, real_twin):
    fake, export = real_twin
    fake.passed = 1
    res = svc.behaviour_test("acme-support", from_export=str(export))
    assert (res["passed"], res["total"], res["ok"], res["failed"]) == (1, 2, False, ["memory-1"])
    assert [c[0] for c in fake.calls] == ["init", "test", "test"]  # memory-1 is retried once (still fails)
    kept = svc._battery_path("acme-support")
    assert kept.is_file() and fake.calls[1][2] == str(kept) and fake.calls[1][1] == "acme-support"
    rec = svc._registry()["acme-support"]["test"]
    assert set(rec) == {"at", "passed", "total", "failed", "retried"} and "no match" not in json.dumps(rec)
    # the next run reuses the kept battery; a refresh of the twin keeps the result
    fake.passed = 2
    assert svc.behaviour_test("acme-support")["ok"] is True
    svc._remember([{"pair_id": "acme-support", "grok": {"id": "g-acme", "name": "Acme Support"},
                    "hermes": {"profile": "acme-support"}}])
    assert svc._registry()["acme-support"]["test"]["passed"] == 2


class FlakyEngine(FakeEngine):
    """live-skills fails on the first run (the model answered from its prompt's skill index, no tool call)."""
    def __init__(self, retry_passes=True, memory_ok=True, persona_ok=True):
        super().__init__()
        self.retry_passes, self.memory_ok, self.persona_ok = retry_passes, memory_ok, persona_ok
        self.timeouts = []

    def behaviour_test(self, profile, battery, hermes, out, only=None, timeout=None):
        self.calls.append(("test", profile, battery, hermes, out, only))
        self.timeouts.append(timeout)
        rows = [{"id": "persona", "family": "persona", "pass": self.persona_ok, "why": []},
                {"id": "memory-1", "family": "memory", "pass": self.memory_ok, "why": []},
                {"id": "live-skills", "family": "live", "pass": bool(only) and self.retry_passes,
                 "why": [] if only and self.retry_passes else ["expected one of [\"skills_list\", \"skill_view\"]"]}]
        rows = [r for r in rows if not only or r["id"] in only]
        return {"pass": sum(r["pass"] for r in rows), "total": len(rows), "results": rows}


def test_a_model_flaky_case_is_retried_once_and_passes_only_if_the_retry_passes(svc, real_twin, monkeypatch):
    _fake, export = real_twin
    flaky = FlakyEngine()
    monkeypatch.setattr(svc, "engine_for", lambda pid: flaky)
    res = svc.behaviour_test("acme-support", from_export=str(export))
    assert (res["passed"], res["total"], res["ok"], res["retried"]) == (3, 3, True, ["live-skills"])
    assert [c[5] for c in flaky.calls if c[0] == "test"] == [None, ["live-skills"]]  # that case only, once
    assert svc._registry()["acme-support"]["test"]["retried"] == ["live-skills"]
    flaky.calls.clear()
    flaky.retry_passes = False  # still strict: a retry that fails is a FAIL, never a third try
    res = svc.behaviour_test("acme-support")
    assert (res["passed"], res["ok"], res["failed"]) == (2, False, ["live-skills"])
    assert len([c for c in flaky.calls if c[0] == "test"]) == 2


def test_no_retry_when_a_content_case_fails(svc, real_twin, monkeypatch):
    _fake, export = real_twin
    flaky = FlakyEngine(persona_ok=False)
    monkeypatch.setattr(svc, "engine_for", lambda pid: flaky)
    res = svc.behaviour_test("acme-support", from_export=str(export))
    assert res["ok"] is False and "retried" not in res and len([c for c in flaky.calls if c[0] == "test"]) == 1


def test_engine_test_only_flag(fake_bp):
    eng, _mode, calls = fake_bp
    eng.behaviour_test("acme-support", "/b", "/h", "/o", only=["live-skills", "live-time"])
    assert "--only=live-skills,live-time" in calls()[-1]["argv"]


def test_service_needs_a_battery_and_refuses_both(svc, real_twin, tmp_path):
    with pytest.raises(E.EngineError) as exc:
        svc.behaviour_test("acme-support")
    assert "--from-export" in exc.value.hint
    with pytest.raises(E.EngineError):
        svc.behaviour_test("acme-support", battery=str(tmp_path), from_export=None)  # a folder is not a battery
    with pytest.raises(E.EngineError):
        svc.behaviour_test("acme-support", battery="b", from_export="e")


def test_cli_test_prints_pass_fail_and_exit_status(svc, real_twin, monkeypatch):
    fake, export = real_twin
    fake.passed = 1
    rc, out, _err = run(["test", "Acme Support", "--from-export", str(export)])
    assert rc == 1 and "1 of 2 pass ✗" in out and "✗ memory-1: no match for 09" in out and "✓ persona" in out
    fake.passed = 2
    rc, out, _err = run(["test", "Acme Support"])
    assert rc == 0 and "2 of 2 pass ✓" in out


def test_row_words_show_the_last_test(svc):
    assert quick_cli.tested_words(None) == ""
    t = behaviour.summary({"at": "2026-11-15T10:00:00Z", "passed": 5, "total": 6, "failed": ["x"]})
    assert quick_cli.tested_words(t).startswith(" · test 5/6 ✗")
    assert behaviour.summary({"passed": 7, "total": 6}) is None
    p = {"pair_id": "acme-support", "grok": {"name": "Acme Support"}, "state": "ok", "test": t}
    assert " · test 5/6 ✗" in cli._pair_line(p)


def test_the_sample_cannot_be_tested(svc, monkeypatch):
    monkeypatch.setattr(svc, "require_pair", lambda pid: pid)
    monkeypatch.setattr(svc, "engine_for", lambda pid: svc.demo)
    with pytest.raises(E.EngineError) as exc:
        svc.behaviour_test("acme-sample")
    assert "sample" in exc.value.message


def test_quick_namespace_fits_the_commands_it_calls(svc):
    """The Namespaces quick builds carry every option the real add, import-exports, finish and compare read."""
    p = cli.build_parser()
    for argv, built in ((["add", "--bot", "X", "--yes"], dict(all=False, bot=["X"], profile=None, yes=True)),
                        (["import-exports", "~/Downloads", "--twin", "X"], dict(folder="~/Downloads", twin=["X"],
                                                                                 show=False, yes=False)),
                        (["finish", "X"], dict(twins=["X"], all=False, model=None, endpoint=None, yes=False)),
                        (["compare", "X"], dict(pair="X"))):
        real = vars(p.parse_args(argv))
        real.pop("twin_command"), real.pop("func")
        assert set(real) == set(argparse.Namespace(**built).__dict__), argv


EXPORT = '{"format": "grok-bot-export", "version": 1, "bots": [{"name": "Acme Support", "instructions": "Hi."}]}'


def test_quick_takes_the_export_on_stdin_without_paste_or_wait(svc, monkeypatch):
    s = Steps(svc, monkeypatch)
    monkeypatch.setattr(sys, "stdin", io.StringIO(EXPORT))
    rc, out, _err = run(["quick", "Acme Support", "--stdin", "--yes"])
    assert rc == 0 and s.scans == 0 and "paste from" not in out
    assert s.names() == ["cmd_add", "import_text", "cmd_finish", "cmd_parity"]
    text, a = s.calls[1][1]
    assert text == EXPORT and a.yes and a.bot is None
    assert out.rstrip().splitlines()[-1].startswith("PASS:")


def test_quick_takes_the_export_from_a_file(svc, monkeypatch, tmp_path):
    s = Steps(svc, monkeypatch, twinned=True)
    f = tmp_path / "acme.json"
    f.write_text(EXPORT, encoding="utf-8")
    rc, _out, _err = run(["quick", "Acme Support", "--from-file", str(f), "--yes"])
    assert rc == 0 and s.calls[0][1][0] == EXPORT and s.scans == 0
    with pytest.raises(SystemExit):
        with redirect_stderr(io.StringIO()):
            cli.build_parser().parse_args(["quick", "X", "--stdin", "--from-file", "f"])


def test_hermes_is_found_by_absolute_path_not_path(tmp_path, monkeypatch):
    """M6: a connector started with a minimal PATH still finds Hermes next to its own Python."""
    venv = tmp_path / "venv" / ("Scripts" if os.name == "nt" else "bin")
    venv.mkdir(parents=True)
    exe = venv / ("hermes.exe" if os.name == "nt" else "hermes")
    exe.write_text("#!/bin/sh\n", encoding="utf-8")
    exe.chmod(0o755)
    monkeypatch.setenv("PATH", "/nonexistent")
    monkeypatch.setattr(behaviour.sys, "executable", str(venv / "python"))
    monkeypatch.setattr(behaviour.sys, "argv", ["/x/mcp"])
    assert behaviour.hermes_path() == str(exe)
    if os.name == "nt":  # (no "writable by others" bit there: the rest is about that bit)
        return
    exe.chmod(0o777)  # writable by others: never used
    monkeypatch.setenv("HOME", str(tmp_path / "nohome"))
    assert behaviour.hermes_path() is None


# ---------------------------------------------------------------------------------------------- audit 16 Nov (#10)

class MemoryOnceEngine(FakeEngine):
    """memory-1 fails on the first run in a few seconds (no tool call), then passes: retried, counted as such."""
    def __init__(self):
        super().__init__()
        self.timeouts = []

    def behaviour_test(self, profile, battery, hermes, out, only=None, timeout=None):
        self.calls.append(("test", only))
        self.timeouts.append(timeout)
        rows = [{"id": "persona", "family": "persona", "pass": True, "why": [], "wall_s": 41.2},
                {"id": "memory-1", "family": "memory", "pass": bool(only), "why": [] if only else ["no tool call"],
                 "wall_s": 4.8}]
        rows = [r for r in rows if not only or r["id"] in only]
        return {"pass": sum(r["pass"] for r in rows), "total": len(rows), "results": rows}


def test_a_memory_case_that_fails_once_then_passes_counts_as_retried(svc, real_twin, monkeypatch):
    _fake, export = real_twin
    eng = MemoryOnceEngine()
    monkeypatch.setattr(svc, "engine_for", lambda pid: eng)
    res = svc.behaviour_test("acme-support", from_export=str(export))
    assert (res["passed"], res["total"], res["ok"], res["retried"]) == (2, 2, True, ["memory-1"])
    assert [c[1] for c in eng.calls if c[0] == "test"] == [None, ["memory-1"]]
    assert {r["id"]: r["wall_s"] for r in res["results"]} == {"persona": 41.2, "memory-1": 4.8}


def test_budget_scales_from_the_first_answer_and_covers_every_case(tmp_path):
    assert behaviour.per_case_budget(None) == behaviour.PER_CASE_FLOOR_S
    assert behaviour.per_case_budget(1.0) == behaviour.PER_CASE_FLOOR_S  # a fast model keeps the floor
    assert behaviour.per_case_budget(12.0) == 360.0  # a slow one gets more per case
    assert behaviour.per_case_budget(999.0) == behaviour.PER_CASE_MAX_S
    for n, ft in ((6, None), (6, 12.0), (12, 20.0)):
        per = behaviour.per_case_budget(ft)
        assert behaviour.call_budget(n, 3, per) >= n * per  # the whole call >= cases x per-case cap
    assert behaviour.call_budget(1, 3, 180) == E.TEST_TIMEOUT_S  # never below the old fixed budget
    b = tmp_path / "b.json"
    b.write_text(json.dumps({"gateway": {"prompt": "p", "expect": "ok"}, "cases": [{}] * 6, "gap_s": 5}))
    assert behaviour.battery_shape(str(b)) == (7, 5.0)
    assert behaviour.battery_shape(str(tmp_path / "missing.json")) == (6, 3.0)


def test_a_slow_fake_model_passes_inside_the_budget(svc, real_twin, monkeypatch, tmp_path):
    """A model that needs 12 s for one word and ~5 min per case: the call budget covers 6 such cases."""
    _fake, export = real_twin
    monkeypatch.setattr(type(svc), "_first_token_s", lambda self, hermes, profile: 12.0, raising=False)

    class Slow(FakeEngine):
        def behaviour_test(self, profile, battery, hermes, out, only=None, timeout=None):
            self.calls.append(("test", timeout))
            need = 6 * (300 + 3)  # six cases of 5 min each plus the gaps, as the slow model takes
            if timeout is None or timeout < need:
                raise E.EngineError("timeout", "botport did not finish in time.")
            rows = [{"id": f"case-{i}", "family": "persona", "pass": True, "why": [], "wall_s": 300.0} for i in range(6)]
            return {"pass": 6, "total": 6, "results": rows}
    eng = Slow()
    monkeypatch.setattr(svc, "engine_for", lambda pid: eng)
    kept = svc._battery_path("acme-support")
    kept.parent.mkdir(parents=True, exist_ok=True)
    kept.write_text(json.dumps({"cases": [{}] * 6, "gap_s": 3}))
    res = svc.behaviour_test("acme-support")
    assert res["ok"] is True and res["budget"] == {"per_case_s": 360, "first_answer_s": 12.0}


def test_concurrent_tests_on_one_model_take_turns(svc, real_twin, monkeypatch):
    import threading
    _fake, export = real_twin
    monkeypatch.setattr(behaviour, "model_endpoint", lambda profile: "http://127.0.0.1:9/v1")
    inside, most, said = [0], [0], []
    gate = threading.Lock()

    class Busy(FakeEngine):
        def behaviour_test(self, profile, battery, hermes, out, only=None, timeout=None):
            with gate:
                inside[0] += 1
                most[0] = max(most[0], inside[0])
            import time as _t
            _t.sleep(0.3)
            with gate:
                inside[0] -= 1
            return super().behaviour_test(profile, battery, hermes, out)
    eng = Busy()
    monkeypatch.setattr(svc, "engine_for", lambda pid: eng)
    svc.behaviour_test("acme-support", from_export=str(export))  # makes the kept battery
    errs = []

    def one():
        try:
            svc.behaviour_test("acme-support", say=said.append)
        except Exception as exc:  # pragma: no cover - shown on failure
            errs.append(exc)
    threads = [threading.Thread(target=one) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert not errs and most[0] == 1  # never two at once on one endpoint
    assert any("Another behaviour test is running" in s for s in said)


def test_the_endpoint_is_read_from_the_profile_config(svc, monkeypatch):
    from hermes_plugins.grok_bot_twin.twin import fleet_profiles
    home = fleet_profiles.profile_dir("acme-support")
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text("model:\n  default: local-7b\n  base_url: http://127.0.0.1:9/V1/\n")
    assert behaviour.model_endpoint("acme-support") == "http://127.0.0.1:9/v1"
    assert behaviour.model_endpoint("recipe-planner") == "default"


def test_cli_test_on_fail_prints_each_case_wall_time(svc, real_twin, monkeypatch):
    _fake, export = real_twin
    eng = MemoryOnceEngine()
    eng.behaviour_test = lambda *a, only=None, timeout=None: {"pass": 1, "total": 2, "results": [
        {"id": "persona", "family": "persona", "pass": True, "why": [], "wall_s": 41.2},
        {"id": "gateway-oneshot", "family": "gateway", "pass": False, "why": ["rc=1"], "wall_s": 181.0}]}
    monkeypatch.setattr(svc, "engine_for", lambda pid: eng)
    rc, out, _err = run(["test", "Acme Support", "--from-export", str(export)])
    assert rc == 1 and "✗ gateway-oneshot (181.0 s): rc=1" in out and "✓ persona (41.2 s)" in out
    assert "Budget: 180 s per case (a one-word answer took 1.0 s)" in out
