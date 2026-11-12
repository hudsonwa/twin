"""LOCK-1: status() answers from a fresh snapshot without waiting for a rebuild that holds TwinService._lock."""
from __future__ import annotations

import threading
import time

from twin_testlib import home, service, svc  # noqa: F401


class SlowBotport:
    """A stand-in botport whose `twin status --all` takes 1 s, on invented data (no twins)."""

    def __init__(self):
        self.calls = 0

    def status(self, pair=None):
        self.calls += 1
        time.sleep(1.0)
        return {"pairs": []}


def _rig(svc, monkeypatch):  # noqa: F811
    bp = SlowBotport()
    monkeypatch.setattr(svc, "botport", lambda: bp)
    monkeypatch.setattr(svc, "engine_info", lambda: {"available": True, "version": "test", "problem": None})
    monkeypatch.setattr(svc, "setup_brief", lambda: {"cause": None, "problem": None})
    return bp


def test_lock_1_fresh_snapshot_does_not_wait_for_a_rebuild(svc, monkeypatch):  # noqa: F811
    bp = _rig(svc, monkeypatch)
    first = svc.status(fresh=True)  # a snapshot younger than STATUS_TTL
    assert bp.calls == 1
    started = threading.Event()
    real_status = bp.status

    def slow_status(pair=None):
        started.set()
        return real_status(pair)
    bp.status = slow_status
    a = threading.Thread(target=lambda: svc.status(fresh=True))
    a.start()
    try:
        assert started.wait(5)  # thread A holds the lock inside botport's status
        t0 = time.monotonic()
        got = svc.status()
        waited = time.monotonic() - t0
    finally:
        a.join(10)
    assert waited < 0.2, waited
    assert got is first
    assert bp.calls == 2  # only thread A ran botport


def test_lock_1_invalidated_snapshot_rebuilds(svc, monkeypatch):  # noqa: F811
    bp = _rig(svc, monkeypatch)
    first = svc.status(fresh=True)
    assert svc.status() is first and bp.calls == 1  # fresh: the fast path, no botport
    svc.invalidate()
    again = svc.status()
    assert bp.calls == 2  # invalidated: no fast path, a rebuild
    assert again is not first
