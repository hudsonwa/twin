"""`hermes twin quick` and `hermes twin test`: one twin, start to finish, then a check.

    hermes twin quick "Acme Support" [--model M] [--yes]   add, ask the bot for its setup export, wait for the
                                                           answer file in Downloads, import, finish, compare
    ... --from-file FILE | --stdin                         the export handed over directly (an agent, or the bot
                                                           itself through its shell): no paste, no wait
    hermes twin test "Acme Support" [--from-export FILE | --battery FILE]   botport's behaviour test

`quick` is the existing commands run in order (twin/cli.py: add, import-exports, finish, compare); it holds no
logic of its own beyond the order, the wait and the summary. Each step asks as it always does, unless --yes. Run
again at any time: a step that is done is skipped (the twin exists; its instructions are in). No model is called.

`test` asks the twin's Hermes bot (twin/behaviour.py), so each run costs what its chats cost; only on request.
"""
from __future__ import annotations

import argparse
import time
from typing import Any

from .engine import EngineError
from .model import ago

WAIT_MIN = 15          # minutes quick waits for the answer file, by default
WAIT_MAX = 120
POLL_S = 3.0
LOOKBACK_S = 3600      # an answer file saved up to an hour before quick started counts too


def _cli():
    from . import cli
    return cli


def _find(svc, name: str):
    """The twin of the bot called NAME, or None when it has none yet."""
    try:
        return _cli()._resolve(svc, name)
    except EngineError:
        return None


def _left(svc, pid: str) -> list:
    info = svc.batch_info([pid])
    for t in info.get("twins") or []:
        if isinstance(t, dict) and t.get("pair_id") == pid:
            return list(t.get("left") or [])
    return []


def _clock() -> float:
    return time.monotonic()


def _wait_for_export(svc, pid: str, minutes: int) -> bool:
    """Look in Downloads (and the sync bot's folder) until a setup export for this twin is there, or time is up.
    Nothing is imported here: `import-exports` does that, with its preview and question."""
    since = max(0.0, time.time() - LOOKBACK_S)
    deadline = _clock() + minutes * 60
    while True:
        res = svc.downloads_scan(since, [pid], False)
        waiting = res.get("waiting")
        if isinstance(waiting, list) and pid not in waiting:
            return True
        if _clock() >= deadline:
            return False
        time.sleep(POLL_S)


def _given_text(a):
    """The setup export given with --from-file FILE or --stdin (a grok-bot-export document), or None."""
    if getattr(a, "stdin", False):
        import sys
        text = sys.stdin.read(_cli().IMPORT_FILE_CAP + 1)
        if len(text) > _cli().IMPORT_FILE_CAP:
            raise EngineError("too_large", "That is too large to be a setup export.")
        return text
    if getattr(a, "from_file", None):
        return _cli()._read_export_file(a.from_file)
    return None


def _step(steps: list, label: str, rc: int) -> int:
    steps.append((label, rc == 0))
    return rc


def _summary(steps: list, name: str) -> int:
    ok = all(good for _l, good in steps)
    c = _cli()
    c._out("")
    for label, good in steps:
        c._out(f" {'✓' if good else '✗'} {label}")
    if ok:
        c._out(f"Behaviour test (asks the twin's model): hermes twin test \"{name}\" --from-export FILE")
    c._out(f"{'PASS' if ok else 'FAIL'}: quick setup of \"{name}\"")  # the last line, always: one verdict
    return 0 if ok else 1


def cmd_quick(a) -> int:
    if getattr(a, "all", False) or not a.name:  # every bot, one summary (twin/bulk.py)
        from . import bulk
        if not getattr(a, "all", False):
            raise EngineError("usage", 'Say which bot: hermes twin quick "Acme Support" (or --all).')
        return bulk.cmd_quick_all(a)
    c = _cli()
    from . import setup_export, tasks
    if tasks.asked_turn():  # (the chat turn of a request from another computer never changes a twin's setup)
        raise EngineError("refused", "A request from another computer cannot set up a twin.",
                          "Do it yourself, on the Twins page or in your own terminal.")
    name, yes, steps = a.name, bool(a.yes), []
    svc = c._svc()
    pid = _find(svc, name)
    if pid is None:
        rc = _step(steps, "twin added", c.cmd_add(argparse.Namespace(all=False, bot=[name], profile=a.profile,
                                                                     yes=yes)))
        pid = _find(svc, name) if rc == 0 else None
        if pid is None:
            return _summary(steps, name)
    else:
        steps.append(("twin added (it already had one)", True))
    given = _given_text(a)
    if given is not None:  # the bot's own export, handed over directly: no paste, no Downloads
        _step(steps, "setup export imported", c.import_text(svc, pid, given, argparse.Namespace(
            bot=None, show=bool(a.show), yes=yes)))
        if not steps[-1][1]:
            return _summary(steps, name)
    elif "instructions" in _left(svc, pid):
        c._out("")
        c._out(f"Paste this into the chat of \"{name}\" in Grok, and save the file it answers with to Downloads:")
        c._out("--- paste from the next line ---")
        c._out(setup_export.REQUEST.rstrip("\n"))
        c._out("--- up to the line above ---")
        c._out(f"Waiting for the file (up to {a.wait} min; Ctrl-C stops, and quick can be run again)…")
        if not _wait_for_export(svc, pid, a.wait):
            steps.append((f"no setup export arrived in {a.wait} min (run hermes twin quick again when it is "
                          "saved)", False))
            return _summary(steps, name)
        _step(steps, "setup export imported", c.cmd_import_exports(argparse.Namespace(
            folder=c.EXPORTS_DIR_HINT, twin=[name], show=bool(a.show), yes=yes)))
        if not steps[-1][1]:
            return _summary(steps, name)
    else:
        steps.append(("instructions already in", True))
    from . import botlock
    with botlock.for_pair(svc, pid):  # the twin's shared lock (botlock.py); import and switch take it too
        _step(steps, "model set", c.cmd_finish(argparse.Namespace(twins=[name], all=False, model=a.model,
                                                                 endpoint=a.endpoint, yes=yes)))
    c._out("")
    _step(steps, "compare with Grok", c.cmd_parity(argparse.Namespace(pair=name)))
    return _summary(steps, name)


def tested_words(t: Any) -> str:
    """" · test 5/6 ✗ 2 h ago" for a twin's row, or "" when it was never tested."""
    if not isinstance(t, dict) or not isinstance(t.get("total"), int):
        return ""
    return f" · test {t['passed']}/{t['total']} {'✓' if t.get('ok') else '✗'} {ago(t.get('at'))}"


def cmd_test(a) -> int:
    c = _cli()
    svc = c._svc()
    pid = c._one(svc, a.pair)
    c._out("Running botport's behaviour test: each case is a real chat with the twin's model…")
    res = svc.behaviour_test(pid, a.battery, a.from_export, say=c._out)
    retried = res.get("retried") or []
    c._out(f"Behaviour test of {c._call(c._twin_names(svc), pid)}: {res['passed']} of {res['total']} pass "
           f"{'✓' if res['ok'] else '✗'}" + (f" ({len(retried)} case(s) retried once: "
                                              f"{', '.join(retried)})" if retried else ""))
    rows = res.get("results") or []
    timed = not res["ok"]  # on a FAIL each case's wall time, to tell a slow model from a wrong answer
    for r in [r for r in rows if not r["pass"]] + [r for r in rows if r["pass"]]:
        wall = f" ({r['wall_s']} s)" if timed and r.get("wall_s") is not None else ""
        c._out(f" {'✓' if r['pass'] else '✗'} {r['id']}{wall}" + ("" if r["pass"] or not r["why"] else f": {r['why']}"))
    b = res.get("budget") or {}
    if timed and b.get("per_case_s"):
        c._out(f"Budget: {b['per_case_s']} s per case" + (f" (a one-word answer took {b['first_answer_s']} s)"
                                                         if b.get("first_answer_s") is not None else ""))
    return 0 if res["ok"] else 1


def _minutes(value: str) -> int:
    try:
        n = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("minutes, such as 15")
    if not 1 <= n <= WAIT_MAX:
        raise argparse.ArgumentTypeError(f"from 1 to {WAIT_MAX} minutes")
    return n


def setup(subs: Any, twin_type: Any, pid_type: Any) -> None:
    p = subs.add_parser("quick", help="One twin start to finish: add, import its setup export, set the model, "
                                      "compare")
    p.add_argument("name", nargs="?", type=twin_type, metavar="NAME", help="The Grok bot's name, in quotes")
    p.add_argument("--all", action="store_true", help="Every Grok bot, one after the other, with one summary")
    p.add_argument("--model", metavar="MODEL", help="The model for the twin (default: the one this Hermes uses)")
    p.add_argument("--endpoint", metavar="NAME", help="A model server already set up in this Hermes that serves MODEL")
    p.add_argument("--hermes-profile", dest="profile", type=pid_type, metavar="NAME",
                   help="Name of the twin's Hermes profile (default: from the bot's name)")
    p.add_argument("--wait", type=_minutes, default=WAIT_MIN, metavar="MIN",
                   help=f"How long to wait for the setup export in Downloads (default {WAIT_MIN})")
    p.add_argument("--show", action="store_true", help="Print the instructions and prompts before the import")
    p.add_argument("--yes", "-y", action="store_true", help="Do not ask")
    g = p.add_mutually_exclusive_group()  # the bot hands its own export over: no paste step, no Downloads wait
    g.add_argument("--from-file", metavar="FILE", help="The bot's setup export (grok-bot-export JSON) from this file")
    g.add_argument("--stdin", action="store_true", help="The bot's setup export (grok-bot-export JSON) on stdin")
    p = subs.add_parser("test", help="botport's behaviour test of a twin (asks its model; --from-export FILE once)")
    p.add_argument("pair", nargs="?", type=twin_type, metavar="TWIN",
                   help="The twin's name, in quotes (not needed with one twin)")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--from-export", metavar="FILE", help="Make the test cases from this setup export (kept)")
    g.add_argument("--battery", metavar="FILE", help="Your own battery file (botport's format)")


HANDLERS = {"quick": cmd_quick, "test": cmd_test}
