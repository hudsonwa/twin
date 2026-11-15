"""twin_make: one Hermes prompt makes or syncs one twin, in mirror-mode scope, with one PASS/FAIL line.

Invented bots only (Acme Support). The CLI steps and botport's behaviour test are stood in for.
"""
from __future__ import annotations

import json

from twin_testlib import cli, home, service, svc  # noqa: F401
from hermes_plugins.grok_bot_twin.twin import engine as E
from hermes_plugins.grok_bot_twin.twin import hermes_make, tasks


class Fake:
    def __init__(self, svc, monkeypatch, twinned=False, left=("instructions", "model"), rcs=None, battery=False,
                 test_ok=True):
        self.calls, self.twinned, self.left, self.rcs = [], twinned, list(left), dict(rcs or {})
        monkeypatch.setattr(cli, "_resolve", self._resolve)
        for name in ("cmd_add", "cmd_finish", "cmd_parity", "cmd_import_exports", "cmd_stop", "cmd_uninstall",
                     "cmd_unlink"):
            monkeypatch.setattr(cli, name, self._fake(name), raising=False)
        monkeypatch.setattr(svc, "batch_info", lambda pids=None: {"twins": [
            {"pair_id": "acme-support", "name": "Acme Support", "left": list(self.left)}]}, raising=False)

        class P:
            def is_file(self_inner):
                return battery
        monkeypatch.setattr(svc, "_battery_path", lambda pid: P(), raising=False)
        monkeypatch.setattr(svc, "behaviour_test", self._test, raising=False)
        self.test_ok = test_ok

    def _resolve(self, svc, given):
        if self.twinned and given.lower() in ("acme support", "acme-support"):
            return "acme-support"
        raise E.EngineError("usage", "No twin is called that.")

    def _fake(self, name):
        def f(a):
            self.calls.append((name, a))
            print("Acme Support terminal text")
            rc = self.rcs.get(name, 0)
            if name == "cmd_add" and rc == 0:
                self.twinned = True
            if name == "cmd_finish" and rc == 0:
                self.left = [x for x in self.left if x != "model"]
            return rc
        return f

    def _test(self, pid, battery=None, from_export=None):
        self.calls.append(("behaviour_test", pid))
        return {"passed": 6 if self.test_ok else 4, "total": 6, "ok": self.test_ok, "results": []}

    def names(self):
        return [n for n, _a in self.calls]


def call(**args):
    return json.loads(hermes_make.twin_make(args))


def test_new_twin_passes_and_lists_gaps(svc, monkeypatch):
    f = Fake(svc, monkeypatch, rcs={"cmd_parity": 1})
    out = call(bot_name="Acme Support")
    assert f.names() == ["cmd_add", "cmd_finish", "cmd_parity"]
    add, fin = f.calls[0][1], f.calls[1][1]
    assert add.bot == ["Acme Support"] and add.yes and not add.all
    assert fin.model is None and fin.yes and fin.twins == ["Acme Support"]  # the default model: no question
    v = out["verdict"]
    assert v.startswith("PASS: twin of \"Acme Support\" (mirror-mode scope")
    assert "gaps: instructions; behaviour test; skills; memory" in v and "\n" not in v
    assert out["grok_prompt"].startswith("Please write your setup export") and "hermes twin quick" in out["then"]
    assert "terminal text" not in json.dumps(out)


def test_second_run_is_idempotent_and_tests(svc, monkeypatch):
    f = Fake(svc, monkeypatch, twinned=True, left=(), battery=True)
    out = call(bot_name="acme support", model="grok-4.7")
    assert "cmd_add" not in f.names() and f.names()[-1] == "behaviour_test"
    assert f.calls[0][1].model == "grok-4.7"
    assert out["verdict"].startswith("PASS") and "gaps: skills; memory" in out["verdict"]
    assert "grok_prompt" not in out
    assert {"step": "behaviour test 6/6", "ok": True} in out["steps"]


def test_failing_behaviour_test_fails(svc, monkeypatch):
    Fake(svc, monkeypatch, twinned=True, left=(), battery=True, test_ok=False)
    assert call(bot_name="Acme Support")["verdict"].startswith("FAIL")


def test_no_model_fails_without_asking(svc, monkeypatch):
    Fake(svc, monkeypatch, rcs={"cmd_finish": 2})
    out = call(bot_name="Acme Support")
    assert out["verdict"].startswith("FAIL") and "give model" in out["verdict"]


def test_unknown_bot_fails(svc, monkeypatch):
    f = Fake(svc, monkeypatch, rcs={"cmd_add": 1})
    out = call(bot_name="Test Scout")
    assert f.names() == ["cmd_add"] and out["verdict"].startswith("FAIL")


def test_bot_must_be_named(svc, monkeypatch):
    f = Fake(svc, monkeypatch)
    for bad in ("", "  ", "all", "ALL", "*", "Acme*", None, 5, "x" * 101):
        assert call(bot_name=bad)["verdict"].startswith("FAIL")
    assert f.calls == []


def test_never_removes_anything(svc, monkeypatch):
    f = Fake(svc, monkeypatch, twinned=True, battery=True)
    call(bot_name="Acme Support")
    assert not {"cmd_stop", "cmd_uninstall", "cmd_unlink", "cmd_import_exports"} & set(f.names())


def test_request_from_another_computer_refused(svc, monkeypatch):
    f = Fake(svc, monkeypatch)
    monkeypatch.setattr(tasks, "asked_turn", lambda *a, **k: True)
    assert "another computer" in call(bot_name="Acme Support")["verdict"] and f.calls == []


def test_never_raises(svc, monkeypatch):
    monkeypatch.setattr(hermes_make, "make", lambda *a: 1 / 0)
    assert json.loads(hermes_make.twin_make({"bot_name": "Acme Support"}))["verdict"] == "FAIL: ZeroDivisionError"
    assert json.loads(hermes_make.twin_make(None))["verdict"].startswith("FAIL")


def test_registered_beside_twin_status():
    import hermes_plugins.grok_bot_twin as plugin
    names = []

    class Ctx:
        def register_tool(self, name, *a, **k):
            names.append(name)

        def __getattr__(self, _n):
            return lambda *a, **k: None
    plugin.register(Ctx())
    assert names.index("twin_make") == names.index("twin_transcripts_search") + 1
    assert hermes_make.TWIN_MAKE_SCHEMA["parameters"]["required"] == ["bot_name"]
    for word in ("twin", "clone", "copy", "duplicate", "back up"):
        assert word in hermes_make.TWIN_MAKE_SCHEMA["description"]
