"""Secrets by reference (docs/SECRETS.md). A value the secret check finds is kept in the OS secret store of this
computer under a NAME and the text keeps `{{secret:NAME}}` (Grok side) or `${NAME}` (Hermes side). The list of
names (`secrets.json`) never holds a value. No OS store: nothing is kept, the caller blanks as before.

Values are never put in argv, an exception, a log line, an event or a return value of anything a chat can call.
"""
from __future__ import annotations

import binascii
import json
import logging
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

from . import secrets as _check
from . import store
from .model import now_iso

log = logging.getLogger(__name__)

SERVICE = "grok-bot-twin"
LIST_FILE = "secrets.json"
NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}\Z")
GROK_REF = re.compile(r"\{\{secret:([A-Z][A-Z0-9_]{0,63})\}\}")
ENV_REF = re.compile(r"\$\{([A-Z][A-Z0-9_]{0,63})\}")
VALUE_MAX = 16 * 1024
TIMEOUT_S = 15
HOW_GROK = ("Set these up in Grok's own connector or secret settings; this bundle holds only their names.")
TO_GROK_WARNING = ("The value of {name} will be sent to the Grok bot and then lives on xAI's service, under xAI's "
                   "terms. Only this one secret is shared; `hermes twin secret share {name} --to-grok --off` stops it.")
# kinds whose value can be cut out cleanly (the rest stays with the line-hiding scrub)
_KINDS = ("api_key", "stripe_key", "github_token", "aws_key", "google_api_key", "slack_token", "hf_token",
          "npm_token", "credential", "random_word")
_LABEL = re.compile(r"([A-Za-z_][A-Za-z0-9_-]{0,63})[\"']?\s*[:=]\s*[\"']?\s*\Z")


class NoStore(Exception):
    """No OS secret store on this computer. The message says why, never a value."""


# ---- the OS stores ---------------------------------------------------------------------------------------------------------
def _env() -> dict:
    keep = ("PATH", "HOME", "USER", "LOGNAME", "DBUS_SESSION_BUS_ADDRESS", "XDG_RUNTIME_DIR", "DISPLAY", "LANG")
    return {k: os.environ[k] for k in keep if k in os.environ}


def _run(argv: list, stdin: Optional[str] = None) -> subprocess.CompletedProcess:
    """argv only, no shell; output is captured and never logged (it could echo the input)."""
    return subprocess.run(argv, input=stdin, capture_output=True, text=True, encoding="utf-8", timeout=TIMEOUT_S, env=_env(),
                          check=False)


class MacKeychain:
    name = "macOS Keychain"
    exe = "/usr/bin/security"

    def available(self) -> Optional[str]:
        return None if sys.platform == "darwin" and os.path.exists(self.exe) else "the security tool is not here"

    def put(self, name: str, value: str) -> None:
        # `security -i` reads the command from stdin, so the value (hex, -X) is never on a command line
        cmd = f"add-generic-password -U -a {name} -s {SERVICE} -l {SERVICE}:{name} -X {value.encode('utf-8').hex()}\n"
        if _run([self.exe, "-i"], cmd).returncode != 0:
            raise NoStore("the Keychain refused to keep it (is it locked?)")

    def get(self, name: str) -> Optional[str]:
        got = _run([self.exe, "find-generic-password", "-a", name, "-s", SERVICE, "-g"])
        if got.returncode != 0:
            return None
        for line in got.stderr.splitlines():
            if line.startswith("password: "):
                rest = line[len("password: "):]
                if rest.startswith("0x"):
                    try:
                        return binascii.unhexlify(rest[2:].split()[0]).decode("utf-8")
                    except (ValueError, UnicodeDecodeError):
                        return None
                return rest[1:-1] if len(rest) >= 2 and rest[0] == rest[-1] == '"' else None
        return None

    def delete(self, name: str) -> None:
        _run([self.exe, "delete-generic-password", "-a", name, "-s", SERVICE])


class SecretService:
    name = "Secret Service"
    exe = "secret-tool"

    def available(self) -> Optional[str]:
        if not sys.platform.startswith("linux"):
            return "not Linux"
        if shutil.which(self.exe) is None:
            return "secret-tool (libsecret) is not installed"
        if not os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
            return "no desktop session bus, so no Secret Service"
        return None

    def put(self, name: str, value: str) -> None:
        got = _run([shutil.which(self.exe) or self.exe, "store", f"--label={SERVICE}:{name}", "service", SERVICE,
                    "account", name], value)
        if got.returncode != 0:
            raise NoStore("the Secret Service refused to keep it (is the keyring locked?)")

    def get(self, name: str) -> Optional[str]:
        got = _run([shutil.which(self.exe) or self.exe, "lookup", "service", SERVICE, "account", name])
        return got.stdout if got.returncode == 0 and got.stdout else None

    def delete(self, name: str) -> None:
        _run([shutil.which(self.exe) or self.exe, "clear", "service", SERVICE, "account", name])


class WinCredentials:
    """Credential Manager through advapi32 (ctypes): no subprocess, nothing on a command line."""
    name = "Windows Credential Manager"

    def available(self) -> Optional[str]:
        if os.name != "nt":
            return "not Windows"
        try:
            import ctypes
            ctypes.WinDLL("advapi32")  # type: ignore[attr-defined]
        except (ImportError, OSError, AttributeError):
            return "Credential Manager cannot be reached"
        return None

    @staticmethod
    def _api() -> Any:
        import ctypes
        from ctypes import wintypes as w

        class CRED(ctypes.Structure):
            _fields_ = [("Flags", w.DWORD), ("Type", w.DWORD), ("TargetName", w.LPWSTR), ("Comment", w.LPWSTR),
                        ("LastWritten", w.FILETIME), ("CredentialBlobSize", w.DWORD),
                        ("CredentialBlob", ctypes.POINTER(ctypes.c_char)), ("Persist", w.DWORD),
                        ("AttributeCount", w.DWORD), ("Attributes", ctypes.c_void_p), ("TargetAlias", w.LPWSTR),
                        ("UserName", w.LPWSTR)]
        return ctypes, CRED, ctypes.WinDLL("advapi32")  # type: ignore[attr-defined]

    def put(self, name: str, value: str) -> None:
        ctypes, CRED, api = self._api()
        blob = value.encode("utf-16-le")
        buf = ctypes.create_string_buffer(blob, len(blob))
        c = CRED(Type=1, TargetName=f"{SERVICE}:{name}", CredentialBlobSize=len(blob),
                 CredentialBlob=ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)), Persist=2, UserName=name)
        if not api.CredWriteW(ctypes.byref(c), 0):
            raise NoStore("Credential Manager refused to keep it")

    def get(self, name: str) -> Optional[str]:
        ctypes, CRED, api = self._api()
        p = ctypes.POINTER(CRED)()
        if not api.CredReadW(f"{SERVICE}:{name}", 1, 0, ctypes.byref(p)):
            return None
        try:
            return ctypes.string_at(p.contents.CredentialBlob, p.contents.CredentialBlobSize).decode("utf-16-le")
        finally:
            api.CredFree(p)

    def delete(self, name: str) -> None:
        ctypes, _CRED, api = self._api()
        api.CredDeleteW(f"{SERVICE}:{name}", 1, 0)


BACKENDS = (MacKeychain(), SecretService(), WinCredentials())
_override: list = []  # tests put a mocked store here (never a file)


def backend() -> Any:
    """The OS store of this computer. Raises NoStore (with the reason) when there is none: never a file."""
    if _override:
        if _override[0] is None:
            raise NoStore("no OS secret store on this computer")
        return _override[0]
    why = []
    for b in BACKENDS:
        reason = b.available()
        if reason is None:
            return b
        why.append(reason)
    raise NoStore("no OS secret store on this computer: " + "; ".join(why[:3]))


def store_reason() -> Optional[str]:
    try:
        backend()
        return None
    except NoStore as e:
        return str(e)


# ---- the list of names (no values) ---------------------------------------------------------------------------------------
def _list_path() -> Path:
    return store.central_dir() / LIST_FILE


def load() -> dict:
    data = store.read_json(_list_path(), {})
    raw = data.get("secrets") if isinstance(data, dict) else None
    out = {}
    for name, rec in (raw or {}).items() if isinstance(raw, dict) else ():
        if isinstance(name, str) and NAME_RE.match(name) and isinstance(rec, dict):
            where = [w for w in rec.get("where") or [] if isinstance(w, dict) and isinstance(w.get("twin"), str)]
            out[name] = {"where": where[:50], "to_grok": rec.get("to_grok") is True, "linked": rec.get("linked") is True,
                         "kind": str(rec.get("kind") or "")[:30], "since": str(rec.get("since") or "")[:40]}
    return out


def save(names: dict) -> None:
    store.atomic_write_text(_list_path(), json.dumps({"version": 1, "secrets": names}, indent=2, sort_keys=True))


def _note(names: dict, name: str, kind: str, twin: str, item: str) -> None:
    rec = names.setdefault(name, {"where": [], "to_grok": False, "linked": False, "kind": kind, "since": now_iso()})
    w = {"twin": twin, "item": item[:80]}
    if twin and w not in rec["where"]:
        rec["where"] = (rec["where"] + [w])[-50:]


def keep(name: str, value: str, kind: str = "set", twin: str = "", item: str = "") -> None:
    """Put one value in the OS store and its name in the list. Raises NoStore or ValueError (never with the value)."""
    if not NAME_RE.match(name or ""):
        raise ValueError("a secret's name is capital letters, digits and _, starting with a letter")
    if not isinstance(value, str) or not value or len(value) > VALUE_MAX or "\0" in value:
        raise ValueError("that is not a value the store can keep")
    backend().put(name, value)
    names = load()
    _note(names, name, kind, twin, item)
    save(names)


def value_of(name: str) -> Optional[str]:
    """For the plugin's own resolving only (`.env`, an opted-in bundle, a linked computer). Never a tool's answer."""
    try:
        return backend().get(name) if NAME_RE.match(name or "") else None
    except (NoStore, OSError, subprocess.SubprocessError):
        return None


def forget(name: str) -> bool:
    names = load()
    found = names.pop(name, None) is not None
    try:
        backend().delete(name)
    except (NoStore, OSError, subprocess.SubprocessError):
        pass
    save(names)
    for home in _twin_homes():
        remove_env(home, name)
    return found


def set_switch(name: str, switch: str, on: bool) -> None:
    names = load()
    if name not in names:
        raise KeyError(name)
    names[name][switch] = bool(on)
    save(names)


def _twin_homes() -> list:
    root = store.hermes_root() / "profiles"
    try:
        return [p for p in root.iterdir() if p.is_dir() and not p.is_symlink() and (p / ".env").is_file()]
    except OSError:
        return []


# ---- finding values in text -----------------------------------------------------------------------------------------------
def _spans(text: str) -> list:
    """[(start, end, kind, label)] of values that can be cut out of `text`, not overlapping, in order."""
    found = []
    for kind, _what, rx, _whole in _check._PATTERNS:
        if kind not in _KINDS:
            continue
        for m in rx.finditer(text):
            g = next((i for i in range(1, (m.lastindex or 0) + 1) if m.group(i)), 0)
            a, b = m.span(g)
            while b > a and text[b - 1] in ".,;)\"'":
                b -= 1
            lab = _LABEL.search(text[m.start():a]) if g else None
            found.append((a, b, kind, lab.group(1) if lab else ""))
    for m in _check._PRIVATE_BLOCK.finditer(text):
        found.append((m.start(), m.end(), "private_key", ""))
    for m in _check._WORD.finditer(text):
        if _check._random_word(m.group(0)):
            found.append((m.start(), m.end(), "random_word", ""))
    refs = [(r.start(), r.end()) for r in _check._REF.finditer(text)]
    # a named credential first, then a known key format, then a word that only looks random
    rank = {"credential": 0, "random_word": 2}
    found.sort(key=lambda s: (rank.get(s[2], 1) if s[2] != "credential" or s[3] else 1, s[0]))
    taken: list = []
    for s in found:
        if s[1] - s[0] < 4 or any(a < s[1] and b > s[0] for a, b in refs + [t[:2] for t in taken]):
            continue
        taken.append(s)
    return sorted(taken)


def _base_name(kind: str, label: str) -> str:
    raw = (label or kind).upper().replace("-", "_")
    raw = re.sub(r"[^A-Z0-9_]", "", raw).strip("_") or "SECRET"
    return (raw if raw[0].isalpha() else "S_" + raw)[:56]


class Refs:
    """One pass of a twin's texts. `take` keeps what it finds in the OS store and puts references in its place; when
    there is no store it changes nothing and says why in `refused` (the caller's own scrub then blanks)."""

    def __init__(self, twin: str) -> None:
        self.twin = twin
        self.names: dict = load()
        self.used: list = []  # names this pass referred to, in order
        self.kept = 0
        self.refused: Optional[str] = None
        self._dirty = False

    def _name_for(self, value: str, kind: str, label: str) -> str:
        base = _base_name(kind, label)
        b = backend()
        for name in self.used + [n for n, r in self.names.items() if any(w["twin"] == self.twin for w in r["where"])]:
            if b.get(name) == value:  # the same value keeps its name, whatever this text calls it
                return name
        for i in range(1, 50):
            name = base if i == 1 else f"{base}_{i}"
            have = b.get(name) if name in self.names else None
            if name not in self.names or have is None:
                b.put(name, value)
                self.kept += 1
                return name
            if have == value:
                return name
        raise NoStore("too many secrets under one name")

    def take(self, text: str, item: str, style: str = "grok") -> str:
        """`text` with each value cut out: `{{secret:NAME}}` (style "grok") or `${NAME}` (style "env")."""
        if not isinstance(text, str) or not text or self.refused:
            return text
        spans = _spans(text)
        if not spans:
            return self.convert(text, style)
        try:
            out, last, parts = text, 0, []
            for a, b, kind, label in spans:
                name = self._name_for(text[a:b], kind, label)
                _note(self.names, name, kind, self.twin, item)
                self._dirty = True
                if name not in self.used:
                    self.used.append(name)
                parts += [text[last:a], ("${%s}" if style == "env" else "{{secret:%s}}") % name]
                last = b
            out = "".join(parts) + text[last:]
        except (NoStore, OSError, subprocess.SubprocessError) as e:
            self.refused = str(e) if isinstance(e, NoStore) else "the OS secret store did not answer"
            return text
        return self.convert(out, style)

    def convert(self, text: str, style: str) -> str:
        """References of known names, turned to the other side's form. A name this twin does not use stays text (a
        hostile bot cannot ask for another twin's secret by writing its placeholder)."""
        mine = {n for n, r in self.names.items() if any(w.get("twin") == self.twin for w in r["where"])}
        rx, fmt = (GROK_REF, "${%s}") if style == "env" else (ENV_REF, "{{secret:%s}}")

        def swap(m: "re.Match[str]") -> str:
            if m.group(1) not in mine:
                return m.group(0)
            if m.group(1) not in self.used:
                self.used.append(m.group(1))
            return fmt % m.group(1)
        return rx.sub(swap, text)

    def done(self) -> None:
        if self._dirty:
            save(self.names)
            self._dirty = False

    def for_grok(self, text: str) -> str:
        """Last step to Grok: only a name the owner shared --to-grok themselves becomes its value."""
        def put(m: "re.Match[str]") -> str:
            rec = self.names.get(m.group(1))
            if not rec or not rec["to_grok"]:
                return m.group(0)
            v = value_of(m.group(1))
            return v if v is not None else m.group(0)
        return GROK_REF.sub(put, text) if isinstance(text, str) else text

    def needed(self) -> list:
        return [n for n in self.used if not (self.names.get(n) or {}).get("to_grok")]

    def report(self) -> dict:
        return {"kept_by_reference": self.kept, "names": list(self.used),
                **({"not_kept": self.refused} if self.refused else {})}

    def to_env(self, home: Path) -> int:
        """Grok -> Hermes: every name this pass referred to, as a line of the profile's own `.env` (Hermes' place
        for keys). Returns how many were written."""
        n = 0
        for name in self.used:
            v = value_of(name)
            if v is not None and write_env(home, name, v):
                n += 1
        return n


# ---- the Hermes profile's .env ----------------------------------------------------------------------------------------------
_ENV_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")


def _quote(value: str) -> str:
    """Hermes' own `_quote_env_value` rule."""
    if not ("#" in value or '"' in value or "'" in value or any(c.isspace() for c in value)):
        return value
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _env_lines(path: Path) -> list:
    try:
        return path.read_text(encoding="utf-8").splitlines() if path.is_file() and not path.is_symlink() else []
    except (OSError, UnicodeDecodeError):
        return []


def write_names(home: Path, names: list) -> int:
    """Each NAME's value from the OS store as a line of the profile's own .env (names only in; never a value in or
    out). -> how many were written."""
    n = 0
    for name in names or []:
        v = value_of(name) if isinstance(name, str) and NAME_RE.match(name) else None
        if v is not None and write_env(home, name, v):
            n += 1
    return n


def write_env(home: Path, name: str, value: str) -> bool:
    if "\n" in value or "\r" in value or not NAME_RE.match(name):
        return False
    path = home / ".env"
    if path.is_symlink():
        return False
    lines = [ln for ln in _env_lines(path) if not ((m := _ENV_LINE.match(ln)) and m.group(1) == name)]
    lines.append(f"{name}={_quote(value)}")
    store.atomic_write_text(path, "\n".join(lines) + "\n")
    os.chmod(path, 0o600)
    return True


def remove_env(home: Path, name: str) -> None:
    path = home / ".env"
    lines = _env_lines(path)
    kept = [ln for ln in lines if not ((m := _ENV_LINE.match(ln)) and m.group(1) == name)]
    if kept != lines:
        store.atomic_write_text(path, "\n".join(kept) + ("\n" if kept else ""))
        os.chmod(path, 0o600)
