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

import contextlib
import json
import os
import stat
import sys
import time
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

from . import botlock, safe, store
from .engine import TEST_TIMEOUT_S, EngineError
from .model import now_iso

FAILED_IDS_MAX = 20
BATTERY_CAP = 1024 * 1024


# Cases whose pass depends on the model choosing a tool, not on the twin's content. Live 16 Nov the sandbox model
# sometimes answered `live-skills` ("Which skills can you use right now?") from the skill index Hermes puts in the
# system prompt (`<available_skills>`, prompt_builder.build_skills_system_prompt) instead of calling skills_list /
# skill_view, so the case read "expected skills_list/skill_view" and the import rolled back. The case stays as strict
# (a tool call is still required); such a case is retried once, and only when every failed case is one of them.
# Memory cases too (audit 16 Nov): on a slow local model a memory case once failed in under 5 s with no tool call (the
# memory skill was not loaded) and passed on every later run, so the data was there.
MODEL_FLAKY_FAMILIES = frozenset({"live", "memory"})


def model_flaky(result: dict) -> bool:
    return result.get("family") in MODEL_FLAKY_FAMILIES or str(result.get("id", "")).startswith(("live-", "memory-"))


# The budget of one `botport test` call. botport asks each case in turn (a pause of the battery's gap_s between
# them); a case on a slow local model can take minutes. The per-case budget is scaled from how long the twin's
# model takes for a one-word answer (measured once per run), between a floor and a ceiling; the whole call gets at
# least cases x per-case budget (+ gaps + slack), never less than the old fixed TEST_TIMEOUT_S.
PER_CASE_FLOOR_S = 180.0
PER_CASE_MAX_S = 900.0
FIRST_TOKEN_FACTOR = 30.0  # a case is a few tool turns, each at least one first answer
PROBE_TIMEOUT_S = 120.0
CALL_SLACK_S = 60.0
LOCK_WAIT_S = 3 * 3600.0  # another test on the same model: wait for it (its own budget is what it may take)


def per_case_budget(first_token_s: Optional[float]) -> float:
    if not isinstance(first_token_s, (int, float)) or first_token_s <= 0:
        return PER_CASE_FLOOR_S
    return max(PER_CASE_FLOOR_S, min(PER_CASE_MAX_S, FIRST_TOKEN_FACTOR * float(first_token_s)))


def call_budget(cases: int, gap_s: float, per_case_s: float) -> float:
    """The whole `botport test` call: never less than cases x per-case budget."""
    return max(TEST_TIMEOUT_S, max(1, cases) * (per_case_s + max(0.0, gap_s)) + CALL_SLACK_S)


def battery_shape(path: str) -> tuple[int, float]:
    """(number of cases incl. the gateway turn, gap_s) of a battery file; (6, 3) when it cannot be read."""
    try:
        with open(path, "rb") as f:
            doc = json.loads(f.read(BATTERY_CAP).decode("utf-8"))
        cases = doc.get("cases") if isinstance(doc, dict) else None
        n = (len(cases) if isinstance(cases, list) else 0) + (1 if isinstance(doc.get("gateway"), dict) else 0)
        gap = doc.get("gap_s", 3)
        return (n or 6), float(gap) if isinstance(gap, (int, float)) and not isinstance(gap, bool) else 3.0
    except (OSError, ValueError, AttributeError, UnicodeDecodeError):
        return 6, 3.0


def model_endpoint(profile: str) -> str:
    """Where the profile's model runs: its config.yaml `model.base_url` (else the provider, else "default"). Two
    tests on one local model slow each other down past their budgets, so they take turns per endpoint."""
    from . import hermes_side as hs
    from .fleet_profiles import profile_dir
    try:
        text = hs._read_below_root(profile_dir(profile) / "config.yaml", hs.CONFIG_CAP)
        doc = hs._yaml_load(text) if text else None
    except Exception:
        doc = None
    m = doc.get("model") if isinstance(doc, dict) else None
    if isinstance(m, dict):
        for key in ("base_url", "provider"):
            v = m.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip().rstrip("/").casefold()
    return "default"


@contextlib.contextmanager
def one_test_at_a_time(profile: str, say: Optional[Callable[[str], None]] = None,
              wait_s: float = LOCK_WAIT_S) -> Iterator[None]:
    """One behaviour test at a time per model endpoint and per profile (always taken in that order)."""
    names = [f"behaviour-test endpoint:{model_endpoint(profile)}", f"behaviour-test profile:{profile}"]
    with contextlib.ExitStack() as stack:
        for name in names:
            try:
                stack.enter_context(botlock.held(name, wait=False))
            except botlock.Busy:
                if say:
                    say("Another behaviour test is running on this model; this one waits for it to finish…")
                try:
                    stack.enter_context(botlock.held(name, wait=True, timeout=wait_s))
                except botlock.Busy:
                    raise EngineError("busy", "Another behaviour test is running on this model.",
                                      "Try again when it has finished.")
        yield


def _wall(r: dict) -> Optional[float]:
    w = r.get("wall_s")
    return round(float(w), 1) if isinstance(w, (int, float)) and not isinstance(w, bool) and w >= 0 else None


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
    windows = os.name == "nt"
    name = "hermes.exe" if windows else "hermes"  # (Windows: the venv's Scripts\hermes.exe launcher)
    seen = []
    argv0 = sys.argv[0] if sys.argv and isinstance(sys.argv[0], str) else ""
    if os.path.isabs(argv0) and os.path.basename(argv0).lower() in (("hermes", "hermes.exe") if windows else ("hermes",)):
        seen.append(argv0)
    if sys.executable and os.path.isabs(sys.executable):
        seen.append(os.path.join(os.path.dirname(sys.executable), name))
    if windows:  # Hermes' Windows installer puts it in <HERMES_HOME>\bin
        from . import store
        seen.append(os.path.join(str(store.hermes_root()), "bin", name))
    else:
        home = os.path.expanduser("~")
        seen += [os.path.join(home, ".hermes", "hermes-agent", "venv", "bin", name),
                 os.path.join(home, ".local", "bin", name)]
    return next((c for c in seen if _usable(c)), None)


class BehaviourTestMixin:
    """`hermes twin test`: run botport's behaviour test on one twin and keep the result on its entry."""

    def _battery_path(self, pid: str) -> Path:
        return self.central / "batteries" / f"{pid}.json"

    def _first_token_s(self, hermes: str, profile: str) -> Optional[float]:
        """Seconds the twin's model takes for a one-word answer (`hermes -p P -z`), None when it gave none."""
        from .engine import WHAT_HERMES, run_capped
        t0 = time.monotonic()
        try:
            rc, _o, _e, _over = run_capped([hermes, "-p", profile, "-z", "Reply with the single word: ok"],
                                           PROBE_TIMEOUT_S, what=WHAT_HERMES)
        except EngineError:
            return None
        return time.monotonic() - t0 if rc == 0 else None

    def behaviour_test(self, pid: str, battery: Any = None, from_export: Any = None,
                       say: Optional[Callable[[str], None]] = None) -> dict:
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
        with one_test_at_a_time(profile, say):
            return self._run_test(pid, eng, profile, use, os.path.realpath(hermes), str(out))

    def _run_test(self, pid: str, eng: Any, profile: str, use: str, hermes: str, out: str) -> dict:
        cases, gap = battery_shape(use)
        first = self._first_token_s(hermes, profile)
        per_case = per_case_budget(first)
        data = eng.behaviour_test(profile, use, hermes, out, timeout=call_budget(cases, gap, per_case))
        results = [r for r in (data.get("results") or []) if isinstance(r, dict)]
        total = data.get("total") if isinstance(data.get("total"), int) else len(results)
        passed = data.get("pass") if isinstance(data.get("pass"), int) else sum(1 for r in results if r.get("pass") is True)
        failed = [r for r in results if r.get("pass") is not True]
        retried: list = []
        if failed and all(model_flaky(r) for r in failed):
            # Each such case once more, scored exactly as before: a case passes only if its retry passes.
            retried = [str(r.get("id")) for r in failed]
            again = eng.behaviour_test(profile, use, hermes, out, only=retried,
                                       timeout=call_budget(len(retried), gap, per_case))
            redo = {str(r.get("id")): r for r in (again.get("results") or []) if isinstance(r, dict)}
            results = [redo.get(str(r.get("id")), r) if r.get("pass") is not True else r for r in results]
            passed = sum(1 for r in results if r.get("pass") is True)
            total = len(results)
        rec = {"at": now_iso(), "passed": max(0, min(passed, total)), "total": max(0, total),
               "failed": [str(r.get("id")) for r in results if r.get("pass") is not True][:FAILED_IDS_MAX]}
        if retried:
            rec["retried"] = retried[:FAILED_IDS_MAX]
        with store.locked():
            reg = self._registry()
            if pid in reg:
                reg[pid]["test"] = rec
                self._save_registry(reg)
        self.invalidate()
        self.emit("behaviour_test", pid, {"passed": rec["passed"], "total": rec["total"]})
        shown = summary(rec) or {}
        if retried:
            shown["retried"] = rec["retried"]
        shown["budget"] = {"per_case_s": round(per_case), "first_answer_s": None if first is None else round(first, 1)}
        shown["results"] = [{"id": safe.clean_name(r.get("id"), 80), "pass": r.get("pass") is True,
                             "why": safe.clean_summary("; ".join(w for w in (r.get("why") or []) if isinstance(w, str)),
                                                       160), "wall_s": _wall(r)} for r in results[:200]]
        return shown
