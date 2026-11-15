"""The behaviour test of a twin: botport's own `botport test`, run on the twin's Hermes bot.

`compare` reads files and calls no model; this asks. botport runs `hermes -p PROFILE chat` once per case of a
battery (a small JSON file of prompts and the patterns a good answer has) and checks each answer. The battery is
the owner's: a file they name (`--battery FILE`), or one botport makes once from a setup export the owner names
(`--from-export FILE`, `botport battery init`), kept in the plugin's folder for the next run.

It runs through the same verified, digest-pinned copy of botport and the same minimal environment as every other
botport command (engine.BotportEngine._exec_report). Each case is a real chat with the twin's model, so it costs
what such a chat costs; it runs only when the owner asks for it.

Kept about a run, on the twin's entry in pairs.json: when it ran, how many cases passed of how many, and the ids of
the cases that failed. Never a prompt, an answer or a reason. botport's own results file stays in the plugin's
folder (0600), where botport wrote it.
"""
from __future__ import annotations

import os
import stat
import sys
from pathlib import Path
from typing import Any, Optional

from . import safe, store
from .engine import EngineError
from .model import now_iso

FAILED_IDS_MAX = 20
BATTERY_CAP = 1024 * 1024


def _regular_file(path: Any, what: str) -> str:
    """The absolute path of a regular file the owner named (never a folder, a pipe, a device or a link)."""
    try:
        full = os.path.abspath(os.path.expanduser(str(path)))
        st = os.lstat(full)
    except (OSError, ValueError, TypeError):
        raise EngineError("usage", f"That {what} could not be read.")
    if not stat.S_ISREG(st.st_mode):
        raise EngineError("usage", f"That {what} is not a plain file.")
    if st.st_size > BATTERY_CAP * 8:
        raise EngineError("too_large", f"That {what} is too large.")
    return full


def summary(rec: Any) -> Optional[dict]:
    """The last test of a twin as kept, checked: {"at","passed","total","ok","failed"} or None."""
    if not isinstance(rec, dict):
        return None
    passed, total = rec.get("passed"), rec.get("total")
    if not (isinstance(passed, int) and isinstance(total, int) and 0 <= passed <= total):
        return None
    return {"at": rec.get("at") if isinstance(rec.get("at"), str) else None, "passed": passed, "total": total,
            "ok": total > 0 and passed == total,
            "failed": [safe.clean_name(i, 80) for i in (rec.get("failed") or [])[:FAILED_IDS_MAX] if isinstance(i, str)]}


def hermes_path() -> Optional[str]:
    """Hermes' own command by absolute path, never looked up on PATH (a connector the Grok app starts has a short
    one): the one this process was started as, the one next to this Python (the venv Hermes runs in, which this
    plugin is loaded into), then Hermes' install folders under the home folder. Each must be a regular executable
    file owned by the user or root and not writable by others (bgagent._usable)."""
    from .bgagent import _usable
    seen = []
    argv0 = sys.argv[0] if sys.argv and isinstance(sys.argv[0], str) else ""
    if os.path.isabs(argv0) and os.path.basename(argv0) == "hermes":
        seen.append(argv0)
    if sys.executable and os.path.isabs(sys.executable):
        seen.append(os.path.join(os.path.dirname(sys.executable), "hermes"))
    home = os.path.expanduser("~")
    seen += [os.path.join(home, ".hermes", "hermes-agent", "venv", "bin", "hermes"),
             os.path.join(home, ".local", "bin", "hermes")]
    return next((c for c in seen if _usable(c)), None)


class BehaviourTestMixin:
    """`hermes twin test`: run botport's behaviour test on one twin and keep the result on its entry."""

    def _battery_path(self, pid: str) -> Path:
        return self.central / "batteries" / f"{pid}.json"

    def behaviour_test(self, pid: str, battery: Any = None, from_export: Any = None) -> dict:
        pid = self.require_pair(pid)
        eng = self.engine_for(pid)
        if eng is self.demo or not hasattr(eng, "behaviour_test"):
            raise EngineError("unsupported", "The sample has no Hermes bot to test.",
                              "Twin a real Grok bot first: hermes twin quick \"NAME\"")
        entry = self._registry().get(pid) or {}
        profile = (entry.get("hermes") or {}).get("profile")
        if not isinstance(profile, str) or not profile:
            raise EngineError("unsupported", "This twin has no Hermes bot to test yet.")
        hermes = hermes_path()
        if not hermes:
            raise EngineError("not_found", "Hermes' own command (hermes) was not found next to this plugin's Python "
                              "or in ~/.hermes/hermes-agent/venv/bin or ~/.local/bin.",
                              "botport asks the twin's Hermes bot through it.")
        kept = self._battery_path(pid)
        if battery and from_export:
            raise EngineError("usage", "Give --battery or --from-export, not both.")
        if from_export:
            store.ensure_dir(kept.parent)
            eng.battery_init(_regular_file(from_export, "setup export"), str(kept))
            use = str(kept)
        elif battery:
            use = _regular_file(battery, "battery")
        elif kept.is_file():
            use = str(kept)
        else:
            raise EngineError("usage", "This twin has no test cases yet.",
                              "Make them once from the bot's setup export: hermes twin test \"NAME\" --from-export "
                              "FILE (or give your own: --battery FILE)")
        out = store.ensure_dir(self.central / "tests" / pid)
        data = eng.behaviour_test(profile, use, os.path.realpath(hermes), str(out))
        results = [r for r in (data.get("results") or []) if isinstance(r, dict)]
        total = data.get("total") if isinstance(data.get("total"), int) else len(results)
        passed = data.get("pass") if isinstance(data.get("pass"), int) else sum(1 for r in results if r.get("pass") is True)
        rec = {"at": now_iso(), "passed": max(0, min(passed, total)), "total": max(0, total),
               "failed": [str(r.get("id")) for r in results if r.get("pass") is not True][:FAILED_IDS_MAX]}
        with store.locked():
            reg = self._registry()
            if pid in reg:
                reg[pid]["test"] = rec
                self._save_registry(reg)
        self.invalidate()
        self.emit("behaviour_test", pid, {"passed": rec["passed"], "total": rec["total"]})
        shown = summary(rec) or {}
        shown["results"] = [{"id": safe.clean_name(r.get("id"), 80), "pass": r.get("pass") is True,
                             "why": safe.clean_summary("; ".join(w for w in (r.get("why") or []) if isinstance(w, str)),
                                                       160)} for r in results[:200]]
        return shown
