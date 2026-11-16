"""Opt-in: each twin gets its own same-named Telegram bot, made with one owner tap through Telegram managed bots
(twin#68; design and open questions: docs/design/managed-bots.md, spike twin#67).

Off unless the owner sets `telegram_bot_per_twin: on`; with it off every entry point here returns a FAIL line
before any file, store or Bot API call is touched.

    hermes twin telegram bot TWIN       the gateway bot DMs the owner one "create bot" button (one tap)
    (managed_bot update arrives)        creator must be the owner; token goes straight into the OS secret store
    hermes twin stop TWIN               the twin's bot is turned off in its profile (deleting it is the owner's)

The token is never a return value, a log line, an exception text, a state field, a transcript line or a `.env`
value: `getManagedBotToken`'s answer is handed straight to `secret_ref.keep` inside one expression. The twin
profile gets `TELEGRAM_ALLOWED_USERS=<owner>` in its `.env` and the token by reference only (config.yaml
`secrets.command`, a command that prints it from the OS store for Hermes alone).

Every Bot API call goes through `Api(transport)`; tests pass a fake transport, so no test talks to Telegram.
"""
from __future__ import annotations

import json
import re
import secrets as _rnd
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Optional

from . import safe, secret_ref, store, tg_route

SETTING = "telegram_bot_per_twin"
STATE_FILE = "telegram-bots.json"
PENDING_S = 15 * 60
MIGRATE = "hermes gateway migrate"
TOKEN_REF_KEY = tg_route.TOKEN_KEY
_TOKENISH = re.compile(r"\d{5,}:[A-Za-z0-9_-]{8,}")
NOT_WIRED = (f"EXPERIMENTAL: {SETTING} is on, but it is not usable yet: nothing receives Telegram's answer after "
             "your tap, so no twin bot gets its token. Leave it off.")
OFF = f"FAIL: telegram bot: {SETTING} is off (set it on in the plugin settings to give each twin its own bot)"


class ApiError(Exception):
    """A Bot API call failed. The text is Telegram's description with anything token-shaped cut out."""


def scrub(text: Any) -> str:
    return _TOKENISH.sub("[token]", str(text))[:300]


# ---- the Bot API, through an injectable transport ----------------------------------------------------------------
Transport = Callable[[str, dict], dict]  # (method, params) -> Telegram's JSON answer {"ok", "result"|"description"}


def http_transport(token_of: Callable[[], Optional[str]]) -> Transport:
    """The real transport (the gateway bot's own token, read at call time and never kept). Unused by tests."""
    def call(method: str, params: dict) -> dict:
        tok = token_of()
        if not tok:
            raise ApiError("the gateway bot's token could not be read")
        body = json.dumps(params).encode("utf-8")
        req = urllib.request.Request(f"https://api.telegram.org/bot{tok}/{urllib.parse.quote(method)}", data=body,
                                     headers={"Content-Type": "application/json"})
        del tok
        try:
            with urllib.request.urlopen(req, timeout=20) as r:  # noqa: S310  (fixed https host)
                return json.loads(r.read(1 << 20).decode("utf-8"))
        except Exception as exc:  # never re-raised: its text can hold the URL, and the URL holds the token
            raise ApiError(f"{method}: {type(exc).__name__}") from None
    return call


def _gateway_token() -> Optional[str]:
    """The gateway bot's own token from its profile's `.env`, for one Bot API call (never kept or returned up)."""
    try:
        gw = tg_route.find_gateway(tg_route.state().get("gateway") or None)
        raw = (store.profile_home(gw["profile"]) / ".env").read_text(encoding="utf-8")[: tg_route.ENV_CAP]
    except Exception:
        return None
    for ln in raw.splitlines():
        k, _, v = ln.strip().removeprefix("export ").partition("=")
        if k.strip() == tg_route.TOKEN_KEY and v.strip().strip("'\""):
            return v.strip().strip("'\"")
    return None


_transport: Optional[Transport] = None  # tests put a fake Bot API here; nothing in tests reaches Telegram


def default_api() -> "Api":
    return Api(_transport or http_transport(_gateway_token))


class Api:
    def __init__(self, transport: Transport) -> None:
        self._t = transport

    def call(self, method: str, **params: Any) -> Any:
        try:
            got = self._t(method, params)
        except ApiError:
            raise
        except Exception as exc:
            raise ApiError(f"{method}: {scrub(type(exc).__name__)}") from None
        if not isinstance(got, dict) or not got.get("ok"):
            raise ApiError(f"{method}: {scrub((got or {}).get('description') if isinstance(got, dict) else 'no answer')}")
        return got.get("result")


# ---- state (no token field exists) -------------------------------------------------------------------------------
def _path() -> Path:
    return store.central_dir() / STATE_FILE


def state() -> dict:
    d = store.read_json(_path(), {})
    d = d if isinstance(d, dict) else {}
    d.setdefault("pending", [])
    d.setdefault("bots", {})
    return d


def _save(d: dict) -> None:
    store.atomic_write_json(_path(), {"pending": d.get("pending") or [], "bots": d.get("bots") or {}})


def secret_name(profile: str) -> str:
    return ("TWIN_TG_" + re.sub(r"[^A-Z0-9]", "_", profile.upper()))[:64]


def suggested(profile: str, title: Optional[str] = None) -> tuple:
    """(display name, username) suggested to Telegram; the owner may edit both in their client."""
    name = (title or " ".join(w.capitalize() for w in re.split(r"[-_]+", profile) if w))[:64] or "Twin"
    user = re.sub(r"[^a-z0-9_]", "_", profile.lower())
    return name, (user[: 32 - len("_twin_bot")] + "_twin_bot")


# ---- checks shared by every step ---------------------------------------------------------------------------------
def enabled() -> bool:
    from . import config
    return config._bool(config.settings().get(SETTING), False)


def multiplexing(root: Optional[Path] = None) -> bool:
    """Does one host gateway serve every profile (Hermes `gateway.multiplex_profiles`)? Per-profile gateways: no."""
    from . import profile_safety
    try:
        cfg = profile_safety.load_config(root or store.hermes_root())
    except Exception:
        return False
    gw = cfg.get("gateway") if isinstance(cfg, dict) else None
    return isinstance(gw, dict) and gw.get("multiplex_profiles") is True


def _owner(gw: dict) -> Optional[str]:
    ids = [str(x) for x in gw.get("users") or []]
    return ids[0] if len(ids) == 1 else None


# ---- 1. the one owner tap ----------------------------------------------------------------------------------------
def request(profile: str, api: Api, title: Optional[str] = None, twin_profiles: tuple = (),
            now: Optional[float] = None) -> str:
    """Send the owner's DM one managed-bot request button for this twin. -> PASS/FAIL line (no token involved)."""
    if not enabled():
        return OFF
    who = safe.clean_name(profile, 60)
    if tg_route._unsafe(profile):
        return f"FAIL: telegram bot: safe profile defaults were not applied to {who}; run hermes twin safety {who} --apply"
    if not multiplexing():
        return (f"FAIL: telegram bot: this host runs one gateway per profile; a twin's bot needs the single host "
                f"gateway: run {MIGRATE} yourself first (the gateway was not changed)")
    try:
        # the same gateway the Bot API calls go through (_gateway_token: the route's own, else the usual pick)
        gw = tg_route.find_gateway(tg_route.state().get("gateway") or None, twin_profiles)
    except LookupError as exc:
        return str(exc).replace("telegram:", "telegram bot:", 1)
    except ValueError as exc:
        return f"FAIL: telegram bot: {exc}"
    owner = _owner(gw)
    if owner is None:
        return f"FAIL: telegram bot: profile {gw['profile']} must allow exactly one Telegram user (the owner)"
    why = secret_ref.store_reason()
    if why:
        return f"FAIL: telegram bot: {why}; the token is never kept in a plain .env, so nothing was asked"
    try:
        me = api.call("getMe") or {}
        if me.get("can_manage_bots") is not True:
            return (f"FAIL: telegram bot: enable Bot Management Mode for @{safe.clean_name(me.get('username'), 40)} "
                    "in BotFather's Mini App (one-time owner step), then run this again")
        name, user = suggested(profile, title)
        rid = _rnd.randbelow(2 ** 31 - 1) + 1
        now = time.time() if now is None else now
        d = state()
        d["pending"] = [p for p in d["pending"] if p.get("expires", 0) > now and p.get("twin") != profile]
        d["pending"].append({"twin": profile, "owner_id": owner, "request_id": rid, "username": user,
                             "created": now, "expires": now + PENDING_S})
        _save(d)
        api.call("sendMessage", chat_id=int(owner), text=f"Give the twin {name} its own Telegram bot: one tap below.",
                 reply_markup={"keyboard": [[{"text": f"Create {name}", "request_managed_bot": {
                     "request_id": rid, "suggested_name": name, "suggested_username": user}}]],
                     "one_time_keyboard": True, "resize_keyboard": True})
    except ApiError as exc:
        return f"FAIL: telegram bot: {exc}"
    link = (f"https://t.me/newbot/{safe.clean_name(me.get('username'), 40)}/{user}?"
            + urllib.parse.urlencode({"name": name}))
    return (f"PASS: telegram bot: asked the owner in Telegram to create {name} (@{user}); one tap there, or open "
            f"{link}; the request lasts 15 minutes")


# ---- 2. the managed_bot update -----------------------------------------------------------------------------------
def on_managed_bot(update: dict, api: Api, check_model: Optional[Callable[[str], dict]] = None,
                   now: Optional[float] = None) -> Optional[str]:
    """Handle one `managed_bot` update. -> a PASS/FAIL line for the owner's terminal, or None when the update is
    ignored (no reply, no token call): not on, not from the owner, nothing pending."""
    if not enabled():
        return None
    mb = update.get("managed_bot") if isinstance(update, dict) else None
    if not isinstance(mb, dict):
        return None
    creator = str(((mb.get("user") or {}).get("id")) or "")
    bot = mb.get("bot") or {}
    bot_id = bot.get("id")
    if not isinstance(bot_id, int) or not creator.isdigit():
        return None
    now = time.time() if now is None else now
    d = state()
    known = next((p for p, b in d["bots"].items() if b.get("bot_id") == bot_id), None)
    if known is not None:  # a token or owner change of a bot we already hold
        b = d["bots"][known]
        if creator != str(b.get("owner_id")):
            stop(known, reason="its owner changed in Telegram")
            return f"FAIL: telegram bot: {safe.clean_name(known, 60)}'s bot changed owner; its Telegram is off"
        try:
            secret_ref.keep(b["secret"], api.call("getManagedBotToken", user_id=bot_id), kind="telegram", twin=known,
                            item="telegram bot")
        except (ApiError, secret_ref.NoStore, ValueError) as exc:
            stop(known, reason="its token could not be read again")
            return f"FAIL: telegram bot: {scrub(exc)}; {safe.clean_name(known, 60)}'s Telegram is off"
        return f"PASS: telegram bot: {safe.clean_name(known, 60)}'s new token is kept by reference"
    live = [p for p in d["pending"] if p.get("expires", 0) > now and str(p.get("owner_id")) == creator]
    if len(live) != 1:  # a non-owner, no request, an expired one, or two at once (cannot tell which)
        if len(live) > 1:
            return "FAIL: telegram bot: two twin bot requests were open at once; run hermes twin telegram bot TWIN again"
        return None
    p = live[0]
    profile = p["twin"]
    name = secret_name(profile)
    try:
        # the token's only path: Telegram's answer -> the OS store, inside this one expression
        secret_ref.keep(name, api.call("getManagedBotToken", user_id=bot_id), kind="telegram", twin=profile,
                        item="telegram bot")
    except (ApiError, secret_ref.NoStore, ValueError) as exc:
        return f"FAIL: telegram bot: {scrub(exc)}; the request stays open for one more try"
    try:
        api.call("setManagedBotAccessSettings", user_id=bot_id, is_access_restricted=True)
    except ApiError:
        pass  # our own allow-list below still holds; said in the line
    username = safe.clean_name(bot.get("username"), 40)
    wired = wire_profile(profile, creator, name)
    d = state()
    d["pending"] = [x for x in d["pending"] if x.get("request_id") != p["request_id"]]
    d["bots"][profile] = {"bot_id": bot_id, "username": username, "owner_id": creator, "secret": name, "on": wired,
                          "since": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))}
    _save(d)
    if not wired:
        return (f"FAIL: telegram bot: token kept, but {safe.clean_name(profile, 60)}'s profile already has its own "
                "Telegram token or secrets.command; nothing there was changed")
    line = (f"PASS: telegram bot: {safe.clean_name(profile, 60)} answers as @{username}, owner only, DM only, "
            "approvals denied; token by reference (the gateway bot can read it too: that is how managed bots work)")
    if check_model is not None:
        try:
            res = check_model(profile) or {}
            line += "; " + str(res.get("line") or "model check: no answer")
        except Exception as exc:  # noqa: BLE001
            line += f"; model check: {type(exc).__name__}"
    return line


def token_command(profile: str) -> str:
    return f"hermes twin telegram token {profile}"


def wire_profile(profile: str, owner: str, name: str) -> bool:
    """The twin profile's `.env` gets the owner id and a comment naming the reference (no token line); config.yaml
    gets `secrets.command`, Telegram on, the strict tool list on Telegram and manual approvals."""
    from . import profile_safety as ps
    home = store.profile_home(profile)
    keys = tg_route.env_keys(home)
    cfg = ps.load_config(home)
    sc = cfg.get("secrets") if isinstance(cfg.get("secrets"), dict) else {}
    if keys["token"] or (sc.get("command") and sc.get("command") != token_command(profile)):
        return False
    secret_ref.remove_env(home, tg_route.USERS_KEY)
    path = home / ".env"
    lines = [ln for ln in secret_ref._env_lines(path) if not ln.startswith(f"# {TOKEN_REF_KEY} by secrets.command")]
    lines += [f"{tg_route.USERS_KEY}={owner}",
              f"# {TOKEN_REF_KEY} by secrets.command (OS secret store name {name}); no value in this file"]
    store.atomic_write_text(path, "\n".join(lines) + "\n")
    path.chmod(0o600)
    cfg.setdefault("secrets", {})["command"] = token_command(profile)
    cfg.setdefault("platforms", {}).setdefault("telegram", {})["enabled"] = True
    cfg.setdefault("platform_toolsets", {})["telegram"] = list(ps.STRICT_ALLOWED)
    cfg.setdefault("approvals", {})["mode"] = "manual"
    _write_blessed(profile, home, cfg)
    return True


def _write_blessed(profile: str, home: Path, cfg: dict) -> None:
    """Write config.yaml and record it as the safe defaults' own write (this step owns those keys now)."""
    import hashlib
    from . import profile_safety as ps
    p = ps.write_config(home, cfg)
    if isinstance(ps.records().get(profile), dict):
        ps.record(profile, wrote_sha=hashlib.sha256(p.read_bytes()).hexdigest(), wrote_owned=ps.owned_sha(ps.load_config(home)))


def has_bot(profile: str) -> bool:
    b = state()["bots"].get(profile)
    return bool(b and b.get("on"))


# ---- 3. the twin's own bot: who gets an answer -------------------------------------------------------------------
def guard(profile: str, source: Any) -> bool:
    """May this message on the twin's own bot get a turn? Owner id, private chat, Telegram only. No reply else."""
    b = state()["bots"].get(profile)
    if not b or not b.get("on"):
        return False
    src = tg_route._src
    if str(getattr(src(source, "platform"), "value", src(source, "platform")) or "").lower() != "telegram":
        return False
    if str(src(source, "chat_type") or "").lower() not in ("dm", "private"):
        return False
    return str(src(source, "user_id") or "") == str(b.get("owner_id"))


def on_bot_update(profile: str, update: dict, api: Api, turn: Callable[[str, str], dict]) -> bool:
    """One message update on the twin's own bot -> whether a reply was sent. A non-owner, a group, a channel, an
    edited or service message: nothing is sent and no turn runs."""
    msg = update.get("message") if isinstance(update, dict) else None
    if not isinstance(msg, dict) or not isinstance(msg.get("text"), str):
        return False
    chat = msg.get("chat") or {}
    source = {"platform": "telegram", "chat_type": chat.get("type"), "user_id": (msg.get("from") or {}).get("id")}
    if chat.get("id") != (msg.get("from") or {}).get("id") or not guard(profile, source):
        return False
    res = turn(profile, msg["text"][:8000]) or {}
    from .model_check import redact
    reply = safe.cap(redact(str(res.get("reply") or "").strip() or "(no reply)"), tg_route.REPLY_CAP)
    api.call("sendMessage", chat_id=chat["id"], text=reply)
    return True


# ---- 4. stop -----------------------------------------------------------------------------------------------------
def stop(profile: str, reason: str = "") -> Optional[str]:
    """Turn the twin's bot off in its profile and drop the stored token. Deleting the bot in Telegram is suggested,
    never done. -> the line, or None when this twin had no bot."""
    d = state()
    b = d["bots"].get(profile)
    d["pending"] = [p for p in d["pending"] if p.get("twin") != profile]
    if not b:
        _save(d)
        return None
    try:
        from . import profile_safety as ps
        home = store.profile_home(profile)
        if home.is_dir():
            cfg = ps.load_config(home)
            if isinstance(cfg.get("secrets"), dict) and cfg["secrets"].get("command") == token_command(profile):
                cfg["secrets"].pop("command", None)
                if not cfg["secrets"]:
                    cfg.pop("secrets")
            cfg.setdefault("platforms", {}).setdefault("telegram", {})["enabled"] = False
            _write_blessed(profile, home, cfg)
            path = home / ".env"
            lines = [ln for ln in secret_ref._env_lines(path) if not ln.startswith(f"# {TOKEN_REF_KEY} by secrets.command")]
            if lines != secret_ref._env_lines(path):
                store.atomic_write_text(path, "\n".join(lines) + ("\n" if lines else ""))
    except Exception:  # noqa: BLE001  (an odd config never keeps the token: it is forgotten below in any case)
        pass
    secret_ref.forget(b.get("secret") or secret_name(profile))
    b["on"] = False
    d["bots"][profile] = b
    _save(d)
    return (f"{safe.clean_name(profile, 60)}'s Telegram bot @{b.get('username')} is off"
            + (f" ({reason})" if reason else "") + "; to delete it, open @BotFather in Telegram yourself")


def print_token(profile: str, out: Any = None) -> int:
    """`secrets.command` for Hermes: prints TELEGRAM_BOT_TOKEN=<value> to a pipe only (never to a terminal)."""
    out = out or sys.stdout
    if getattr(out, "isatty", lambda: False)() or not has_bot(profile):
        return 1
    v = secret_ref.value_of(state()["bots"][profile]["secret"])
    if not v:
        return 1
    out.write(f"{TOKEN_REF_KEY}={v}\n")
    return 0
