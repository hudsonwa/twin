"""twin#66: `hermes twin check-model TWIN`, the post-create check that a twin answers on the model its profile is set
to, in Hermes (a CLI turn) and in Telegram (the existing route, twin/tg_route.py); and the endpoint redaction every
Telegram-bound text goes through.

The check sends one fixed message per channel, MESSAGE, and compares each reply against the profile's own
config.yaml (`model.default`/`model.model`, `model.provider`, `model.base_url`) instead of trusting the model's
self-report: a channel passes when its reply names the configured model id. The Telegram leg runs the twin's turn
the same way the route does (every approval answered "deny") and only when the twin is on the route; its text goes,
redacted, to the owner's DM only (the one owner id the route was turned on with), through `sender(chat_id, text)`.
No sender is built in: the plugin never reads a bot token, so without one the Telegram leg checks the reply and
says it was not posted.

Redaction (Telegram is a third-party cloud): a private address never leaves this computer. A URL becomes either its
public hostname (no port, no path) or "custom endpoint on your network"; private IPs (RFC 1918, CGNAT/tailnet
100.64.0.0/10, loopback, link-local, IPv6 ULA and link-local), names under .local/.lan/.internal/.home.arpa/
.localhost/.ts.net, bare hostnames and ports are taken out. The Hermes (GUI/CLI) side may show the full URL.
"""
from __future__ import annotations

import ipaddress
import re
import urllib.parse
from pathlib import Path
from typing import Any, Callable, Optional

MESSAGE = "Reply with the model and endpoint you are configured to use"
NETWORK_LABEL = "custom endpoint on your network"
PRIVATE_LABEL = "[private address]"
DEFAULT_LABEL = "the provider's default endpoint"
PRIVATE_SUFFIXES = (".local", ".lan", ".internal", ".home.arpa", ".localhost", ".ts.net", ".intranet", ".corp")
_CGNAT = ipaddress.ip_network("100.64.0.0/10")
_ULA = ipaddress.ip_network("fc00::/7")

Turn = Callable[[str, str], Optional[dict]]  # (profile, text) -> {"ok", "reply"} | None
Sender = Callable[[str, str], bool]  # (owner chat id, text) -> sent


# ---- redaction --------------------------------------------------------------------------------------------------
def private_ip(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(host.strip("[]").split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return bool(ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_unspecified
                or (ip.version == 4 and ip in _CGNAT) or (ip.version == 6 and ip in _ULA))


def public_host(host: Any) -> Optional[str]:
    """`host` (lower case, no port) when it is a public DNS name or public IP; None for anything private: a private
    or special IP, a bare hostname (no dot), or a name under a local/tailnet suffix."""
    if not isinstance(host, str):
        return None
    h = host.strip().strip("[]").rstrip(".").lower()
    if not h:
        return None
    try:
        ipaddress.ip_address(h.split("%", 1)[0])
        return None if private_ip(h) else h
    except ValueError:
        pass
    if "." not in h or h == "localhost" or any(h.endswith(s) for s in PRIVATE_SUFFIXES):
        return None
    if not re.fullmatch(r"[a-z0-9-]+(\.[a-z0-9-]+)+", h) or h.rsplit(".", 1)[1].isdigit():
        return None
    return h


def endpoint_label(base_url: Any) -> str:
    """What Telegram may show of an endpoint: the public hostname, else NETWORK_LABEL; DEFAULT_LABEL for none."""
    if not isinstance(base_url, str) or not base_url.strip():
        return DEFAULT_LABEL
    try:
        u = urllib.parse.urlsplit(base_url.strip() if "//" in base_url else "//" + base_url.strip())
        host = u.hostname
    except ValueError:
        host = None
    return public_host(host) or NETWORK_LABEL


_URL_RE = re.compile(r"\b[a-z][a-z0-9+.-]*://(?:[^\s/<>\"'`@]*@)?(?:\[[0-9a-f:.%\w]*\]|[^\s/:<>\"'`)\]]+)"
                     r"(?::\d*)?[^\s<>\"'`)\]]*", re.I)
_V6_RE = re.compile(r"\[?(?<![\w:])(?:[0-9a-f]{0,4}:){2,7}[0-9a-f]{0,4}(?:%\w+)?\]?(?![\w:])", re.I)
_V6_BRACKET_RE = re.compile(r"\[([0-9a-f:.]+(?:%\w+)?)\](?::\d{1,5})?", re.I)
_V4_RE = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])")
_HOSTPORT_RE = re.compile(r"(?<![\w.-])([a-z0-9](?:[a-z0-9.-]*[a-z0-9])?):(\d{1,5})(?![\w])", re.I)
_LOCALNAME_RE = re.compile(r"(?<![\w-])[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9-]+)*(?:"
                           + "|".join(re.escape(s) for s in PRIVATE_SUFFIXES) + r")\.?(?![\w-])", re.I)
_LOCALHOST_RE = re.compile(r"(?<![\w.-])localhost(?![\w-])", re.I)


def _v6(m: "re.Match[str]") -> str:
    s = m.group(0)
    core = s.strip("[]")
    try:
        ipaddress.ip_address(core.split("%", 1)[0])
    except ValueError:
        return s
    return PRIVATE_LABEL if private_ip(core) else s


def _v6_bracket(m: "re.Match[str]") -> str:
    core = m.group(1)
    try:
        ipaddress.ip_address(core.split("%", 1)[0])
    except ValueError:
        return m.group(0)
    return PRIVATE_LABEL if private_ip(core) else core


def _v4(m: "re.Match[str]") -> str:
    s = m.group(0)
    try:
        ipaddress.ip_address(s)
    except ValueError:
        return s
    return PRIVATE_LABEL if private_ip(s) else s


def _hostport(m: "re.Match[str]") -> str:
    host = m.group(1)
    if host.isdigit():  # a time like 10:30 or a ratio: not a host
        return m.group(0)
    return public_host(host) or NETWORK_LABEL


def redact(text: Any) -> str:
    """`text` as it may go to Telegram: every URL is its public hostname or NETWORK_LABEL; private IPs, local or
    tailnet names, localhost and ports are taken out. Public hostnames and everything else stay."""
    s = str(text or "")
    s = _URL_RE.sub(lambda m: endpoint_label(m.group(0)), s)
    s = _V6_BRACKET_RE.sub(_v6_bracket, s)
    s = _V6_RE.sub(_v6, s)
    s = _HOSTPORT_RE.sub(_hostport, s)
    s = _V4_RE.sub(_v4, s)
    s = _LOCALNAME_RE.sub(NETWORK_LABEL, s)
    s = _LOCALHOST_RE.sub(NETWORK_LABEL, s)
    return s


# ---- the profile's own settings ---------------------------------------------------------------------------------
def configured(profile: str) -> dict:
    """{"model", "provider", "base_url"} from the profile's config.yaml ("" for what is not set)."""
    from . import hermes_side as hs
    from .fleet_profiles import profile_dir
    try:
        text = hs._read_below_root(Path(profile_dir(profile)) / "config.yaml", hs.CONFIG_CAP)
        doc = hs._yaml_load(text) if text else None
    except Exception:
        doc = None
    m = doc.get("model") if isinstance(doc, dict) else None
    if isinstance(m, str):
        m = {"default": m}
    if not isinstance(m, dict):
        m = {}

    def _s(*keys: str) -> str:
        for k in keys:
            v = m.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return ""
    return {"model": _s("default", "model"), "provider": _s("provider"), "base_url": _s("base_url").rstrip("/")}


def names_model(reply: Any, model: str) -> bool:
    """The reply names the configured model id (case and the provider prefix of either side ignored)."""
    if not isinstance(reply, str) or not model:
        return False
    r = reply.casefold()
    want = model.casefold()
    return want in r or want.rsplit("/", 1)[-1] in r


# ---- the check -------------------------------------------------------------------------------------------------
def _default_turn(profile: str, text: str) -> Optional[dict]:
    from . import tasks_turn
    return tasks_turn.run_turn(profile, text, should_stop=lambda: None, on_wait=lambda q: None,
                               answer=lambda: "deny", limit_s=180)


def _leg(turn: Turn, profile: str, model: str) -> dict:
    try:
        res = turn(profile, MESSAGE)
    except Exception:
        res = None
    if not res or not res.get("ok"):
        return {"ok": False, "reply": "", "why": "silent"}
    reply = str(res.get("reply") or "").strip()
    if not reply:
        return {"ok": False, "reply": "", "why": "silent"}
    return {"ok": names_model(reply, model), "reply": reply, "why": "" if names_model(reply, model) else "wrong"}


def check(profile: str, turn: Optional[Turn] = None, tg_turn: Optional[Turn] = None,
          sender: Optional[Sender] = None) -> dict:
    """-> {"ok", "line" (Hermes side, may show the URL), "telegram_line" (redacted), "hermes", "telegram"}.
    One MESSAGE per channel. The Telegram leg runs only when the twin is on the Telegram route."""
    from . import safe, tg_route
    cfg = configured(profile)
    shown = safe.clean_name(profile, 60)
    model, provider = cfg["model"], cfg["provider"] or "default provider"
    if not model:
        line = f"FAIL: check-model {shown}: no model is set in the twin's config.yaml"
        return {"ok": False, "line": line, "telegram_line": redact(line), "hermes": None, "telegram": None}
    hermes = _leg(turn or _default_turn, profile, model)
    data = tg_route.state()
    on_route = profile in (data.get("twins") or {})
    telegram: Optional[dict] = None
    if on_route:
        telegram = _leg(tg_turn or tg_route._run_turn, profile, model)
        owners = [str(x) for x in data.get("owner_ids") or []]
        telegram["posted"] = False
        if sender is not None and len(owners) == 1:  # the owner's DM only, never a group or another user
            body = redact(f"[{shown}] {telegram['reply'] or '(no reply)'}")
            try:
                telegram["posted"] = bool(sender(owners[0], safe.cap(body, tg_route.REPLY_CAP)))
            except Exception:
                telegram["posted"] = False
    bad = [n for n, leg in (("Hermes", hermes), ("Telegram", telegram)) if leg is not None and not leg["ok"]]
    ok = not bad
    full = f"{provider} {model} at {cfg['base_url'] or DEFAULT_LABEL}"
    tg_where = f"{provider} {model} at {endpoint_label(cfg['base_url'])}"

    def _why(n: str, leg: Optional[dict]) -> str:
        if leg is None:
            return f"{n}: not on the Telegram route (hermes twin telegram on {shown})"
        if leg["ok"]:
            return f"{n}: named the model" + ("" if n == "Hermes" or leg.get("posted") else " (not posted: no sender)")
        return f"{n}: {'silent' if leg['why'] == 'silent' else 'named another model'}"
    tail = "; ".join(_why(n, leg) for n, leg in (("Hermes", hermes), ("Telegram", telegram)))
    head = "PASS" if ok else "FAIL"
    wrong = "" if ok else f" ({', '.join(bad)} wrong or silent)"
    line = f"{head}: check-model {shown}{wrong}: configured {full}; {tail}"
    tg_line = redact(f"{head}: check-model {shown}{wrong}: configured {tg_where}; {tail}")
    return {"ok": ok, "line": line, "telegram_line": tg_line, "hermes": hermes, "telegram": telegram,
            "configured": {"model": model, "provider": cfg["provider"], "endpoint": endpoint_label(cfg["base_url"])}}
