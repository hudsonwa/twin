"""The key a model server needs, carried to a new twin by reference (twin#76 item 1).

A twin pointed at the owner's own model server (one_prompt.same_server_as_owner, the Twins page's model picker:
batch.set_model with an endpoint) got the server's address but no key, so on a server that wants one its first chat
failed. Now the key goes with it, by reference, the way docs/SECRETS.md keeps every key:

- Where the key is found, in this order: the model setup (the endpoint's entry in the default profile's
  config.yaml: `key_env` / `api_key_env`, or `api_key: ${NAME}`, or a literal `api_key`), then the source profile
  (the default profile's own `.env`, for the NAME the setup refers to), then the OS secret store (a NAME kept there
  before).
- The value goes into the OS secret store under NAME (it may already be there), and from there into the twin
  profile's own private `.env` (secret_ref.write_names, 0600), the place Hermes reads a profile's keys from.
- The twin's config.yaml gets `api_key: ${NAME}`: the reference, never the value.
- The caller's line names NAME and where it came from, never the value. No OS secret store (or a locked one):
  the value (already on this computer: the source profile's .env or the model setup) goes straight into the twin's
  own private .env (0600) instead, and the line says so. No value under NAME anywhere: nothing is written, and the line
  says the key was not kept and why.

The value is never in a return value, a log line, an exception or argv.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any, Optional

from . import hermes_side as hs
from . import secret_ref, store

_REF = re.compile(r"^\s*\$\{(?:env:)?([A-Z][A-Z0-9_]{0,63})\}\s*$")
DEFAULT_NAME = "MODEL_SERVER_API_KEY"
KIND = "model_key"


def _norm(url: Any) -> str:
    return str(url or "").strip().rstrip("/").lower()


def _entries(doc: dict) -> list:
    out: list = []
    cp = doc.get("custom_providers")
    if isinstance(cp, list):
        out += [e for e in cp if isinstance(e, dict)]
    pv = doc.get("providers")
    if isinstance(pv, dict):
        out += [{**e, "name": e.get("name") or k} for k, e in pv.items() if isinstance(e, dict)]
    if isinstance(doc.get("model"), dict):
        out.append(doc["model"])
    return out


def _name_for(label: Any) -> str:
    n = re.sub(r"[^A-Z0-9]+", "_", str(label or "").upper()).strip("_")
    n = f"{n}_API_KEY" if n else DEFAULT_NAME
    return n if secret_ref.NAME_RE.match(n) else DEFAULT_NAME


def _find(base_url: str, root: Path) -> Optional[tuple]:
    """(NAME, literal value or None) for the endpoint at base_url in root's config.yaml; None: no key there."""
    text = hs._read_below_root(root / "config.yaml", hs.CONFIG_CAP)
    if not text:
        return None
    try:
        doc = hs._yaml_load(text)
    except Exception:
        return None
    if not isinstance(doc, dict):
        return None
    want = _norm(base_url)
    for e in _entries(doc):
        url = next((e.get(k) for k in ("base_url", "url", "api") if isinstance(e.get(k), str) and e.get(k)), "")
        if not want or _norm(url) != want:
            continue
        for k in ("key_env", "api_key_env"):
            v = e.get(k)
            if isinstance(v, str) and secret_ref.NAME_RE.match(v.strip()):
                return v.strip(), None
        v = e.get("api_key")
        if isinstance(v, str) and v.strip():
            m = _REF.match(v)
            if m:
                return m.group(1), None
            if "${" not in v:
                return _name_for(e.get("name") or e.get("provider")), v.strip()
    return None


def _env_value(path: Path, name: str) -> Optional[str]:
    """NAME's value in a dotenv file (the last line naming it), or None. Kept in memory only."""
    got = None
    for ln in secret_ref._env_lines(path):
        m = secret_ref._ENV_LINE.match(ln)
        if not m or m.group(1) != name:
            continue
        v = ln[m.end():].strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
            if ln[m.end():].strip()[0] == '"':
                v = v.replace('\\"', '"').replace("\\\\", "\\")
        got = v or None
    return got


def carry(home: Path, base_url: str, twin: str, root: Optional[Path] = None) -> Optional[dict]:
    """Give the twin at `home` the key of the model server at `base_url`, by reference.
    -> None (the setup names no key for that server), {"name", "from"} (kept: "model setup", "source profile" or
    "secret store"), or {"name", "not_kept": why}. Names only, never a value."""
    root = Path(root) if root is not None else store.hermes_root()
    found = _find(base_url, root)
    if found is None:
        return None
    name, literal = found
    if literal is not None:
        value, frm = literal, "model setup"
    else:
        value, frm = _env_value(root / ".env", name), "source profile"
        if value is None:
            value, frm = secret_ref.value_of(name), "secret store"
    if not value:
        return {"name": name, "not_kept": "it has no value in the source profile or the secret store"}
    if frm == "model setup":
        held = secret_ref.value_of(name)
        if held is not None and held != value:  # never overwrite another key that happens to share the made-up name
            return {"name": name, "not_kept": "the secret store already holds a different key under that name"}
    if frm != "secret store":
        try:
            secret_ref.keep(name, value, kind=KIND, twin=twin, item="model")
        except ValueError:
            return {"name": name, "not_kept": "the secret store did not keep it"}
        except (secret_ref.NoStore, OSError, subprocess.SubprocessError):
            # The OS secret store is locked or missing (the Keychain over SSH, rehearsal 17 Nov): the value is
            # already on this computer in a file only the owner reads, so it goes straight into the twin's own
            # private .env (0600), the reference in config.yaml as always. No hand edit; the line says how.
            if not secret_ref.write_env(Path(home), name, value):
                return {"name": name, "not_kept": "it could not be written to the twin's own .env"}
            return {"name": name, "from": frm, "store": "locked"}
    if secret_ref.write_names(Path(home), [name]) != 1:
        return {"name": name, "not_kept": "it could not be written to the twin's own .env"}
    return {"name": name, "from": frm}


def ref(name: str) -> str:
    return "${" + name + "}"


def note(key: Optional[dict]) -> str:
    """"; model key kept by reference (NAME, from the source profile)" for a PASS line, or why it was not."""
    if not isinstance(key, dict) or not key.get("name"):
        return ""
    if key.get("from"):
        via = ("; the OS secret store was locked, so it went straight to the twin's own private .env"
               if key.get("store") == "locked" else "")
        return f"; model key kept by reference ({key['name']}, from the {key['from']}{via})"
    return f"; model key {key['name']} not kept ({key.get('not_kept') or 'unknown'})"
