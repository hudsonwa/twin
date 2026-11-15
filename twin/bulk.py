"""Three single commands that end in one PASS/FAIL line, and the same three as library functions.

    hermes twin quick --all [--model M] [--yes]       `quick` for every Grok bot, one summary at the end
    hermes twin link-computer [--wait MIN]            sharing on, a link code, then a wait (bounded) until a computer
                                                      has used it
    hermes twin stop NAME --yes [--remove-data]       stop one twin, named; its full transcripts and What syncs
                                                      choices stay unless --remove-data

Each is the existing command run as it always is (quick_cli.cmd_quick, fleet's share and code, cli.cmd_remove); this
module only adds the loop, the wait and the verdict. The library functions (quick_all, link_computer, stop_twin)
return {"ok", "verdict", "lines"} for a Hermes model tool to call; none of them deletes data: stop_twin has no
remove-data choice (that stays in the owner's own terminal) and is a dry run unless confirm=True.
"""
from __future__ import annotations

import argparse
import io
import time
from contextlib import redirect_stdout
from typing import Any, Callable

from .engine import EngineError

LINK_WAIT_MIN = 10     # a link code lasts 10 minutes: waiting longer is waiting for nothing
POLL_S = 2.0


def _cli():
    from . import cli
    return cli


def _refuse_requests_turn(what: str) -> None:
    from . import tasks
    if tasks.asked_turn():  # (the chat turn of a request from another computer changes nothing here)
        raise EngineError("refused", f"A request from another computer cannot {what}.",
                          "Do it yourself, on the Twins page or in your own terminal.")


def _verdict(ok: bool, what: str) -> str:
    return f"{'PASS' if ok else 'FAIL'}: {what}"


# ---- quick --all -------------------------------------------------------------------------------------------------------
def bot_names(svc) -> list:
    """The names of the owner's real Grok bots (never the sample's), each once."""
    real, _sample = _cli()._roster(svc.grok_list())
    out: list = []
    for b in real:
        name = b.get("name")
        if isinstance(name, str) and name.strip() and name.lower() not in [n.lower() for n in out]:
            out.append(name)
    return out


def cmd_quick_all(a) -> int:
    from . import quick_cli
    c = _cli()
    _refuse_requests_turn("set up a twin")
    if getattr(a, "from_file", None) or getattr(a, "stdin", False):
        raise EngineError("usage", "--from-file and --stdin are one bot's export: use them with quick NAME.")
    names = bot_names(c._svc())
    if not names:
        c._out("No Grok bots found. Run hermes twin doctor to see why.")
        c._out(_verdict(False, "quick setup of every bot"))
        return 1
    results = []
    for name in names:
        c._out(f"=== {name} ===")
        try:
            rc = quick_cli.cmd_quick(argparse.Namespace(**{**vars(a), "name": name, "all": False}))
        except EngineError as exc:
            c._out(f"{exc.message}")
            rc = 1
        results.append((name, rc == 0))
    good = sum(1 for _n, ok in results if ok)
    c._out("")
    for name, ok in results:
        c._out(f" {'✓' if ok else '✗'} {name}")
    c._out(_verdict(good == len(results), f"quick setup of {good} of {len(results)} bots"))
    return 0 if good == len(results) else 1


# ---- link another computer ---------------------------------------------------------------------------------------------
def _followers() -> set:
    from . import fleet
    return set(((fleet.load().get("share") or {}).get("followers") or {}).keys())


def cmd_link_computer(a) -> int:
    c = _cli()
    _refuse_requests_turn("link a computer")
    svc = c._svc()
    before = _followers()
    f = svc.fleet()
    if f.get("role") == "follower":
        c._out("This computer follows another one: make the code on the computer with the Grok app.")
        c._out(_verdict(False, "link another computer"))
        return 1
    turned_on = not (f.get("share") or {}).get("on")
    if turned_on:
        svc.fleet_share(True)
    linked = False
    try:
        code = svc.fleet_code()["code"]
        c._out(f"Link code: {code['code']}   (one computer, 10 minutes; made {time.strftime('%H:%M')})")
        c._out(f"On the other computer:  hermes twin setup --link {code['code']} --yes")
        c._out("Both computers must be on the same private network. Keep this running while the other links.")
        minutes = int(getattr(a, "wait", LINK_WAIT_MIN) or LINK_WAIT_MIN)
        c._out(f"Waiting for the other computer (up to {minutes} min; Ctrl-C stops)…")
        deadline = time.monotonic() + minutes * 60
        while True:
            if _followers() - before:
                linked = True
                c._out(_verdict(True, "another computer is linked"))
                return 0
            if time.monotonic() >= deadline:
                c._out(_verdict(False, f"no computer used the code in {minutes} min (hermes twin link-computer "
                                       "makes a new one)" + ("; sharing is off again" if turned_on else "")))
                return 1
            time.sleep(POLL_S)
    finally:
        if turned_on and not linked:  # (timeout, Ctrl-C or an error: sharing goes back to off, as it was)
            svc.fleet_share(False)


# ---- stop one twin, named ----------------------------------------------------------------------------------------------
def cmd_stop(a) -> int:
    c = _cli()
    if not getattr(a, "pair", None):
        c._err('Say which twin to stop, by its bot\'s name: hermes twin stop "Acme Support"')
        c._out(_verdict(False, "stop a twin (no twin named)"))
        return 2
    _refuse_requests_turn("stop a twin")
    svc = c._svc()
    sample = c._resolve(svc, a.pair) in svc.demo.pair_ids()
    rc = c.cmd_remove(a)
    if not getattr(a, "dry_run", False) and rc == 0 and not sample:
        c._out("Kept: its full transcripts and What syncs choices." if not getattr(a, "remove_data", False)
               else "Its full transcripts and What syncs choices are deleted too.")
    what = f"stop \"{a.pair}\"" + (" (dry run)" if getattr(a, "dry_run", False) else "")
    c._out(_verdict(rc == 0, what))
    return rc


# ---- library functions for a Hermes model tool -------------------------------------------------------------------------
def _captured(fn: Callable[[Any], int], a) -> dict:
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            rc = fn(a)
    except EngineError as exc:
        buf.write(f"{exc.message}\n{_verdict(False, exc.code)}\n")
        rc = 1
    lines = [ln for ln in buf.getvalue().splitlines()]
    last = next((ln for ln in reversed(lines) if ln.startswith(("PASS:", "FAIL:"))), _verdict(rc == 0, "done"))
    return {"ok": rc == 0, "verdict": last, "lines": lines[-200:]}


def quick_all(model: Any = None, wait: int = 15) -> dict:
    """Every Grok bot gets a twin, start to finish (no question asked: the caller asked)."""
    return _captured(cmd_quick_all, argparse.Namespace(
        name=None, all=True, model=model, endpoint=None, profile=None, wait=int(wait), show=False, yes=True,
        from_file=None, stdin=False))


def link_computer(wait: int = LINK_WAIT_MIN) -> dict:
    """A link code for one more computer, and the wait until it has linked (at most WAIT minutes)."""
    return _captured(cmd_link_computer, argparse.Namespace(wait=max(1, min(int(wait), LINK_WAIT_MIN))))


def stop_twin(name: str, confirm: bool = False) -> dict:
    """Stop the twin of the bot called NAME. A dry run unless confirm=True; its data is always kept."""
    if not isinstance(name, str) or not name.strip():
        return {"ok": False, "verdict": _verdict(False, "stop a twin (no twin named)"), "lines": []}
    return _captured(cmd_stop, argparse.Namespace(pair=name.strip(), dry_run=not confirm, yes=bool(confirm),
                                                  remove_data=False))


def _minutes(value: str) -> int:
    try:
        n = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("minutes, such as 10")
    if not 1 <= n <= LINK_WAIT_MIN:
        raise argparse.ArgumentTypeError(f"from 1 to {LINK_WAIT_MIN} minutes")
    return n


def setup(subs: Any) -> None:
    p = subs.add_parser("link-computer", help="Link one more computer: prints a link code and waits until it is used")
    p.add_argument("--wait", type=_minutes, default=LINK_WAIT_MIN, metavar="MIN",
                   help=f"How long to wait for the other computer (default and most {LINK_WAIT_MIN})")


HANDLERS = {"link-computer": cmd_link_computer, "stop": cmd_stop, "remove": cmd_stop}
