"""twin#75: restart the twins' own Hermes gateways after a setup or an update, and make sure each is running again.

A standalone twin profile can run its own gateway (its Telegram bot). After the plugin is updated, a running gateway
still has the old code loaded until it restarts. `hermes -p TWIN gateway restart` can take over 90 s, and when it is
interrupted it leaves the gateway stopped: the twin's Telegram bot goes silent and nothing says so.

So setup and update restart twin gateways only through `restart_running` here, which for each twin profile:
1. asks `hermes -p TWIN gateway status`; a gateway that was not running is left alone (never started by setup);
2. runs `hermes -p TWIN gateway restart` with its own time limit (a timeout is not the end: step 3 decides);
3. waits until `gateway status` says it is running again; if it does not within the wait, runs `gateway start`
   once and waits again;
4. reports it as restarted, or as offline (the PASS line names every offline twin and the command to start it).

Every Hermes call goes through an injectable runner, so tests never start or stop a real gateway.
"""
from __future__ import annotations

import re
import subprocess
import time
from typing import Any, Callable, Iterable, Optional

Run = Callable[[list, float], tuple]  # (argv, timeout) -> (rc, stdout, stderr)

RESTART_TIMEOUT_S = 180.0  # one `gateway restart` call (seen: over 90 s on a standalone twin profile)
START_TIMEOUT_S = 120.0
STATUS_TIMEOUT_S = 30.0
WAIT_S = 45.0              # how long a gateway may take to say it is running after restart/start
TOTAL_S = 180.0            # review rc052 #9: no new twin is restarted after this long; the rest are left as they were
POLL_S = 3.0
MIN_LEFT_S = 30.0          # review rc052 #9: with less time left than this, a twin is left as it was, not half-restarted
_NOT_RUNNING = ("not running", "stopped", "inactive", "not loaded", "no gateway", "dead", "failed")
# review rc052 #9: these count only as status words, never inside other text: "running, 0 failed" or
# "restarts: 2 failed" is a running gateway: a word counts when it is a whole word and not a count (after a number).
_NOT_RUNNING_RE = re.compile(r"(?<!\d )(?<!\d)\b(?:" + "|".join(re.escape(n) for n in _NOT_RUNNING) + r")\b")
_RUNNING_RE = re.compile(r"(?<!not )\brunning\b")


def says_running(text: str) -> bool:
    """Status words (already casefolded) say running, and no status word says otherwise."""
    return bool(_RUNNING_RE.search(text)) and not _NOT_RUNNING_RE.search(text)


def _run(argv: list, timeout: float) -> tuple:
    p = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout, check=False)
    return p.returncode, p.stdout, p.stderr


def _text(b: Any) -> str:
    return b.decode("utf-8", "replace") if isinstance(b, (bytes, bytearray)) else str(b or "")


def _bound(timeout: float, end: Optional[float], clock: Callable[[], float]) -> float:
    """review rc052 #9: a call's own limit, never past the overall deadline `end` (None = no deadline)."""
    return timeout if end is None else max(0.0, min(timeout, end - clock()))


def is_running(hermes: str, profile: str, run: Run = _run, timeout: float = STATUS_TIMEOUT_S) -> bool:
    """`hermes -p PROFILE gateway status`: running only when it exits 0 and its words say running (and not "not
    running", "stopped"...). A status that cannot be read counts as not running."""
    try:
        rc, out, err = run([hermes, "-p", profile, "gateway", "status"], timeout)
    except (OSError, subprocess.SubprocessError):
        return False
    words = (_text(out) + " " + _text(err)).casefold()
    return rc == 0 and says_running(words)


def _call(hermes: str, profile: str, verb: str, timeout: float, run: Run) -> None:
    try:
        run([hermes, "-p", profile, "gateway", verb], timeout)
    except (OSError, subprocess.SubprocessError):
        pass  # (a timeout or a failed call is judged by the status that follows, never by itself)


def _wait_running(hermes: str, profile: str, run: Run, wait_s: float, sleep: Callable[[float], None],
                  clock: Callable[[], float], deadline: Optional[float] = None) -> bool:
    end = clock() + wait_s
    if deadline is not None:
        end = min(end, deadline)
    while True:
        left = _bound(STATUS_TIMEOUT_S, deadline, clock)
        if left > 0 and is_running(hermes, profile, run, left):
            return True
        if clock() >= end:
            return False
        sleep(max(0.0, min(POLL_S, end - clock())))


def restart_one(hermes: str, profile: str, run: Run = _run, wait_s: float = WAIT_S,
                sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic,
                deadline: Optional[float] = None) -> dict:
    """Restart one running gateway and make sure it runs again. -> {"profile", "state": restarted|started|offline}
    `deadline` (a `clock()` value): every call and wait is cut to the time left, so nothing runs past it."""
    _call(hermes, profile, "restart", _bound(RESTART_TIMEOUT_S, deadline, clock), run)
    if _wait_running(hermes, profile, run, wait_s, sleep, clock, deadline):
        return {"profile": profile, "state": "restarted"}
    t = _bound(START_TIMEOUT_S, deadline, clock)
    if t <= 0:
        return {"profile": profile, "state": "offline"}
    _call(hermes, profile, "start", t, run)
    if _wait_running(hermes, profile, run, wait_s, sleep, clock, deadline):
        return {"profile": profile, "state": "started"}
    return {"profile": profile, "state": "offline"}


def restart_running(profiles: Iterable[str], hermes: Optional[str] = None, run: Run = _run, wait_s: float = WAIT_S,
                    sleep: Callable[[float], None] = time.sleep,
                    clock: Callable[[], float] = time.monotonic, total_s: float = TOTAL_S) -> dict:
    """Every twin gateway that was running before is restarted and running again, or named offline.
    Once `total_s` has passed, no further twin is touched (not checked, not stopped): those are named in
    "left" with the command to restart them. `total_s` is a hard ceiling: every status/restart/start call and wait
    is given only the time left, so the twin in progress when the cap passes is cut short (named offline if not
    running by then).
    -> {"restarted": [profiles], "offline": [profiles], "left": [profiles], "skipped": why-or-""}"""
    if hermes is None:
        from .behaviour import hermes_path
        hermes = hermes_path()
    if not hermes:
        return {"restarted": [], "offline": [], "left": [], "skipped": "Hermes' own command was not found"}
    restarted, offline, left = [], [], []
    end = clock() + max(0.0, float(total_s))
    for prof in dict.fromkeys(p for p in profiles if isinstance(p, str) and p and p != "default"):
        if left or end - clock() < min(MIN_LEFT_S, float(total_s)) or clock() >= end:
            left.append(prof)  # (time cap: left exactly as it was)
            continue
        if not is_running(hermes, prof, run, _bound(STATUS_TIMEOUT_S, end, clock)):
            continue  # (not running before: left as it is)
        got = restart_one(hermes, prof, run, wait_s, sleep, clock, deadline=end)
        (offline if got["state"] == "offline" else restarted).append(prof)
    return {"restarted": restarted, "offline": offline, "left": left, "skipped": ""}


def note(res: dict) -> str:
    """The PASS line's words: "" when no twin gateway was running; offline twins are always named."""
    if res.get("skipped"):
        return f"; twin gateways not restarted ({res['skipped']})"
    out = ""
    if res.get("restarted"):
        out += f"; twin gateways restarted and running: {', '.join(res['restarted'])}"
    if res.get("offline"):
        out += ("; OFFLINE twin gateway(s), Telegram silent: " + ", ".join(res["offline"])
                + " (start with: " + "; ".join(f"hermes -p {p} gateway start" for p in res["offline"]) + ")")
    if res.get("left"):
        out += ("; twin gateways NOT restarted (time cap reached, left as they were, may run the old version): "
                + ", ".join(res["left"]) + " (restart with: "
                + "; ".join(f"hermes -p {p} gateway restart" for p in res["left"]) + ")")
    return out


# ---- doctor (read-only): is every twin gateway running, with its Telegram connection up? -------------------------
_TG_DOWN = ("disconnected", "not connected", "error", "failed", "offline", "down", "stopped", "unauthorized",
            "invalid token", "conflict", "retrying")


def telegram_state(text: str) -> str:
    """From `gateway status` words: "up", "down", or "unknown" (status says nothing about Telegram)."""
    lines = [ln.casefold() for ln in text.splitlines() if "telegram" in ln.casefold()]
    if not lines:
        return "unknown"
    return "down" if any(b in ln for ln in lines for b in _TG_DOWN) else "up"


def check_one(hermes: str, profile: str, run: Optional[Run] = None) -> dict:
    """Read-only: one `gateway status` call; never starts, stops or restarts anything.
    -> {"profile", "running": bool, "telegram": up|down|unknown}"""
    run = run or _run
    try:
        rc, out, err = run([hermes, "-p", profile, "gateway", "status"], STATUS_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError):
        return {"profile": profile, "running": False, "telegram": "unknown"}
    text = _text(out) + "\n" + _text(err)
    words = text.casefold()
    # (the Telegram lines are judged on their own: "telegram: disconnected" must not make the gateway "stopped")
    head = "\n".join(ln for ln in words.splitlines() if "telegram" not in ln)
    running = rc == 0 and says_running(head)
    return {"profile": profile, "running": running, "telegram": telegram_state(text) if running else "down"}


def check_all(profiles: Iterable[str], hermes: Optional[str] = None, run: Optional[Run] = None) -> dict:
    """-> {"ok": [profiles], "offline": [{"profile", "why"}], "unknown_tg": [profiles], "skipped": why-or-""}"""
    profs = list(dict.fromkeys(p for p in profiles if isinstance(p, str) and p and p != "default"))
    if hermes is None and profs:
        from .behaviour import hermes_path
        hermes = hermes_path()
    if profs and not hermes:
        return {"ok": [], "offline": [], "unknown_tg": [], "skipped": "Hermes' own command was not found"}
    ok, offline, unknown = [], [], []
    for prof in profs:
        got = check_one(hermes, prof, run)
        if not got["running"]:
            offline.append({"profile": prof, "why": "gateway not running"})
        elif got["telegram"] == "down":
            offline.append({"profile": prof, "why": "Telegram not connected"})
        else:
            ok.append(prof)
            if got["telegram"] == "unknown":
                unknown.append(prof)
    return {"ok": ok, "offline": offline, "unknown_tg": unknown, "skipped": ""}


def doctor_line(res: dict) -> str:
    """The ONE PASS/FAIL line doctor ends with; every offline twin is named with the command that fixes it."""
    if res.get("skipped"):
        return f"FAIL twin gateways: not checked ({res['skipped']}); check with hermes -p TWIN gateway status"
    if res.get("offline"):
        names = ", ".join(f"{o['profile']} ({o['why']})" for o in res["offline"])
        fix = "; ".join(f"hermes -p {o['profile']} gateway restart" for o in res["offline"])
        return f"FAIL twin gateways: offline, Telegram silent: {names}. Fix: {fix}"
    if not res.get("ok"):
        return "PASS twin gateways: no twin profiles to check"
    line = f"PASS twin gateways: running with Telegram up: {', '.join(res['ok'])}"
    if res.get("unknown_tg"):
        line += f" (status did not report Telegram for: {', '.join(res['unknown_tg'])})"
    return line
