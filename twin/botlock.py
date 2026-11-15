"""One lock per twin, shared by every writer of that twin: the one-prompt MCP tools (twin_from_grok,
twin_back_to_grok), `hermes twin sync`, `quick`, `import` (import_setup) and `switch`.

It is an OS file lock (flock on macOS/Linux, a one-byte region lock on Windows: osflags.lock_file) on
<plugin-data>/locks/twin-<KEY>.lock. The OS lets go of it when the holding process dies, so a lock left by a run
that crashed is taken over atomically by the next caller: there is no stale-file check and nothing is unlinked.
Within one thread the lock is re-entrant (twin_from_grok holds it and then calls import_setup and switch, which
take it too); another thread or process waits (`wait=True`, up to `timeout` seconds) or is refused at once.
"""
from __future__ import annotations

import contextlib
import hashlib
import os
import threading
import time
from typing import Iterator, Optional

from . import osflags as _osflags
from . import store
from .engine import EngineError

WAIT_S = 600.0
_STEP_S = 0.05
_GUARD = threading.Lock()
_HELD: dict = {}  # key -> [thread ident, depth]


def key_for(name: str) -> str:
    """The lock's key: the Grok bot's name (spaces collapsed, case ignored), the one thing every caller knows,
    including twin_from_grok before the twin exists."""
    return hashlib.sha256(" ".join(str(name).split()).casefold().encode("utf-8")).hexdigest()[:16]


def name_of(svc, pid: str) -> str:
    """The Grok bot name a twin's lock is keyed by (its pair id when the entry has no name)."""
    entry = svc._registry().get(pid) or {}
    name = (entry.get("grok") or {}).get("name")
    return name if isinstance(name, str) and name.strip() else f"pair:{pid}"


def for_pair(svc, pid: str, wait: bool = True, timeout: Optional[float] = None):
    return held(name_of(svc, pid), wait=wait, timeout=timeout)


class Busy(EngineError):
    def __init__(self) -> None:
        super().__init__("busy", "Another run is changing this twin right now.",
                         "Try again when it has finished.")


def _path(key: str):
    return store.ensure_dir(store.central_dir() / "locks") / f"twin-{key}.lock"


@contextlib.contextmanager
def held(name: str, wait: bool = True, timeout: Optional[float] = None) -> Iterator[None]:
    """Hold the lock of one twin, by its Grok bot's name."""
    key, me = key_for(name), threading.get_ident()
    with _GUARD:
        cur = _HELD.get(key)
        if cur is not None and cur[0] == me:
            cur[1] += 1
            reentered = True
        else:
            reentered = False
    if reentered:
        try:
            yield
        finally:
            with _GUARD:
                _HELD[key][1] -= 1
        return
    fd = _osflags.open_nofollow(_path(key), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        if _osflags.can_lock():
            deadline = time.monotonic() + max(0.0, WAIT_S if timeout is None else timeout)
            while not _osflags.try_lock_file(fd):
                if not wait or time.monotonic() >= deadline:
                    raise Busy()
                time.sleep(_STEP_S)
        with _GUARD:
            _HELD[key] = [me, 1]
        try:
            yield
        finally:
            with _GUARD:
                _HELD.pop(key, None)
            with contextlib.suppress(OSError):
                if _osflags.can_lock():
                    _osflags.unlock_file(fd)
    finally:
        os.close(fd)
