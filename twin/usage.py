"""The weekly Grok usage line for `hermes twin status` and the Twins page (read through the engine: 0 turns).

"Grok this week: 42% used (resets Mon); twin used 7 turns". `botport grok usage` is a read, never a bot turn. The
twin's own count is botport's turn ledger (`botport_turns_week`, botport with the weekly budget); an older botport
has none and the line says so. Past the owner's budget (`grok_turn_budget_week`, else botport's
`usage_budget_week`) a warning follows. Without the engine (no botport, the port closed) the line is left out and a
note says why.

An engine read auto-opens the Grok app's debug port when it is closed (botport's launch policy), so a read that
found the port closed puts the app back with `botport grok restore` afterwards, as chat sync does; a port someone
else opened is left alone. A good reading is kept for CACHE_S, so repeated `status` calls do not reopen the port.
"""
from __future__ import annotations

import contextlib
import time
from datetime import datetime
from typing import Any, Optional

from . import config, grok_engine as ge, one_prompt, safe, store
from .model import parse_iso


CACHE = "grok-usage.json"
CACHE_S = 15 * 60


def _cache_path():
    return one_prompt._folder() / CACHE


def _cached(now: float) -> Optional[dict]:
    try:
        rec = store.read_json(_cache_path(), {}) if _cache_path().is_file() else {}
    except Exception:  # noqa: BLE001  (a broken cache is just a miss)
        return None
    if not isinstance(rec, dict) or not isinstance(rec.get("data"), dict):
        return None
    at = rec.get("at")
    if not isinstance(at, (int, float)) or isinstance(at, bool) or not 0 <= now - at < CACHE_S:
        return None
    return rec["data"]


def _keep(data: dict, now: float) -> None:
    with contextlib.suppress(Exception):
        store.atomic_write_json(_cache_path(), {"at": now, "data": data})


def _port_open(eng: ge.GrokEngine) -> bool:
    """True when the port is open (or cannot be told: then restore is not ours to run)."""
    st = eng.status()
    if st.exit != ge.DONE or not isinstance(st.data, dict) or "port_open" not in st.data:
        return True
    return bool(st.data.get("port_open"))


def _int(v: Any) -> Optional[int]:
    return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0 else None


def _day(resets_at: Any) -> str:
    when = parse_iso(resets_at) if isinstance(resets_at, str) else None
    if when is None and isinstance(resets_at, (int, float)) and not isinstance(resets_at, bool):
        ts = resets_at / 1000 if resets_at > 1e11 else resets_at
        when = datetime.fromtimestamp(ts).astimezone()
    return when.astimezone().strftime("%a") if when else "unknown"


def describe(data: dict) -> dict:
    """{"line", "warning"?} from a usage answer."""
    pct = data.get("percent_used")
    pct_s = f"{round(float(pct))}%" if isinstance(pct, (int, float)) and not isinstance(pct, bool) else "?%"
    turns = _int(data.get("botport_turns_week"))
    line = (f"Grok this week: {pct_s} used (resets {_day(data.get('resets_at'))}); "
            + (f"twin used {turns} turn{'' if turns == 1 else 's'}" if turns is not None
               else "twin's turns not counted by this botport"))
    out: dict = {"line": line, "percent_used": pct, "turns": turns}
    budget = _int(config.get("grok_turn_budget_week")) or _int(data.get("usage_budget_week")) or 0
    if budget and turns is not None and turns >= budget:
        out["warning"] = (f"twin used {turns} Grok turns this week, past your budget of {budget} "
                          "(grok_turn_budget_week): skill sync, routines and exports spend turns")
    return out


def read(svc: Any, eng: Optional[ge.GrokEngine] = None, now: Optional[float] = None) -> dict:
    """-> {"ok", "line"} or {"ok": False, "note"}. Never raises; never a bot turn; never leaves a port it opened."""
    now = time.time() if now is None else now
    hit = _cached(now)
    if hit is not None:
        return {"ok": True, **describe(hit)}
    opened = False
    try:
        eng = eng or ge.from_service(svc)
        opened = not _port_open(eng)
        try:
            res = eng.usage()
        finally:
            if opened:  # this read opened the port: put the app back (a reused port belongs to its opener)
                with contextlib.suppress(Exception):
                    eng.restore()
    except ge.Unavailable as exc:
        return {"ok": False, "note": f"Grok usage not shown: {safe.clean_summary(str(exc), 200)}."}
    except Exception as exc:  # noqa: BLE001  (status never fails over this line)
        return {"ok": False, "note": f"Grok usage not shown: {type(exc).__name__}."}
    if res.exit != ge.DONE or not isinstance(res.data, dict) or "percent_used" not in res.data:
        why = res.proof.removeprefix("FAIL: ") if res.proof else ge.EXIT_WORDS.get(res.exit, "no answer")
        return {"ok": False, "note": f"Grok usage not shown: the engine could not read it "
                                     f"({safe.clean_summary(why, 200)})."}
    _keep({k: res.data.get(k) for k in ("percent_used", "resets_at", "botport_turns_week", "usage_budget_week")},
          now)
    return {"ok": True, **describe(res.data)}
