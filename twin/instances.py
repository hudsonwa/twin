"""EXPERIMENTAL (twin#70): instances of a twin, "Acme Support 2" next to "Acme Support".

`hermes twin instance create TWIN [--name "TWIN N"] --yes` records one instance on this computer;
`hermes twin instance list [--json]` lists them. Hidden from `hermes twin --help` like remote-create, which runs
`instance create` on the target computer (docs/design/remote-create.md, step 7).

The smallest step the design needs: the record (name, twin, Hermes profile id, when). The name is "TWIN N" with N
the next free number among the names this computer knows plus any the caller passes (`taken`); remote-create passes
the names it read from the target so two computers never both make a "2". Making the instance's own Hermes profile,
chats and Telegram bot is later work; the record says `profile` so that work has one place to look.
Nothing is deleted or overwritten: creating a name that exists is "already there" (safe to run again).
"""
from __future__ import annotations

import json
import re
from typing import Any, Iterable, List, Optional

from . import store
from .model import now_iso

FILE = "instances.json"
NAME_MAX = 100
_BAD = re.compile(r"[\x00-\x1f\x7f/\\]")


def _path():
    return store.central_dir() / FILE


def load() -> List[dict]:
    data = store.read_json(_path(), {})
    rows = data.get("instances") if isinstance(data, dict) else None
    return [r for r in rows or [] if isinstance(r, dict) and isinstance(r.get("name"), str)]


def profile_id(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:64] or "instance"


def next_name(twin: str, taken: Iterable[str] = ()) -> str:
    """Next free "TWIN N" (N from 2; "TWIN" itself is the first instance)."""
    have = set(taken) | {r["name"] for r in load()}
    n = 2
    while f"{twin} {n}" in have:
        n += 1
    return f"{twin} {n}"


def bad_name(name: Any) -> Optional[str]:
    if not isinstance(name, str) or not name.strip() or len(name) > NAME_MAX or _BAD.search(name):
        return "a name is plain text, at most 100 characters"
    return None


def create(twin: str, name: str = "", taken: Iterable[str] = ()) -> dict:
    """{"name", "twin", "profile", "created": bool}. Raises ValueError on a bad name."""
    for v in (twin, name or twin):
        why = bad_name(v)
        if why:
            raise ValueError(why)
    name = name.strip() if name else next_name(twin.strip(), taken)
    with store.locked():
        rows = load()
        for r in rows:
            if r["name"] == name:
                return {**r, "created": False}
        rec = {"name": name, "twin": twin.strip(), "profile": profile_id(name), "since": now_iso()}
        store.atomic_write_text(_path(), json.dumps({"version": 1, "instances": rows + [rec]}, indent=2))
    return {**rec, "created": True}


# ---- CLI (hidden, experimental) ----

def cmd_instance(a: Any, out=print) -> int:
    if a.what == "list":
        rows = load()
        if getattr(a, "json", False):
            out(json.dumps({"instances": rows}))
        else:
            for r in rows:
                out(f"{r['name']}  (instance of {r.get('twin', '?')}, profile {r.get('profile', '?')})")
            if not rows:
                out("No instances on this computer.")
        return 0
    if not a.twin:
        out("FAIL: instance create: say which twin")
        return 2
    if not a.yes:
        out(f"Would record the instance {(a.name or next_name(a.twin))!r} of {a.twin!r}; run again with --yes")
        return 2
    try:
        rec = create(a.twin, a.name or "")
    except ValueError as e:
        out(f"FAIL: instance create: {e}")
        return 2
    out(f"PASS: instance {rec['name']!r} of {rec['twin']!r} "
        + ("recorded" if rec["created"] else "already there"))
    return 0


def setup(subs: Any) -> None:
    p = subs.add_parser("instance")  # no help=: hidden while experimental (twin#70)
    p.add_argument("what", choices=("create", "list"))
    p.add_argument("twin", nargs="?", default="")
    p.add_argument("--name", default="")
    p.add_argument("--yes", action="store_true")
    p.add_argument("--json", action="store_true")


HANDLERS = {"instance": lambda a: cmd_instance(a)}
