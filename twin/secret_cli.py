"""`hermes twin secret list|set|forget|share|pull` and the route that brings a secret to the owner's own linked
computers (docs/SECRETS.md). Nothing here prints, logs or returns a value; the route carries values only inside
the sealed box of the link (xs_memory.seal), with a key of its own made from the link's key, and only for names
the owner shared --linked on the computer that shares."""
from __future__ import annotations

import getpass
import hashlib
import hmac
import logging
import sys
from typing import Any

from . import fleet, fleet_items, safe, secret_ref, xs_memory
from .osflags import is_terminal

log = logging.getLogger(__name__)

ROUTE = "/v1/xs/secrets"
ASK_CAP = 4096
MAX_SHARED = 100


def _key(link_key: bytes) -> bytes:
    """Secrets get a key of their own, so a memory box can never be read as a secrets box or the other way round."""
    return hmac.new(link_key, b"grok-bot-twin secrets\n", hashlib.sha256).digest()


# ---- the computer that shares ------------------------------------------------------------------------------------------
def answer() -> dict:
    """What a linked computer gets: the values of the names shared --linked here, and nothing else."""
    values = {}
    for name, rec in list(secret_ref.load().items())[:MAX_SHARED]:
        if rec["linked"]:
            v = secret_ref.value_of(name)
            if v is not None:
                values[name] = v
    return {"values": values}


def wire(asked: Any, body: dict) -> tuple:
    """`POST /v1/xs/secrets`: (status, object, signed) like every signed route."""
    from . import fleet_server as server
    if body.get("proto") != fleet.PROTO:
        return server._err(426, "version_mismatch") + (None,)
    again = server._replayed(asked, body)
    if again is not None:
        return again
    fst = fleet.load()
    f, key = asked.by(fst)
    if f is None:
        return server._unlinked(key, asked)
    signed = (key, asked.nonce)
    plain = xs_memory.unseal(_key(key), "ask", f["id"], "", body.get("seal"), ASK_CAP)
    if plain is None:
        return server._err(400, "bad_box") + (signed,)
    try:
        out = answer()
    except Exception:
        log.debug("grok-bot-twin: a secrets answer failed")  # (never the exception's text)
        out = {"values": {}, "busy": True}
    bind = str((body.get("seal") or {}).get("nonce"))
    return 200, {"schema": fleet.SCHEMA, "seal": xs_memory.seal(_key(key), "answer", f["id"], bind, out)}, signed


fleet_items.routes[ROUTE] = wire


# ---- a linked computer ------------------------------------------------------------------------------------------------
def keep_pulled(values: Any) -> int:
    """Keep what arrived in this computer's own OS store (raises NoStore when it has none). Returns how many."""
    n = 0
    for name, v in (values.items() if isinstance(values, dict) else ()):
        if isinstance(name, str) and secret_ref.NAME_RE.match(name) and isinstance(v, str):
            secret_ref.keep(name, v, "linked")
            n += 1
    return n


def pull() -> int:
    from . import fleet_follow as follow
    fst = fleet.load()
    ln = fst.get("link")
    if not isinstance(ln, dict) or not isinstance(ln.get("pass"), str):
        raise RuntimeError("This computer is not linked to another one.")
    secret_ref.backend()  # no store here: refuse before anything is asked
    mid = fst["machine"]["id"]
    key = _key(fleet.share_key(ln["pass"]))
    box = xs_memory.seal(key, "ask", mid, "", {"want": "linked"})
    try:
        status, obj, signed = follow._counted_request(ln, mid, ROUTE, {"proto": fleet.PROTO, "seal": box})
    except follow.Unreachable:
        raise RuntimeError("The computer that shares cannot be reached now.")
    if status == 404:
        raise RuntimeError("The computer that shares has an older Grok Bot Twin.")
    ans = xs_memory.unseal(key, "answer", mid, box["nonce"], obj.get("seal")) if status == 200 and signed else None
    if ans is None:
        raise RuntimeError("The answer could not be checked, so nothing was kept.")
    return keep_pulled(ans.get("values"))


# ---- terminal ---------------------------------------------------------------------------------------------------------
def _owner_terminal() -> bool:
    from .tasks_api import _owner_terminal as owner
    return owner()


def _read_value(a: Any) -> str:
    if a.stdin:
        return sys.stdin.readline().rstrip("\r\n")
    if not is_terminal(sys.stdin):
        raise ValueError("give the value in your own terminal, or with --stdin")
    return getpass.getpass(f"Value of {a.name} (not shown): ")


def _list(c: Any) -> int:
    why = secret_ref.store_reason()
    c._out(f"Store: {'none (' + why + ')' if why else secret_ref.backend().name}")
    names = secret_ref.load()
    if not names:
        c._out("No secrets kept by reference.")
    for name, rec in sorted(names.items()):
        where = ", ".join(f"{w['twin']} {w['item']}".strip() for w in rec["where"][:5]) or "set by hand"
        flags = [f for f, on in (("shared to Grok", rec["to_grok"]), ("linked computers", rec["linked"])) if on]
        c._out(f"{name}: {where}" + (f" [{'; '.join(flags)}]" if flags else ""))
    return 0


def _share(c: Any, a: Any) -> int:
    switch = "to_grok" if a.to_grok else "linked" if a.linked else None
    if switch is None:
        c._out("FAIL: say where: --to-grok or --linked")
        return 1
    on = not a.off
    if on and not _owner_terminal():
        c._out("FAIL: only you can share a secret, in your own terminal (a command a chat started cannot)")
        return 1
    if on and switch == "to_grok":
        c._out("Warning: " + secret_ref.TO_GROK_WARNING.format(name=a.name))
        if not a.yes and (not is_terminal(sys.stdin) or input("Type yes to share it: ").strip().lower() != "yes"):
            c._out("FAIL: not shared")
            return 1
    try:
        secret_ref.set_switch(a.name, switch, on)
    except KeyError:
        c._out(f"FAIL: no secret named {a.name}")
        return 1
    where = "the Grok bot" if switch == "to_grok" else "your linked computers"
    c._out(f"PASS: {a.name} {'is now shared with' if on else 'is no longer shared with'} {where}")
    return 0


def cmd_secret(a: Any) -> int:
    from . import cli as c
    name = getattr(a, "name", None)
    if a.action != "list" and a.action != "pull" and not (name and secret_ref.NAME_RE.match(name)):
        c._out("FAIL: name the secret (capital letters, digits and _), such as OPENAI_API_KEY")
        return 1
    try:
        if a.action == "list":
            return _list(c)
        if a.action == "set":
            secret_ref.keep(name, _read_value(a))
            c._out(f"PASS: {name} kept in {secret_ref.backend().name}")
        elif a.action == "forget":
            found = secret_ref.forget(name)
            c._out(f"PASS: {name} forgotten" if found else f"PASS: there was no secret named {name}")
        elif a.action == "share":
            return _share(c, a)
        else:
            c._out(f"PASS: {pull()} secret(s) kept from the computer that shares")
    except secret_ref.NoStore as e:
        c._out(f"FAIL: not kept: {e}. Grok Bot Twin never keeps a secret in a plain file.")
        return 1
    except (ValueError, RuntimeError) as e:
        c._out(f"FAIL: {safe.clean_summary(str(e), 200)}")
        return 1
    return 0


def setup(subs: Any) -> None:
    p = subs.add_parser("secret", help="Secrets kept by reference in this computer's OS store (never shown)")
    p.add_argument("action", choices=["list", "set", "forget", "share", "pull"])
    p.add_argument("name", nargs="?", metavar="NAME", help="The secret's name, such as OPENAI_API_KEY")
    p.add_argument("--stdin", action="store_true", help="set: read the value from one line of stdin")
    p.add_argument("--to-grok", action="store_true", help="share: let this one value go to the Grok bot (xAI)")
    p.add_argument("--linked", action="store_true", help="share: let your linked computers fetch it")
    p.add_argument("--off", action="store_true", help="share: take the share back")
    p.add_argument("--yes", action="store_true", help="share --to-grok: do not ask (you read the warning)")


HANDLERS = {"secret": cmd_secret}
