"""Twins reached through the owner's EXISTING Hermes Telegram bot (zero-touch issue 09). No BotFather step.

A new Telegram bot can only be made by a person in @BotFather, so the default is to reuse the Telegram bot one of
the owner's Hermes profiles already runs (the "gateway profile": its `.env` has TELEGRAM_BOT_TOKEN and
TELEGRAM_ALLOWED_USERS, the way Hermes attaches Telegram to a profile). The plugin's `/twin` command in that chat
then routes to a named twin:

    /twin to acme-support Any open tickets?   one message to the twin called acme-support
    /twin use acme-support                     this chat now talks to acme-support ...
    /twin say Any open tickets?                ... so say goes to acme-support
    /twin use off                              back to the gateway profile's own bot

Rules, all checked on every message, failing closed:
- Only on the gateway profile: the profile handling the message (Hermes' `source.profile` when it multiplexes
  profiles, else this process's own Hermes folder) must be the one the route was turned on for. Another profile
  that loads this plugin and runs its own Telegram bot does not serve the route.
- DM only (Hermes 0.22.7's Telegram adapter maps Telegram's "private" chat to `chat_type` "dm"; a group, channel
  or thread is refused), and only from the owner's numeric Telegram user id, taken
  from the gateway profile's TELEGRAM_ALLOWED_USERS when the route is turned on (exactly one id, or the owner names
  theirs with --owner). Hermes' own allow-list check still runs first; this is a second, narrower one.
- Only twins the owner put on the route. Telegram can never start setup, sync or a route change (the existing
  /twin rule: messaging chats are read-only for everything else).
- The twin's turn runs with every approval answered "deny": nothing a Telegram message asks for can run a tool
  that needs approval.
- Tokens are referenced, never copied: the plugin only looks whether TELEGRAM_BOT_TOKEN is set in the gateway
  profile's `.env` (or its `secrets.command` is set); the value is never read into a variable, logged or written.
  The twin profiles get no token and keep their own Telegram off.

If no profile has a Telegram bot, `hermes twin telegram on` FAILs up front and names BotFather as the one human
step. A per-twin bot stays possible when the owner asks (TELEGRAM_BOT_TOKEN in that twin's own `.env`, or by
`secrets.command`), never by default.

`hermes twin telegram on` makes the gateway profile load this plugin (it links the plugin folder into that
profile and enables it with `hermes -p PROFILE plugins enable`, twin/auto_setup.py `reach`) and names that change
in its PASS line. A twin whose safe profile defaults were not applied is refused.
"""
from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path
from typing import Any, Callable, Optional

from . import safe, store
from .model import valid_id

STATE_FILE = "telegram-routes.json"
TOKEN_KEY = "TELEGRAM_BOT_TOKEN"
USERS_KEY = "TELEGRAM_ALLOWED_USERS"
REPLY_CAP = 3500  # under Telegram's 4096-character message limit
TURN_LIMIT_S = 180
MESSAGING_PLATFORM = "telegram"
_ID_RE = re.compile(r"^\d{1,20}$")
ENV_CAP = 256 * 1024

NO_BOT = ("FAIL: telegram: no Hermes profile has a Telegram bot yet. The one human step: make one in Telegram with "
          "@BotFather (/newbot), then attach it to a Hermes profile (hermes -p PROFILE gateway setup); then run "
          "hermes twin telegram on again")


# ---- reading a profile's Telegram setup (keys only) --------------------------------------------------------------
def env_keys(home: Path) -> dict:
    """{key: has a value} for TELEGRAM_* keys in <home>/.env, plus the TELEGRAM_ALLOWED_USERS value (ids are not
    secret). The token's value is looked at only to see that it is not empty; it is never returned."""
    p = home / ".env"
    out: dict = {"token": False, "users": "", "secrets_command": False}
    try:
        if p.is_symlink() or not p.is_file():
            return out
        with open(p, "rb") as fh:
            raw = fh.read(ENV_CAP).decode("utf-8", "replace")
    except OSError:
        return out
    for ln in raw.splitlines():
        ln = ln.strip()
        if ln.startswith("export "):
            ln = ln[7:].lstrip()
        if "=" not in ln or ln.startswith("#"):
            continue
        k, _, v = ln.partition("=")
        k = k.strip()
        if k == TOKEN_KEY:
            out["token"] = bool(v.strip().strip("'\""))
        elif k == USERS_KEY:
            out["users"] = v.strip().strip("'\"")
    del raw
    return out


def _cfg(home: Path) -> dict:
    from . import profile_safety
    try:
        return profile_safety.load_config(home)
    except Exception:
        return {}


def telegram_of(profile: str) -> Optional[dict]:
    """{"profile", "users": [ids], "by": "env"|"secrets.command"} when this profile runs a Telegram bot, else None."""
    try:
        home = store.profile_home(profile)
    except ValueError:
        return None
    keys = env_keys(home)
    cfg = _cfg(home)
    tg = ((cfg.get("platforms") or {}).get("telegram") or {}) if isinstance(cfg.get("platforms"), dict) else {}
    if tg.get("enabled") is False:
        return None
    sc = (cfg.get("secrets") or {}).get("command") if isinstance(cfg.get("secrets"), dict) else None
    if not keys["token"] and not sc:
        return None
    users = [u.strip() for u in re.split(r"[,\s]+", keys["users"]) if u.strip()]
    return {"profile": profile, "users": [u for u in users if _ID_RE.match(u)],
            "by": "env" if keys["token"] else "secrets.command"}


def profiles(root: Optional[Path] = None) -> list:
    root = root or store.hermes_root()
    names = ["default"]
    pdir = root / "profiles"
    if pdir.is_dir():
        names += sorted(p.name for p in pdir.iterdir() if p.is_dir() and valid_id(p.name))
    return names


def find_gateway(via: Optional[str] = None, twin_profiles: tuple = ()) -> dict:
    """The profile whose Telegram bot the twins ride on. `via` names it; otherwise default first, then the sticky
    profile, then the only other one. Twin profiles are never chosen."""
    if via:
        got = telegram_of(via)
        if got is None:
            raise ValueError(f"profile {safe.clean_name(via, 60)} has no Telegram bot")
        return got
    found = [g for g in (telegram_of(p) for p in profiles()) if g and g["profile"] not in twin_profiles]
    if not found:
        raise LookupError(NO_BOT)
    from .auto_setup import active_profile
    for want in ("default", active_profile()):
        hit = next((g for g in found if g["profile"] == want), None)
        if hit:
            return hit
    if len(found) == 1:
        return found[0]
    raise ValueError(f"{len(found)} profiles have a Telegram bot; say which with --via PROFILE")


# ---- the route record --------------------------------------------------------------------------------------------
def _path() -> Path:
    return store.central_dir() / STATE_FILE


def state() -> dict:
    data = store.read_json(_path(), {})
    return data if isinstance(data, dict) else {}


def _save(data: dict) -> None:
    store.atomic_write_json(_path(), data)


def _chat_key(chat_id: Any) -> str:
    return hashlib.sha256(f"tg:{chat_id}".encode()).hexdigest()[:16]


def turn_on(twins: list, via: Optional[str] = None, owner: Optional[str] = None,
            twin_profiles: tuple = (), reach: Optional[Callable[[str], str]] = None) -> str:
    """Put these twins (profile names) on the owner's existing Telegram bot. Returns the PASS/FAIL line."""
    try:
        gw = find_gateway(via, twin_profiles)
    except LookupError as exc:
        return str(exc)
    except ValueError as exc:
        return f"FAIL: telegram: {exc}"
    ids = gw["users"]
    if owner is not None:
        if not _ID_RE.match(str(owner)) or str(owner) not in ids:
            return "FAIL: telegram: --owner must be one of the numeric ids the gateway profile already allows"
        ids = [str(owner)]
    if len(ids) != 1:
        return (f"FAIL: telegram: profile {gw['profile']} allows {len(ids)} Telegram users; the route takes only "
                "the owner: give --owner ID (one of them)" if ids else
                f"FAIL: telegram: profile {gw['profile']} has no numeric {USERS_KEY}; the route stays off")
    if not twins:
        return "FAIL: telegram: no twin named"
    from . import profile_safety
    unsafe = [t for t in twins if profile_safety.is_unsafe(t)]
    if unsafe:
        return (f"FAIL: telegram: safe profile defaults were not applied to {safe.clean_name(unsafe[0], 60)}; run "
                "hermes twin safety TWIN --apply first")
    how = reach(gw["profile"]) if reach is not None else None  # the gateway profile must load this plugin
    data = state()
    data.update(gateway=gw["profile"], owner_ids=ids, token_by=gw["by"], at=time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                                                           time.gmtime()))
    routed = dict(data.get("twins") or {})
    for t in twins:
        routed[t] = True
    data["twins"] = routed
    data.setdefault("current", {})
    _save(data)
    names = ", ".join(sorted(routed))
    changed = (f"; plugin linked and enabled in profile {gw['profile']}" if how == "linked" else "")
    return (f"PASS: telegram: twins {names} reachable through the existing Hermes Telegram bot of profile "
            f"{gw['profile']} (/twin to NAME TEXT), owner only, DM only, no new token{changed}")


def turn_off(twins: Optional[list] = None) -> str:
    data = state()
    if not data:
        return "PASS: telegram: route already off"
    if twins:
        for t in twins:
            (data.get("twins") or {}).pop(t, None)
    else:
        data["twins"] = {}
    data["current"] = {k: v for k, v in (data.get("current") or {}).items() if v in (data.get("twins") or {})}
    _save(data)
    left = sorted(data.get("twins") or {})
    return "PASS: telegram: route " + (f"now {', '.join(left)}" if left else "off for every twin")


def forget(profile: str) -> bool:
    """A removed twin leaves the route (and any chat's current choice of it). -> whether it was on the route."""
    data = state()
    if profile not in (data.get("twins") or {}):
        return False
    turn_off([profile])
    return True


def describe() -> str:
    data = state()
    twins = sorted(data.get("twins") or {})
    if not twins:
        return "Telegram route: off (hermes twin telegram on TWIN)"
    return (f"Telegram route: on via profile {data.get('gateway')} for {', '.join(twins)}; owner only, DM only; "
            f"token by {data.get('token_by', 'env')} reference")


# ---- the /twin handler on a messaging chat -----------------------------------------------------------------------
_turn: Optional[Callable] = None  # tests put a fake here: (profile, text) -> {"ok", "reply"} | None


def _run_turn(profile: str, text: str) -> Optional[dict]:
    if _turn is not None:
        return _turn(profile, text)
    from . import tasks_turn
    return tasks_turn.run_turn(profile, text, should_stop=lambda: None, on_wait=lambda q: None,
                               answer=lambda: "deny", limit_s=TURN_LIMIT_S)


def _unsafe(profile: str) -> bool:
    from . import profile_safety
    try:
        return profile_safety.is_unsafe(profile)
    except Exception:
        return True


ROUTE_WORDS = ("to", "use", "say")


def is_route(raw_args: str) -> bool:
    w = (raw_args or "").strip().split(None, 1)
    return bool(w) and w[0].lower() in ROUTE_WORDS


def _src(source: Any, key: str) -> Any:
    return source.get(key) if isinstance(source, dict) else getattr(source, key, None)


def handling_profile(source: Any = None) -> Optional[str]:
    """The Hermes profile handling this message: `source.profile` (Hermes 0.22.7 SessionSource, set when one
    gateway process multiplexes profiles), else the profile of this process's own Hermes folder ("default" for the
    main folder). None when it cannot be told (fail closed)."""
    import os
    p = _src(source, "profile") if source is not None else None
    if isinstance(p, str) and p.strip():
        return p.strip()
    from . import config
    try:
        root = os.path.realpath(str(store.hermes_root()))
        own = os.path.realpath(os.path.expanduser(config._own_home() or root))
    except Exception:
        return None
    if own == root:
        return "default"
    parent, name = os.path.split(own)
    return name if parent == os.path.join(root, "profiles") and valid_id(name) else None


def guard(platform: Any, source: Any, profile: Optional[str] = None) -> Optional[str]:
    """None when this message may use the route, else the refusal text (said without detail). `profile`: the
    profile handling the message (default: handling_profile(source))."""
    data = state()
    if not data.get("twins"):
        return "The Telegram route to twins is off."
    plat = getattr(platform, "value", platform)
    if not isinstance(plat, str) or plat.strip().lower() != MESSAGING_PLATFORM:
        return "The route to twins is for the owner's Telegram chat."
    if (profile or handling_profile(source)) != data.get("gateway"):
        return "The route to twins answers only on the Telegram bot it was turned on for."
    if source is None or str(_src(source, "chat_type") or "").lower() != "dm":
        return "Twins answer in a direct chat only."
    uid = str(_src(source, "user_id") or "")
    if not _ID_RE.match(uid) or uid not in [str(x) for x in data.get("owner_ids") or []]:
        return "Not allowed."
    return None


def handle(raw_args: str, platform: Any = None, source: Any = None, resolve: Optional[Callable] = None,
           profile: Optional[str] = None) -> str:
    """`/twin to NAME TEXT`, `/twin use NAME|off`, `/twin say TEXT` on Telegram. `resolve(name) -> profile`;
    `profile`: the profile handling the message (default: handling_profile(source))."""
    why = guard(platform, source, profile)
    if why:
        return why
    data = state()
    routed = data.get("twins") or {}
    word, _, rest = (raw_args or "").strip().partition(" ")
    word, rest = word.lower(), rest.strip()
    chat = _chat_key(_src(source, "chat_id"))

    def _named(name: str) -> Optional[str]:
        try:
            prof = resolve(name) if resolve else name
        except Exception:
            return None
        return prof if prof in routed and not _unsafe(prof) else None

    if word == "use":
        cur = dict(data.get("current") or {})
        if rest.lower() in ("off", "none", ""):
            cur.pop(chat, None)
            data["current"] = cur
            _save(data)
            return "This chat talks to the main bot again."
        prof = _named(rest)
        if not prof:
            return "That twin is not on the Telegram route."
        cur[chat] = prof
        data["current"] = cur
        _save(data)
        return f"This chat now talks to the twin {safe.clean_name(prof, 60)}: /twin say TEXT"
    if word == "to":
        name, _, text = rest.partition(" ")
        prof = _named(name)
        if not prof:
            return "That twin is not on the Telegram route."
    else:  # say
        prof = (data.get("current") or {}).get(chat)
        text = rest
        if prof not in routed or _unsafe(prof):
            return "Choose a twin first: /twin use NAME"
    text = text.strip()
    if not text:
        return "Say something after the twin's name."
    res = _run_turn(prof, text[:8000])
    if not res or not res.get("ok"):
        return f"The twin {safe.clean_name(prof, 60)} could not answer just now."
    reply = str(res.get("reply") or "").strip() or "(no reply)"
    from .model_check import redact  # twin#66: no private address, local name or port reaches Telegram
    return f"[{safe.clean_name(prof, 60)}] " + safe.cap(redact(reply), REPLY_CAP)
