"""M4: one lock per twin, shared by twin_from_grok, twin_back_to_grok, sync, quick, import and switch; flock-based,
so a lock left by a dead process is taken over atomically. Invented bots only."""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time

import pytest

from twin_testlib import fake_key, home, svc  # noqa: F401
from hermes_plugins.grok_bot_twin.twin import botlock, store


def test_reentrant_in_one_thread_and_exclusive_across_threads(home):
    with botlock.held("Acme Support"):
        with botlock.held("acme support"):  # same thread: re-entered, not deadlocked
            pass
        out = {}

        def other():
            try:
                with botlock.held("ACME SUPPORT", wait=False):
                    out["got"] = True
            except botlock.Busy:
                out["busy"] = True
        t = threading.Thread(target=other)
        t.start()
        t.join()
        assert out == {"busy": True}
    with botlock.held("Acme Support", wait=False):
        pass  # free again


def test_waiting_caller_gets_it_when_the_holder_ends(home):
    order = []
    got = threading.Event()

    def holder():
        with botlock.held("Recipe Planner"):
            got.set()
            time.sleep(0.3)
            order.append("first")
    t = threading.Thread(target=holder)
    t.start()
    got.wait(5)
    with botlock.held("Recipe Planner", timeout=10):
        order.append("second")
    t.join()
    assert order == ["first", "second"]


def test_a_lock_left_by_a_dead_process_is_taken_over(home):
    path = botlock._path(botlock.key_for("Acme Support"))
    code = ("import fcntl, os, sys; fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT, 0o600); "
            "fcntl.flock(fd, fcntl.LOCK_EX); print('held', flush=True); sys.stdin.readline()")
    if not hasattr(os, "fork"):
        pytest.skip("POSIX flock")
    p = subprocess.Popen([sys.executable, "-c", code, str(path)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         text=True)
    assert p.stdout.readline().strip() == "held"
    with pytest.raises(botlock.Busy):
        with botlock.held("Acme Support", wait=False):
            pass
    p.kill()
    p.wait()
    with botlock.held("Acme Support", wait=False):  # the OS dropped the dead holder's lock
        pass
    assert path.exists()  # nothing was unlinked


def _registry(svc, monkeypatch):
    reg = {"acme-support": {"pair_id": "acme-support", "grok": {"name": "Acme Support"},
                            "hermes": {"profile": "acme-support"}}}
    monkeypatch.setattr(svc, "_registry", lambda: dict(reg))
    monkeypatch.setattr(svc, "require_pair", lambda pid: pid)


def _blocked_while_held(fn):
    got, release, out = threading.Event(), threading.Event(), {}

    def hold():
        with botlock.held("acme support"):
            got.set()
            release.wait(10)
    t = threading.Thread(target=hold)
    t.start()
    got.wait(5)
    try:
        fn()
    except botlock.Busy:
        out["busy"] = True
    finally:
        release.set()
        t.join()
    return out


def test_switch_and_import_take_the_twin_lock(svc, home, monkeypatch):
    _registry(svc, monkeypatch)
    monkeypatch.setattr(svc, "_switch", lambda *a: {"resumed": []})
    monkeypatch.setattr(svc, "_import_setup", lambda *a: {"added": 0})
    monkeypatch.setattr(botlock, "WAIT_S", 0.2)
    assert _blocked_while_held(lambda: svc.switch("acme-support", [])) == {"busy": True}
    assert _blocked_while_held(lambda: svc.import_setup("acme-support", "{}", apply=True)) == {"busy": True}
    assert svc.import_setup("acme-support", "{}", apply=False) == {"added": 0}  # a preview writes nothing


def test_cli_sync_takes_the_twin_lock(svc, home, monkeypatch):
    from hermes_plugins.grok_bot_twin.twin import sync_both
    _registry(svc, monkeypatch)
    store.ensure_dir(store.profile_home("acme-support"))
    monkeypatch.setattr(botlock, "WAIT_S", 0.2)
    ran = []
    assert _blocked_while_held(lambda: sync_both.sync_bot(svc, "acme-support", {"instructions": "x"},
                                                          runner=lambda a: ran.append(a) or {})) == {"busy": True}
    assert not ran
