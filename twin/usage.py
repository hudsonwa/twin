"""The weekly Grok usage line for `hermes twin status` and the Twins page (read through the engine: 0 turns).

"Grok this week: 42% used (resets Mon); twin used 7 turns". `botport grok usage` is a read, never a bot turn. The
twin's own count is botport's turn ledger (`botport_turns_week`, botport with the weekly budget); an older botport
has none and the line says so. Past the owner's budget (`grok_turn_budget_week`, else botport's
`usage_budget_week`) a warning follows. Without the engine (no botport, the port closed) the line is left out and a
note says why.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from . import config, grok_engine as ge, safe
from .model import parse_iso


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


def read(svc: Any, eng: Optional[ge.GrokEngine] = None) -> dict:
    """-> {"ok", "line"} or {"ok": False, "note"}. Never raises; never a bot turn."""
    try:
        eng = eng or ge.from_service(svc)
        res = eng.usage()
    except ge.Unavailable as exc:
        return {"ok": False, "note": f"Grok usage not shown: {safe.clean_summary(str(exc), 200)}."}
    except Exception as exc:  # noqa: BLE001  (status never fails over this line)
        return {"ok": False, "note": f"Grok usage not shown: {type(exc).__name__}."}
    if res.exit != ge.DONE or not isinstance(res.data, dict) or "percent_used" not in res.data:
        why = res.proof.removeprefix("FAIL: ") if res.proof else ge.EXIT_WORDS.get(res.exit, "no answer")
        return {"ok": False, "note": f"Grok usage not shown: the engine could not read it "
                                     f"({safe.clean_summary(why, 200)})."}
    return {"ok": True, **describe(res.data)}
