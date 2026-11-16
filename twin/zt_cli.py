"""CLI for the zero-touch pieces: `setup --auto` (twin/auto_setup.py), `telegram` (twin/tg_route.py) and
`safety` (twin/profile_safety.py). Each prints one PASS/FAIL line last."""
from __future__ import annotations

from typing import Any

from . import safe
from .engine import EngineError


def _svc():
    from .service import get_service
    return get_service()


def profile_of(svc: Any, pid: str) -> str:
    """The Hermes profile of one twin."""
    for p in svc.status().get("pairs", []):
        if p.get("pair_id") == pid:
            return str((p.get("hermes") or {}).get("profile") or pid)
    raise EngineError("no_twin", "That twin is not on this computer.")


def resolve_profile(svc: Any, name: str) -> str:
    from .cli import _resolve
    return profile_of(svc, _resolve(svc, name))


def twin_profiles(svc: Any) -> tuple:
    out = []
    for p in svc.status().get("pairs", []):
        prof = (p.get("hermes") or {}).get("profile")
        if prof and not (p.get("sample") or p.get("demo")):
            out.append(str(prof))
    return tuple(out)


def cmd_setup_auto(a: Any) -> int:
    from . import auto_setup
    if getattr(a, "install_line", False):
        print(auto_setup.install_line())
        return 0
    rc, line = auto_setup.run(_svc(), open_port=bool(getattr(a, "open_port", False)),
                              link_profile=bool(getattr(a, "link_profile", False)))
    print(line)
    return rc


def cmd_telegram(a: Any) -> int:
    from . import auto_setup, tg_route
    svc = _svc()
    action = a.action or "status"
    if action == "status":
        print(tg_route.describe())
        return 0
    names = list(a.twins or [])
    if action == "off":
        line = tg_route.turn_off([resolve_profile(svc, n) for n in names] if names else None)
    else:
        if getattr(a, "all", False):
            profs = list(twin_profiles(svc))
        else:
            profs = [resolve_profile(svc, n) for n in names]
        try:
            line = tg_route.turn_on(profs, via=a.via, owner=a.owner, twin_profiles=twin_profiles(svc),
                                    reach=lambda prof: auto_setup.reach(prof, twins=twin_profiles(svc)))
        except auto_setup.Stop as exc:
            line = f"FAIL: telegram: {exc}"
    print(line)
    return 0 if line.startswith("PASS") else 1


def cmd_safety(a: Any) -> int:
    from . import profile_safety as ps
    svc = _svc()
    profs = list(twin_profiles(svc)) if getattr(a, "all", False) else [
        resolve_profile(svc, a.twin) if a.twin else _only(svc)]
    rc = 0
    for prof in profs:
        if a.model_policy:
            ps.set_model_policy(prof, a.model_policy)
        if a.preset:
            ps.set_preset(prof, a.preset, allow=getattr(a, "allow", None) or ())
        elif a.apply:
            got = ps.apply_default(prof)
            if got["words"]:
                who = safe.clean_name(prof, 60)
                print(f"{who}: {got['preset']}; its text mentions: {', '.join(got['words'][:5])} (risky actions ask "
                      f"first; hermes twin safety {who} strict narrows it)")
        res = ps.check(prof)
        if res["ok"]:
            ps.clear_unsafe(prof)  # (an add whose defaults failed stays off until this passes)
        elif ps.is_unsafe(prof):
            res["problems"].insert(0, "safe defaults were never applied (run with --apply)")
        print(ps.line(prof, res))
        rc |= 0 if res["ok"] else 1
    return rc


def cmd_check_model(a: Any) -> int:
    """twin#66: one fixed message per channel (Hermes, and Telegram when the twin is on the route)."""
    from . import model_check
    svc = _svc()
    prof = resolve_profile(svc, a.twin) if a.twin else _only(svc)
    res = model_check.check(prof)
    if getattr(a, "json", False):
        import json
        print(json.dumps({k: res[k] for k in ("ok", "line", "telegram_line", "configured") if k in res},
                         ensure_ascii=False))
    else:
        print(res["line"])
    return 0 if res["ok"] else 1


def _only(svc: Any) -> str:
    from .cli import _one
    return profile_of(svc, _one(svc, None))


def setup(subs: Any) -> None:
    p = subs.add_parser("telegram", help="Reach twins through your existing Hermes Telegram bot (no BotFather)")
    p.add_argument("action", nargs="?", choices=("on", "off", "status"))
    p.add_argument("twins", nargs="*", metavar="TWIN")
    p.add_argument("--all", action="store_true", help="on: every twin")
    p.add_argument("--via", metavar="PROFILE", help="The Hermes profile whose Telegram bot to use")
    p.add_argument("--owner", metavar="ID", help="Your numeric Telegram user id, when the bot allows several")
    p = subs.add_parser("safety", help="A twin's tool preset (parity, strict, standard, open) and model "
                                         "policy")
    p.add_argument("twin", nargs="?", metavar="TWIN")
    p.add_argument("preset", nargs="?", choices=("parity", "strict", "standard", "open"),
                   help="Set this preset (your choice, kept); without it: check")
    p.add_argument("--allow", action="append", choices=("web", "x_search", "file", "image_gen", "mcp"),
                   metavar="TOOLSET", help="With standard: let the twin keep this toolset (web, x_search, file, "
                                           "image_gen, mcp: all its MCP servers); repeatable")
    p.add_argument("--apply", action="store_true", help="Apply the default chosen by rule (parity: what the Grok bot can do)")
    p.add_argument("--all", action="store_true", help="Every twin")
    p.add_argument("--model-policy", choices=("local", "any"), help="Record the model policy (default local)")


    p = subs.add_parser("check-model", help="Check the twin answers on its configured model, in Hermes and (when on "
                                            "the Telegram route) in Telegram; Telegram never sees a private address")
    p.add_argument("twin", nargs="?", metavar="TWIN")
    p.add_argument("--json", action="store_true")


def add_setup_flags(p: Any) -> None:
    p.add_argument("--auto", action="store_true",
                   help="No questions, no manual steps: fetch + verify the pinned botport, make hermes twin work "
                        "from any profile, check the Grok app's PATH, the engine and port (fast preset); one "
                        "PASS/FAIL line")
    p.add_argument("--open-port", action="store_true",
                   help="With --auto: open the Grok port now (restarts the Grok app); otherwise it opens on demand")
    p.add_argument("--link-profile", action="store_true",
                   help="With --auto: also add the plugin to the sticky profile (hermes -p) when it is not "
                        "default; off by default, since it gives that bot the twin tools")
    p.add_argument("--install-line", action="store_true",
                   help="Print the pinned one-line install for this plugin version")


HANDLERS = {"telegram": cmd_telegram, "safety": cmd_safety, "check-model": cmd_check_model}
