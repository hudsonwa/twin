"""twin#65: the twin skill pack, four read-only skills the plugin ships in `skills/twin-pack/` and copies into each
twin's profile (`<profile>/skills/twin-pack/<skill>/SKILL.md`), tagged `origin: plugin`.

The copy carries a marker file, `.plugin-version`, holding the plugin version that wrote it. It is refreshed on the
same trigger as the origin note (origin.refresh): nothing is written while the marker already holds this version.
A pack skill the owner deleted is not brought back by a refresh (the marker lists what was installed); only
`repair=True` (`hermes twin doctor --repair-pack`) puts it back.

The pack is the plugin's, never the bot's: fleet_skills (the linked-computer copy), skill sync, send-to-grok and
compare's own-skills count all leave it out through is_pack_dir / is_pack_name below.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Iterable, Optional

from . import store
from .model import PLUGIN_VERSION

log = logging.getLogger(__name__)

PACK_DIR = "twin-pack"
MARKER = ".plugin-version"
NAMES = ("twin-about-me", "twin-health", "twin-update", "twin-new-computer")
SOURCE = Path(__file__).resolve().parent.parent / "skills" / PACK_DIR
_CAP = 64 * 1024


def is_pack_name(name: Any) -> bool:
    return isinstance(name, str) and name.strip().casefold() in NAMES


def is_pack_dir(name: Any) -> bool:
    return isinstance(name, str) and name.casefold() == PACK_DIR


def is_pack_path(rel: Any) -> bool:
    """A path (relative to a profile, or a botport item path) inside the pack folder."""
    parts = [p for p in str(rel or "").replace("\\", "/").split("/") if p]
    return any(is_pack_dir(p) for p in parts)


def is_pack_item(item: Any) -> bool:
    """A botport item (sync / drift / parity row) that is one of the pack's skills."""
    if not isinstance(item, dict):
        return False
    if is_pack_path(item.get("path")):
        return True
    for key in ("id", "item"):
        v = item.get(key)
        if isinstance(v, str) and v.startswith("skill:") and is_pack_name(v.split(":", 1)[1]):
            return True
    return False


def source_texts() -> dict:
    """{name: SKILL.md text} of the pack this plugin ships."""
    out = {}
    for n in NAMES:
        f = SOURCE / n / "SKILL.md"
        try:
            out[n] = f.read_text(encoding="utf-8")[:_CAP]
        except (OSError, UnicodeDecodeError):
            continue
    return out


def _read_marker(dest: Path) -> Optional[dict]:
    f = dest / MARKER
    try:
        if f.is_symlink() or not f.is_file():
            return None
        data = json.loads(f.read_text(encoding="utf-8")[:_CAP])
        return data if isinstance(data, dict) else None
    except (OSError, ValueError, UnicodeDecodeError):
        return None


def install_home(home: Path, repair: bool = False) -> bool:
    """Bring one twin profile's pack up to this plugin version. Returns True when anything was written. Only an
    existing profile folder is touched; a link anywhere on the way is refused."""
    home = Path(home)
    if not home.is_dir() or home.is_symlink():
        return False
    skills = home / "skills"
    dest = skills / PACK_DIR
    for p in (skills, dest):
        if p.is_symlink() or (p.exists() and not p.is_dir()):
            return False
    marker = _read_marker(dest)
    if marker and marker.get("version") == PLUGIN_VERSION and not repair:
        return False
    texts = source_texts()
    if not texts:
        return False
    had = set(marker.get("skills") or []) if marker else set()
    wrote = False
    installed = []
    for name, text in texts.items():
        d = dest / name
        f = d / "SKILL.md"
        if d.is_symlink() or f.is_symlink():
            continue
        if marker is not None and name in had and not d.exists() and not repair:
            continue  # the owner deleted it: it stays deleted
        installed.append(name)
        try:
            if f.is_file() and f.read_text(encoding="utf-8") == text:
                continue
        except (OSError, UnicodeDecodeError):
            pass
        d.mkdir(parents=True, exist_ok=True)
        store.atomic_write_text(f, text)
        wrote = True
    want = {"version": PLUGIN_VERSION, "origin": "plugin", "skills": sorted(installed)}
    if marker != want:
        dest.mkdir(parents=True, exist_ok=True)
        store.atomic_write_text(dest / MARKER, json.dumps(want, sort_keys=True) + "\n")
        wrote = True
    return wrote


def refresh(profiles: Iterable[str], repair: bool = False) -> int:
    """Install or refresh the pack in each given twin profile; returns how many were written. Never raises."""
    n = 0
    for prof in profiles:
        try:
            n += install_home(store.profile_home(prof), repair=repair)
        except Exception:
            log.debug("grok-bot-twin: skill pack not refreshed in one profile", exc_info=True)
    return n


def listed(home: Path) -> list:
    """The pack skills present in one profile (for status / tests)."""
    dest = Path(home) / "skills" / PACK_DIR
    return [n for n in NAMES if os.path.isfile(dest / n / "SKILL.md")]
