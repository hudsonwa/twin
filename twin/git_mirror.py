"""Optional per-bot git history of a twin (off by default; git is only needed once it is switched on).

`hermes twin git on [BOT|--all] [--remote URL] [--with-history]`, `hermes twin git off [BOT|--all]`,
`hermes twin git status`. When it is on for a twin, every PASS of the one-prompt tools (twin, sync, move, back:
`one_prompt._finish`, the one place the library reports PASS) writes the bot's instructions, skills, memory and
routines as readable files (Markdown/JSON, stable order) to `<plugin-data>/git/<twin>/`, one repository per twin,
and commits them ("PASS sync from Grok: 2 skills changed"). With a remote (a Forgejo URL, say) it pushes after the
commit; a push that fails is a warning on the PASS line, never a FAIL of the sync.

- Chat history (the twin's Hermes session database) is left out unless `--with-history` was given.
- Every file goes through the plugin's secret scrub first (`secrets.redact`, line mode); a file that still looks
  like it holds a password or key is left out. Plugin keys, tokens and `.env`/auth files are never read. The remote
  URL lives in this module's settings file only (not in the repository and never printed).
- No git on this computer: the PASS line says so and how to install it; the sync itself is untouched.
- The default (the twin's Hermes files plus 3 snapshots, chat history in Hermes' own database) is unchanged.
"""
from __future__ import annotations

import json
import re
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional

from . import safe, store
from . import secrets as _secrets

ALL = "*"
GIT_TIMEOUT_S = 60
FILE_CAP = 1_000_000             # bytes of one source file that are mirrored
LEFT_OUT = "[line left out: it looked like a password or key]"
NEVER = (".env", "auth.json", "credentials", "token", "key", ".pem")
INSTALL = ("git is not installed, so no git history was kept (install it: macOS `xcode-select --install`, "
           "Debian/Ubuntu `sudo apt install git`, Windows https://git-scm.com/download/win)")
AUTHOR = ["-c", "user.name=Grok Bot Twin", "-c", "user.email=twin@localhost", "-c", "commit.gpgsign=false"]


# ---- settings -------------------------------------------------------------------------------------------------
def _base() -> Path:
    return store.ensure_dir(store.central_dir() / "git")


def _settings_file() -> Path:
    return _base() / "settings.json"


def settings() -> dict:
    got = store.read_json(_settings_file(), {}) if _settings_file().is_file() else {}
    return got if isinstance(got, dict) else {}


def setting_for(pid: str) -> Optional[dict]:
    """This twin's git setting (its own, else the --all one), or None when git history is off for it."""
    s = settings()
    own = s.get(pid)
    if isinstance(own, dict):
        return own if own.get("on") else None
    every = s.get(ALL)
    return every if isinstance(every, dict) and every.get("on") else None


def _status_file() -> Path:
    return _base() / "status.json"


def last_status(pid: str) -> dict:
    got = store.read_json(_status_file(), {}) if _status_file().is_file() else {}
    got = got.get(pid) if isinstance(got, dict) else None
    return got if isinstance(got, dict) else {}


def _note_status(pid: str, **fields: Any) -> None:
    """What the last commit/push did, for the Twins page (never the remote URL or a token)."""
    all_ = store.read_json(_status_file(), {}) if _status_file().is_file() else {}
    all_ = all_ if isinstance(all_, dict) else {}
    from .model import now_iso
    all_[pid] = {**fields, "at": now_iso()}
    store.atomic_write_json(_status_file(), all_)


def set_on(pid: str, on: bool, remote: Optional[str] = None, history: bool = False) -> None:
    s = settings()
    s[pid] = {"on": True, "remote": remote, "history": bool(history)} if on else {"on": False}
    store.atomic_write_json(_settings_file(), s)
    os.chmod(_settings_file(), 0o600)  # (owner-only; clean_remote refuses an address that carries a password or token)


# ---- the files ------------------------------------------------------------------------------------------------
def _clean(text: str) -> Optional[str]:
    text = _secrets.redact(text, line_marker=LEFT_OUT)
    return None if _secrets.has_secret(text) else text


def _read(path: Path) -> Optional[str]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > FILE_CAP:
        return None
    if any(n in path.name.lower() for n in NEVER):
        return None
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _tree(home: Path, part: str, dest: str) -> dict:
    out = {}
    root = home / part
    if not root.is_dir() or root.is_symlink():
        return out
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if any(x.startswith(".") for x in rel.parts):
            continue
        text = _read(p)
        if text is not None:
            out[f"{dest}/{rel.as_posix()}"] = text
    return out


def _json_text(text: str) -> str:
    try:
        return json.dumps(json.loads(text), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    except ValueError:
        return text


def _history(home: Path) -> dict:
    from .transcripts import _hermes_sessions
    out = {}
    try:
        sessions = list(_hermes_sessions(home))
    except Exception:  # noqa: BLE001  (an unreadable database: history is left out, the rest is kept)
        return out
    for sid, title, msgs in sessions:
        lines = [f"# {title or sid}", ""] + [f"**{m['role']}** ({m['at']}): {m['text']}" for m in msgs]
        out[f"history/{safe.clean_name(sid, 80) or 'session'}.md"] = "\n\n".join(lines) + "\n"
    return out


def readable_files(home: Path, history: bool = False) -> tuple[dict, int]:
    """{repo path: scrubbed text} of the twin's instructions, skills, memory and routines (and chat history when
    asked), and how many files were left out as password-like."""
    raw: dict = {}
    soul = _read(home / "SOUL.md")
    if soul is not None:
        raw["instructions.md"] = soul
    raw.update(_tree(home, "skills", "skills"))
    raw.update(_tree(home, "memories", "memory"))
    raw.update({k: _json_text(v) if k.endswith(".json") else v for k, v in _tree(home, "cron", "routines").items()})
    if history:
        raw.update(_history(home))
    out, left = {}, 0
    for k in sorted(raw):
        text = _clean(raw[k])
        if text is None:
            left += 1
        else:
            out[k] = text
    return out, left


def _write(repo: Path, files: dict) -> None:
    for p in sorted(repo.rglob("*"), reverse=True):  # what is no longer there goes (never inside .git)
        rel = p.relative_to(repo)
        if rel.parts[0] == ".git":
            continue
        if p.is_file() and rel.as_posix() not in files:
            p.unlink()
        elif p.is_dir() and not any(p.iterdir()):
            p.rmdir()
    for k, text in files.items():
        target = store.safe_child(repo, *k.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="\n")


# ---- git ------------------------------------------------------------------------------------------------------
def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_ASKPASS="true", LC_ALL="C")
    return subprocess.run(["git", *AUTHOR, "-C", str(repo), *args], capture_output=True, text=True,
                          timeout=GIT_TIMEOUT_S, env=env, check=False)


def _message(kind: str, changed: list) -> str:
    skills = {p.split("/")[1] for p in changed if p.startswith("skills/") and p.count("/") >= 2}
    parts = [f"{len(skills)} skill{'s' if len(skills) != 1 else ''} changed"]
    for prefix, word in (("instructions.md", "instructions"), ("memory/", "memory"), ("routines/", "routines"),
                         ("history/", "history")):
        if any(p.startswith(prefix) for p in changed):
            parts.append(f"{word} changed")
    return f"PASS {kind} from Grok: " + ", ".join(parts)


def commit(pid: str, home: Path, kind: str, setting: dict) -> str:
    """Mirror and commit one twin; the words added to its PASS line (empty when nothing changed)."""
    if shutil.which("git") is None:
        return f" Note: {INSTALL}."
    repo = store.ensure_dir(_base() / pid)
    if not (repo / ".git").is_dir():
        _git(repo, "init", "-q")
    files, left = readable_files(home, bool(setting.get("history")))
    _write(repo, files)
    _git(repo, "add", "-A")
    changed = [p for p in _git(repo, "diff", "--cached", "--name-only").stdout.splitlines() if p]
    note = f" Git history: {left} file(s) left out as password-like." if left else ""
    if not changed:
        return note
    got = _git(repo, "commit", "-q", "-m", _message(kind, changed))
    if got.returncode != 0:
        why = safe.clean_summary(_secrets.redact(got.stderr), 200)
        _note_status(pid, commit=None, pushed=None, problem="The git commit failed: " + why)
        return note + " Warning: the git commit failed: " + why
    sha = _git(repo, "rev-parse", "--short", "HEAD").stdout.strip()
    words = f" Git history: commit {sha}." + note
    pushed_ok, problem = None, ""
    if setting.get("remote"):
        pushed = _git(repo, "push", "-q", setting["remote"], "HEAD:refs/heads/main")
        if pushed.returncode != 0:  # the URL may carry a token: never shown
            err = safe.clean_summary(_secrets.redact(pushed.stderr.replace(setting["remote"], "the remote")), 200)
            words += f" Warning: git push failed ({err})."
            pushed_ok, problem = False, f"The push failed: {err}"
        else:
            words += " Pushed."
            pushed_ok = True
    _note_status(pid, commit=sha, pushed=pushed_ok, problem=problem)
    return words


def after_pass(pid: Any, home: Any, kind: str) -> str:
    """Called on every PASS; never raises (a PASS stays a PASS)."""
    try:
        setting = setting_for(pid) if isinstance(pid, str) else None
        if setting is None or home is None:
            return ""
        return commit(pid, Path(home), kind, setting)
    except Exception as exc:  # noqa: BLE001
        return f" Warning: git history not kept ({safe.clean_summary(type(exc).__name__, 60)})."


# ---- the Twins page (dashboard routes call these; the CLI uses the same set_on) ------------------------------
SCHEMA = "grok-bot-twin.gitpanel.v1"
REMOTE_MAX = 500


def has_git() -> bool:
    return shutil.which("git") is not None


_CRED_IN_URL = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://[^/@\s]*:[^/@\s]*@")  # scheme://user:secret@


def clean_remote(value: Any) -> Optional[str]:
    """A remote URL as typed ('' clears it); raises EngineError when it cannot be one."""
    from .engine import EngineError
    if value is None:
        return None
    if not isinstance(value, str):
        raise EngineError("bad_input", "That remote address was not understood.")
    value = value.strip()
    if value and (len(value) > REMOTE_MAX or value.startswith("-") or any(c.isspace() or ord(c) < 32 for c in value)):
        raise EngineError("bad_input", "That does not look like a git address (for example https://forgejo.example/me/bot.git).")
    if value and (_CRED_IN_URL.match(value) or _secrets.has_secret(value)):
        # (it would be kept in plain text in git/settings.json): sign-in belongs to git's own credential helper or SSH
        raise EngineError("bad_input", "That address carries a password or token. Give it without one (for example "
                          "https://forgejo.example/me/bot.git or git@forgejo.example:me/bot.git) and let git's "
                          "credential helper or your SSH key sign in.")
    return value


def _host(url: str) -> str:
    from urllib.parse import urlsplit
    try:
        return urlsplit(url).hostname or ""
    except ValueError:
        return ""


def panel(svc: Any) -> dict:
    """GET /git/panel: every twin, whether its git history is on, whether a remote is set (the host only, never
    the URL), and what the last commit/push did."""
    from .sync_panel import _contexts
    twins = []
    for ctx in _contexts(svc):
        own = settings().get(ctx.pair_id)
        on = setting_for(ctx.pair_id)
        st = last_status(ctx.pair_id)
        twins.append({
            "id": ctx.pair_id, "name": ctx.name, "on": on is not None,
            "every": on is not None and not isinstance(own, dict),
            "remote_set": bool(on and on.get("remote")), "remote_host": _host(on["remote"]) if on and on.get("remote") else "",
            "last": {"at": st.get("at"), "commit": st.get("commit"), "pushed": st.get("pushed"),
                     "problem": safe.clean_summary(str(st.get("problem") or ""), 200)} if st else None,
        })
    return {"schema": SCHEMA, "git": has_git(), "install": "" if has_git() else INSTALL, "twins": twins}


def choose(svc: Any, pid: Any, on: Any, remote: Any = None) -> dict:
    """POST /git/panel: switch one twin's git history on/off; remote None keeps it, '' clears it, a string sets it."""
    from .engine import EngineError
    from .model import valid_id
    from .sync_panel import _contexts
    if not valid_id(pid) or not isinstance(on, bool):
        raise EngineError("bad_input", "That request was not understood.")
    ctx = next((c for c in _contexts(svc) if c.pair_id == pid), None)
    if ctx is None:
        raise EngineError("no_twin", "That twin is not on this computer.")
    new = clean_remote(remote)
    cur = setting_for(pid) or {}
    if on and not has_git():
        raise EngineError("no_git", INSTALL[0].upper() + INSTALL[1:] + ".")
    set_on(pid, on, (cur.get("remote") if new is None else new or None) if on else None,
           bool(cur.get("history")) if on else False)
    return {**panel(svc), "said": {"sentence": f"Git history for {ctx.name}: {'on' if on else 'off'}."}}


# ---- the command ----------------------------------------------------------------------------------------------
def status_lines() -> list:
    s = settings()
    lines = [] if shutil.which("git") else [f"Note: {INSTALL}."]
    if not any(isinstance(v, dict) and v.get("on") for v in s.values()):
        return lines + ["Git history is off for every twin (the default). Switch on: hermes twin git on \"NAME\""]
    for pid in sorted(s):
        v = s[pid]
        who = "every twin" if pid == ALL else pid
        if isinstance(v, dict):
            extra = (", pushes to its remote" if v.get("remote") else "") + (", with chat history" if v.get("history")
                                                                               else "")
            lines.append(f"{who}: {'on' if v.get('on') else 'off'}{extra if v.get('on') else ''}"
                         + (f" ({_base() / pid})" if v.get("on") and pid != ALL else ""))
    return lines


def cmd_git(a) -> int:
    from . import cli as c
    if a.action == "status":
        for ln in status_lines():
            c._out(ln)
        return 0
    if a.all:
        pid = ALL
    elif a.pair:
        svc = c._svc()
        pid = c._resolve(svc, a.pair)
    else:
        c._out("FAIL: name the twin (hermes twin git on \"NAME\") or give --all")
        return 1
    on = a.action == "on"
    try:
        a.remote = clean_remote(a.remote) or None
    except Exception as exc:  # noqa: BLE001
        c._out(f"FAIL: {exc}")
        return 1
    set_on(pid, on, a.remote if on else None, a.with_history if on else False)
    who = "every twin" if pid == ALL else f"\"{pid}\""
    if on and shutil.which("git") is None:
        c._out(f"Note: {INSTALL}.")
    c._out(f"PASS: git history {'on' if on else 'off'} for {who}"
           + (" (commits after every PASS" + (" and pushes" if a.remote else "") + ")" if on else ""))
    return 0


def setup(subs: Any, twin_type: Any) -> None:
    p = subs.add_parser("git", help="Optional git history of a twin's instructions, skills, memory and routines")
    p.add_argument("action", choices=["on", "off", "status"])
    p.add_argument("pair", nargs="?", type=twin_type, metavar="TWIN", help="The twin's name, in quotes")
    p.add_argument("--all", action="store_true", help="Every twin")
    p.add_argument("--remote", metavar="URL", help="Push after each commit (a Forgejo URL, say)")
    p.add_argument("--with-history", action="store_true", help="Include chat history (left out by default)")


HANDLERS = {"git": cmd_git}
