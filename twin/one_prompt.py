"""One prompt in a Grok bot makes a tested Hermes twin (issue #41, the U1 slice of the one-prompt plan).

A Grok bot reads its own instructions, skills (Skill tool), memory (RecallMemory) and routines and passes them,
in ONE call, to `twin_from_grok` on the plugin's local MCP server (mcp_server.py, `hermes twin mcp`). This module
is everything that call does; the MCP server only decodes the call and prints the answer.

It is the existing code path, in order, nothing new:
1. the twin: an existing one of this bot (pairs.json, by the bot's name), else `TwinService.create` for the one
   Grok bot of that name in the Grok app's own list (botport `twin create`), exactly as `hermes twin add` does.
   Only a twin made in this call is made bot-driven here (`make_bot_driven`); an existing twin that botport's
   twin pairing keeps is a FAIL before anything is written, and the owner converts it with
   `hermes twin bot-driven TWIN` (mcp_server.cmd_bot_driven), never this call;
2. a snapshot of what the next steps can change in that twin's Hermes folder;
3. botport `sync` with the bot's words as a `grok-bot-export` file (instructions, skills, memory; `--no-cron`),
   and the routines through `import_setup` (each made switched off, as an imported export's are);
4. the proof: botport `drift` (exit 0 = the Hermes bot matches what the Grok bot sent), the behaviour test
   (`TwinService.behaviour_test`, botport `test`; `hermes twin test`), and a secret grep of what was written
   and of the answer. Compare-with-Grok (`parity`) is reported, not gated on: it reads the Grok app's cache, which
   holds no instructions.
Any FAIL puts the snapshot back and says so.

Safety (the part of #42 this slice needs):
- The bots this server may write for are fixed by the owner when the connector is added (`--bot NAME`, the
  server-side allowlist). A call that names another bot is refused before anything is read. No argument is a path
  or a profile: the profile is the one the twin already has (or the one `create` gives it), never "default".
- Every text argument is screened by the plugin's own secret check (`secrets.redact`, line mode) before it is
  used; what was written and the answer are checked again afterwards.
- Size limits on every argument; a per-bot lock (a second call while one runs is refused, never interleaved);
  a second call with the same words is a sync (botport `sync` writes only what changed), never a second twin.
- No delete or stop: this module removes nothing but its own snapshots and its lock.
- Every call is appended to `one-prompt/calls.jsonl` (when, which bot, PASS/FAIL, counts; never the texts).
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any, Optional

from . import safe, secret_ref, store
from . import secrets as _secrets
from .engine import EngineError
from .model import now_iso, valid_id

TOOL = "twin_from_grok"
BACK_TOOL = "twin_back_to_grok"
ROUTINE_ID_MAX = 200
NAME_MAX = 100
INSTRUCTIONS_MAX = 200_000          # characters
SKILLS_MAX, SKILL_MAX = 100, 64_000
MEMORY_MAX, MEMORY_ITEM_MAX = 500, 4_000
ROUTINES_MAX, ROUTINE_FIELD_MAX = 50, 16_000
TOTAL_MAX = 2_000_000               # characters over every argument
SNAPSHOTS_KEPT = 3
# what botport sync, the routine import and the model choice can change in a twin's Hermes folder
SNAPSHOT_PARTS = ("SOUL.md", "skills", "cron", "memories", "config.yaml", "botport.lock.json", ".botport.lock",
                  "backups/botport", "botport-manual.md")  # (botport's restore points and its by-hand checklist)
DIGEST_SUFFIX = ".export-sha256"
LEFT_OUT = "[line left out: it looked like a password or key]"
SECRET_GREP_CAP = 1_000_000         # bytes of one written file that are grepped


class Refused(Exception):
    """A FAIL before anything was written."""


# ---- the bot's words ------------------------------------------------------------------------------------------
def _text(value: Any, cap: int, what: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise Refused(f"{what} must be text")
    if len(value) > cap:
        raise Refused(f"{what} is longer than {cap} characters")
    return value.replace("\x00", "")


def _list(value: Any, cap: int, what: str) -> list:
    if value is None:
        return []
    if not isinstance(value, list):
        raise Refused(f"{what} must be a list")
    if len(value) > cap:
        raise Refused(f"{what} has more than {cap} entries")
    return value


class _Scrub:
    """The plugin's secret check, line mode, on every text the bot sent; counts the lines it took out."""

    def __init__(self, refs: Any = None) -> None:
        self.lines, self.refs, self.item = 0, refs, ""

    def __call__(self, text: str) -> str:
        if not text:
            return text
        if self.refs is not None:  # a key the OS store can keep becomes ${NAME} (docs/SECRETS.md); the rest is hidden
            text = self.refs.take(text, self.item, "env")
        out = _secrets.redact(text, "[secret]", line_marker=LEFT_OUT)
        if out != text:
            self.lines += max(1, sum(1 for a, b in zip(text.split("\n"), out.split("\n")) if a != b))
        return out


def build_export(bot_name: str, instructions: Any, skills: Any, memory: Any, routines_meta: Any,
                 refs: Any = None) -> tuple[dict, dict]:
    """(a `grok-bot-export` v1 document of this one bot, counts). Size limits first, then the scrub on every text:
    with `refs` (secret_ref.Refs of the twin), a key is kept by reference first and the text says ${NAME}.
    Raises Refused on anything malformed or too large."""
    total = sum(len(json.dumps(v, ensure_ascii=False, default=str)) for v in (instructions, skills, memory,
                                                                              routines_meta))
    if total > TOTAL_MAX:
        raise Refused(f"the call is larger than {TOTAL_MAX} characters")
    scrub = _Scrub(refs)
    scrub.item = "instructions"
    ins = scrub(_text(instructions, INSTRUCTIONS_MAX, "instructions"))
    out_skills = []
    for s in _list(skills, SKILLS_MAX, "skills"):
        if isinstance(s, str):
            s = {"name": "", "instructions": s}
        if not isinstance(s, dict):
            raise Refused("each skill must be an object with a name and its text")
        name = safe.clean_name(_text(s.get("name"), NAME_MAX * 4, "a skill's name"), NAME_MAX)
        scrub.item = "skill:" + name
        body = scrub(_text(s.get("instructions") or s.get("content") or s.get("text"), SKILL_MAX, "a skill"))
        if not name or not body.strip():
            raise Refused("each skill needs a name and its text")
        out_skills.append({"name": name, "description": scrub(_text(s.get("description"), 1000, "a description")),
                           "instructions": body})
    mems = []
    scrub.item = "memories"
    for m in _list(memory, MEMORY_MAX, "memory"):
        if isinstance(m, dict):
            m = m.get("text") or m.get("content") or ""
        m = scrub(_text(m, MEMORY_ITEM_MAX, "a memory"))
        if m.strip() and m.strip() != LEFT_OUT:
            mems.append(m)
    routines = []
    scrub.item = "routines"
    for r in _list(routines_meta, ROUTINES_MAX, "routines_meta"):
        if not isinstance(r, dict):
            raise Refused("each routine must be an object")
        routines.append({k: scrub(_text(r.get(k), ROUTINE_FIELD_MAX, f"a routine's {k}"))
                         for k in ("name", "instruction", "trigger", "schedule_cron", "schedule_text", "timezone")
                         if r.get(k) is not None})
    doc = {"format": "grok-bot-export", "version": 1, "bots": [{
        "name": bot_name, "instructions": ins, "skills": out_skills, "memories": mems, "user_facts": [],
        "routines": routines, "apps": []}]}
    counts = {"instructions": bool(ins.strip()), "skills": len(out_skills), "memory": len(mems),
              "routines": len(routines), "scrubbed_lines": scrub.lines}
    return doc, counts


def check_name(bot_name: Any, allowed: list) -> str:
    """The bot's name as sent, when it is one the owner allowed for this server; else Refused."""
    if not isinstance(bot_name, str) or not bot_name.strip() or len(bot_name) > NAME_MAX:
        raise Refused("bot_name must be the bot's own name")
    name = " ".join(bot_name.split())
    if _secrets.has_secret(name) or name != safe.clean_name(name, NAME_MAX):
        raise Refused("bot_name must be the bot's own name")
    keys = {" ".join(str(a).split()).casefold() for a in allowed or []}
    if name.casefold() not in keys:
        raise Refused("the bot's name in the JSON is not the one after --bot (or the one this connector is set up for); "
                      "use your name exactly as Grok shows it in both")
    return name


# ---- lock, snapshot, log --------------------------------------------------------------------------------------
def _folder() -> Path:
    return store.ensure_dir(store.central_dir() / "one-prompt")


def _key(name: str) -> str:
    return hashlib.sha256(name.casefold().encode("utf-8")).hexdigest()[:16]


@contextlib.contextmanager
def bot_lock(name: str):
    """The twin's shared lock (botlock.py: also taken by hermes twin sync, quick, import and switch). A second
    call while one runs is refused, never interleaved; a lock left by a run that died is the OS's to drop."""
    from . import botlock
    try:
        with botlock.held(name, wait=False):
            yield
    except botlock.Busy:
        raise Refused("a twin run for this bot is already going; try again when it has finished")


ENGINE_LOCK = "grok-engine-port"  # one lock for every use of the Grok app's port (from-hermes, the chat-sync tick)


@contextlib.contextmanager
def engine_lock(wait: bool = True):
    """Held across a from-hermes run and a chat-sync pull, so a tick never restores (closes) the port while an
    export or ask is using it. A tick does not wait (it skips); from-hermes waits for a running tick."""
    from . import botlock
    try:
        with botlock.held(ENGINE_LOCK, wait=wait, timeout=None if wait else 0):
            yield
    except botlock.Busy:
        raise Refused("the Grok engine is in use by another twin run; try again when it has finished")


_SNAP_SVC: dict = {}  # snapshot folder -> the service it was taken with (restore puts pairs.json back through it)
MANIFEST = "manifest.json"


def _kind(path: Path) -> str:
    if path.is_symlink():
        return "link"
    if path.is_dir():
        return "dir"
    if path.is_file():
        return "file"
    return "absent" if not os.path.lexists(path) else "other"


def snapshot(pid: str, home: Path, svc: Any = None, parts: tuple = SNAPSHOT_PARTS, kind: str = "snapshots") -> Path:
    """Copy `parts` of the twin's Hermes folder to one-prompt/KIND/PID/STAMP, with a manifest of what each part was
    (a folder, a file, a symlink and its target, or absent). With `svc`, also kept: the twin's pairs.json entry
    (routine ids, `switched`, the last test) and its kept behaviour-test cases, so a FAIL puts those back too.
    KIND "converted" is the copy taken once before a twin becomes bot-driven (never put back by itself)."""
    base = store.ensure_dir(_folder() / kind / pid)
    dest = base / time.strftime("%Y%m%dT%H%M%S", time.gmtime())
    n = 0
    while dest.exists():
        n += 1
        dest = base / (time.strftime("%Y%m%dT%H%M%S", time.gmtime()) + f"-{n}")
    dest.mkdir(mode=0o700)
    manifest: dict = {"parts": {}, "extras": {}}
    for part in parts:
        src, kind = home / part, _kind(home / part)
        manifest["parts"][part] = {"kind": kind}
        if kind == "link":
            manifest["parts"][part]["target"] = os.readlink(src)
        elif kind == "dir":
            shutil.copytree(src, dest / "home" / part, symlinks=True)
        elif kind == "file":
            store.ensure_dir((dest / "home" / part).parent)
            shutil.copy2(src, dest / "home" / part)
    if svc is not None:
        _SNAP_SVC[str(dest)] = svc
        with store.locked():
            entry = svc._registry().get(pid)
        manifest["pair"] = {"pid": pid, "entry": entry}
        for i, extra in enumerate(_extras(svc, pid)):
            kind = _kind(extra) if _kind(extra) in ("file", "absent") else "other"
            manifest["extras"][str(extra)] = {"kind": kind, "copy": f"extra-{i}"}
            if kind == "file":
                shutil.copy2(extra, dest / f"extra-{i}")
    store.atomic_write_json(dest / MANIFEST, manifest)
    (dest / ".complete").write_bytes(now_iso().encode("utf-8"))
    old = sorted(p for p in base.iterdir() if p.is_dir() and not p.is_symlink())
    for p in old[:-SNAPSHOTS_KEPT]:
        _SNAP_SVC.pop(str(p), None)
        shutil.rmtree(p, ignore_errors=True)
    return dest


def _extras(svc: Any, pid: str) -> list:
    """Files outside the Hermes folder a call can change: the kept behaviour-test cases and their export digest."""
    out = []
    with contextlib.suppress(AttributeError):
        battery = svc._battery_path(pid)
        out += [battery, battery.with_name(battery.name + DIGEST_SUFFIX)]
    return out


def _remove(cur: Path) -> None:
    if cur.is_symlink() or cur.is_file():
        cur.unlink()
    elif cur.is_dir():
        shutil.rmtree(cur)


def restore(snap: Path, home: Path, svc: Any = None) -> None:
    """Put the parts the snapshot recorded back as they were: folders and files copied back, symlinks recreated
    with their old target, a part that was absent removed. A part the manifest does not record as one of those
    (a pipe, a device, anything it could not copy) is left alone: nothing is deleted that was not snapshotted."""
    if not (snap / ".complete").is_file() or not (snap / MANIFEST).is_file():
        raise OSError("the snapshot is not complete")
    manifest = store.read_json(snap / MANIFEST, {}) or {}
    for part, rec in (manifest.get("parts") or {}).items():
        if part not in SNAPSHOT_PARTS or not isinstance(rec, dict):
            continue
        kind, cur, was = rec.get("kind"), home / part, snap / "home" / part
        if kind == "link":
            target = rec.get("target")
            if not isinstance(target, str):
                continue
            if cur.is_symlink() and os.readlink(cur) == target:
                continue
            _remove(cur)
            store.ensure_dir(cur.parent)
            os.symlink(target, cur)
        elif kind == "dir" and was.is_dir():
            _remove(cur)
            store.ensure_dir(cur.parent)
            shutil.copytree(was, cur, symlinks=True)
        elif kind == "file" and was.is_file():
            _remove(cur)
            store.ensure_dir(cur.parent)
            shutil.copy2(was, cur)
        elif kind == "absent":
            _remove(cur)
    svc = svc if svc is not None else _SNAP_SVC.get(str(snap))
    for path, rec in (manifest.get("extras") or {}).items():
        cur = Path(path)
        if rec.get("kind") == "file" and (snap / str(rec.get("copy"))).is_file():
            shutil.copy2(snap / str(rec["copy"]), cur)
        elif rec.get("kind") == "absent" and (cur.is_file() or cur.is_symlink()):
            cur.unlink()
    pair = manifest.get("pair")
    if svc is not None and isinstance(pair, dict) and valid_id(pair.get("pid")):
        pid = pair["pid"]
        with store.locked():
            reg = svc._registry()
            if reg.get(pid) != pair.get("entry"):
                if pair.get("entry") is None:
                    reg.pop(pid, None)
                else:
                    reg[pid] = pair["entry"]
                svc._save_registry(reg)
        with contextlib.suppress(AttributeError):
            svc.invalidate()


def log_call(entry: dict) -> None:
    with contextlib.suppress(OSError):
        path = _folder() / "calls.jsonl"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_BINARY", 0), 0o600)
        with os.fdopen(fd, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def written_secrets(home: Path, snap: Optional[Path] = None) -> int:
    """How many files among SOUL.md and the skills that THIS call wrote or changed look like they hold a password
    or key. A file that is byte for byte as it was in `snap` (the snapshot taken before) is not this call's: Hermes'
    own bundled skills, say, carry example keys in their text and would fail every twin otherwise."""
    files = [home / "SOUL.md"] + [p for p in (home / "skills").rglob("SKILL.md")] if (home / "skills").is_dir() \
        else [home / "SOUL.md"]
    hits = 0
    for p in files:
        try:
            if not p.is_file() or p.is_symlink():
                continue
            data = p.read_bytes()[:SECRET_GREP_CAP]
            was = snap / "home" / p.relative_to(home) if snap is not None else None
            if was is not None and was.is_file() and not was.is_symlink() and \
                    was.read_bytes()[:SECRET_GREP_CAP] == data:
                continue
            if _secrets.has_secret(data.decode("utf-8", "replace")):
                hits += 1
        except OSError:
            continue
    return hits


FROM_HERMES_TAG = "(from hermes)"  # the bot tags a fact Hermes handed it (sync_both.HOW); the same fact on its way back


def _memory_key(note: str) -> str:
    """A memory note as compared for the union: spaces and case ignored, and a leading '(from Hermes)' tag too, so a
    fact that went Hermes -> Grok -> Hermes is not added a second time."""
    key = " ".join(note.split()).casefold()
    return key[len(FROM_HERMES_TAG):].lstrip() if key.startswith(FROM_HERMES_TAG) else key


def merge_memory(home: Path, notes: list) -> dict:
    """The bot's memory, where the twin's own `memory` tool reads it: Hermes' MEMORY.md (its separator and its
    lock, through xs_memory's helpers). botport carries memory only as a skill the model rarely opens. A union:
    notes already there stay, the bot's new ones are added while Hermes' character limit allows; a note the memory
    privacy check holds back is never written. -> {"added", "left_out"}"""
    from . import xs_memory as xm
    path = xm._mem_path(home, "memory")
    limit = xm._limits(home)["memory"]
    with xm._mem_lock(path) as got:
        if not got:
            raise Refused("Hermes is writing this twin's memory right now; try again in a moment")
        have = xm._read(path)
        if have is None:
            raise Refused("this twin's memory file cannot be read safely, so it was not changed")
        known = {_memory_key(e) for e in have}
        out, left = list(have), 0
        for n in notes:
            key = _memory_key(n)
            if not key or key in known or xm.why_held(n):
                continue
            if len(xm.DELIM.join(out + [n])) > limit:
                left += 1
                continue
            out.append(n)
            known.add(key)
        if len(out) > len(have):
            store.ensure_dir(path.parent)
            xm._write(path, out)
    return {"added": len(out) - len(have), "left_out": left}


# ---- bot-driven twins (botport v0.2.1 has no "apply this export" call for a profile its twin pairing owns) -------
MIRROR_STATE = "botport.mirror.json"  # in a profile: botport's twin pairing owns it; apply/sync/drift refuse it
CONVERT_PARTS = SNAPSHOT_PARTS + (MIRROR_STATE, "botport-mirror-conflicts.md", "botport")
CONVERT_HOW = "hermes twin bot-driven"  # the owner's own step (mcp_server.cmd_bot_driven); a call never converts


def follows_botport(home: Path) -> bool:
    """Does botport's twin pairing (or the owner's own `botport mirror`) keep this Hermes folder?"""
    return (home / MIRROR_STATE).exists()


def refuse_botport_paired(name: str, home: Path) -> None:
    """An existing twin that follows its Grok bot through botport is the owner's to convert, once, by choice: the
    one-prompt calls FAIL on it before anything is written (no `botport twin remove`, no snapshot, no pairs.json)."""
    if follows_botport(home):
        raise Refused(f"this twin follows its Grok bot through botport, so nothing was changed. To keep it in step "
                      f"with one prompt instead, the owner runs {CONVERT_HOW} \"{name}\" in their own terminal")


def make_bot_driven(svc: Any, pid: str, home: Path) -> bool:
    """Make this twin one the Grok bot keeps in step itself (driver "bot"): once, a full copy of its Hermes folder's
    botport parts (one-prompt/converted/PID/STAMP, never put back by itself), then `botport twin remove`, which keeps
    the profile, its chats and everything it holds as a normal profile, so botport's apply/sync/drift (the path the
    bot's own words go through) accept it. Idempotent: a twin already bot-driven is only marked. -> converted now.
    Called by `twin_from_grok` for a twin it made in the same call, and by the owner's `hermes twin bot-driven`."""
    owned = follows_botport(home)
    if owned:
        snapshot(pid, home, None, CONVERT_PARTS, "converted")
        try:
            svc.engine_for(pid).remove(pid)
        except EngineError as exc:  # (no twin pair owns it: the owner's own `botport mirror` does; leave it alone)
            raise EngineError("mirrored", "this twin's Hermes bot is a mirrored profile kept by botport mirror, not "
                              "by its twin pairing, so nothing was changed", "Stop that mirror first (botport "
                              "mirror init --undo), or give the twin another profile.") from exc
        if (home / MIRROR_STATE).exists():
            raise Refused("botport still keeps this twin's Hermes bot to itself, so nothing was changed")
    note_bot(svc, pid, {"driver": "bot"})
    return owned


def note_bot(svc: Any, pid: Optional[str], fields: dict) -> None:
    """Keep `fields` (driver, last_call) on this twin's pairs.json entry."""
    if not pid:
        return
    with contextlib.suppress(OSError), store.locked():
        reg = svc._registry()
        e = reg.get(pid)
        if isinstance(e, dict) and any(e.get(k) != v for k, v in fields.items()):
            e.update(fields)
            svc._save_registry_quiet(reg)  # (not _save_registry: its fleet push writes into the twin's Hermes folder)


# ---- the twin -------------------------------------------------------------------------------------------------
def _same(a: Any, b: str) -> bool:
    return isinstance(a, str) and " ".join(a.split()).casefold() == b.casefold()


def find_or_create(svc: Any, name: str) -> tuple[str, bool]:
    """(the pair id of this bot's twin, whether it was made now). Never a second twin for one bot."""
    hits = [pid for pid, e in svc._registry().items() if _same((e.get("grok") or {}).get("name"), name)]
    if len(hits) == 1:
        return hits[0], False
    if len(hits) > 1:
        raise Refused("more than one twin has that bot's name; run hermes twin status to see them")
    bots = [b for b in (svc.grok_list().get("bots") or []) if _same(b.get("name"), name)]
    if not bots:
        raise Refused("no Grok bot of that name is in the Grok app on this computer")
    if len(bots) > 1:
        raise Refused("more than one Grok bot has that name; rename one in Grok first")
    if bots[0].get("twinned_pair_id"):
        return bots[0]["twinned_pair_id"], False
    made = [p["pair_id"] for p in (svc.create([bots[0]["grok_id"]]).get("pairs") or []) if valid_id(p.get("pair_id"))]
    if len(made) != 1:
        raise Refused("Hermes could not make the twin")
    return made[0], True


def same_server_as_owner(svc: Any, pid: str, home: Path, res: Optional[dict] = None) -> bool:
    """botport `twin create` gives a new twin the owner's model id and provider name but not the server it is on
    (`base_url`): a model on the owner's own server would not answer the twin (behaviour test 0/N). When the
    owner's default model is on such a server, point the twin at it the way the Twins page's model picker does
    (`set_model` with that endpoint: provider "custom" + base_url). A key that server needs goes with it by
    reference (twin#76, model_key.py): `res["model_key"]` names it for the PASS line, never its value. -> changed"""
    from . import endpoints as _ep
    from . import hermes_side as hs
    m = hs.profile_model(home) or ""
    hit = next((e for e in _ep.configured() if e["model"] == m and e["provider"].startswith("custom")), None)
    if not m or hit is None:
        return False
    got = svc.set_model(pid, m, _endpoint={"_base_url": hit["base_url"]})
    if res is not None and isinstance(got.get("key"), dict):
        res["model_key"] = got["key"]
    return got.get("state") == "set"


def _behaviour(svc: Any, pid: str, export_file: Path) -> dict:
    """`hermes twin test` (behaviour.BehaviourTestMixin, botport `test`). The cases are made from the export the
    bot just sent whenever it differs from the one the kept cases were made from (its sha256 is kept next to them),
    so new instructions get new cases. A call that FAILs puts the old cases back with the snapshot."""
    battery = svc._battery_path(pid)
    marker = battery.with_name(battery.name + DIGEST_SUFFIX)
    digest = hashlib.sha256(export_file.read_bytes()).hexdigest()
    current = battery.is_file() and marker.is_file() and marker.read_text(encoding="utf-8").strip() == digest
    res = svc.behaviour_test(pid, from_export=None if current else str(export_file))
    if not current and battery.is_file():
        store.atomic_write_text(marker, digest + "\n")
    return res


def keeps_failing_import(test: dict, cases: list) -> bool:
    """twin#74: a behaviour test that still fails after its retry keeps the import (the twin marked "test failing")
    when every failed case is a model-behaviour one and the setting `import_test_failing` is "keep" (the default).
    A data case (persona, instructions, skills, the gateway turn), an unknown failure or "rollback" rolls back."""
    from . import config
    if config.get("import_test_failing") == "rollback" or not cases:
        return False
    total, passed = test.get("total"), test.get("passed")
    if not (isinstance(total, int) and isinstance(passed, int)) or total - passed != len(cases):
        return False  # (every failure must be accounted for by a listed case)
    return all(c.get("kind") == "behaviour" for c in cases)


def twin_from_grok(svc: Any, allowed: list, bot_name: Any, *args: Any, **kwargs: Any) -> dict:
    """The whole call. -> {"ok", "line", ...details}. Never raises for a FAIL; the line says what happened. After a
    PASS the origin note (twin#64) in every twin follows this install's versions."""
    res = _twin_from_grok(svc, allowed, bot_name, *args, **kwargs)
    if isinstance(res, dict) and res.get("ok"):
        from . import origin
        origin.refresh(svc)
    return res


def _twin_from_grok(svc: Any, allowed: list, bot_name: Any, instructions: Any = None, skills: Any = None,
                    memory: Any = None, routines_meta: Any = None, move: Any = False,
                    history: Any = None, grok_paused: Any = None) -> dict:
    started = time.monotonic()
    stack, after = contextlib.ExitStack(), []  # (after: steps that run only on the final PASS, in _finish)
    res: dict = {"ok": False, "restored": False}
    shown_name = "this bot"
    snap: Optional[Path] = None
    home: Optional[Path] = None
    try:
        name = check_name(bot_name, allowed)
        shown_name = name
        if move not in (False, None, True):
            raise Refused("move must be true or false")
        refs = routine_refs(routines_meta)
        paused = routine_refs([{"id": r} for r in _list(grok_paused, ROUTINES_MAX, "grok_paused")
                               if isinstance(r, str)])
        res["grok_paused"] = paused
        if move:  # the bot pauses its Grok routines FIRST: Hermes turns them on only once none runs in Grok
            missing = [r for r in refs if r not in paused]
            if missing:
                raise Refused("move needs every Grok routine paused first (UpdateRoutine); not confirmed paused: "
                              + ", ".join(missing) + ". Nothing was turned on in Hermes")
        doc, counts = build_export(name, instructions, skills, memory, routines_meta)
        res["counts"] = counts
        with _locked_until_finished(stack, name):
            pid, made = find_or_create(svc, name)
            entry = svc._registry().get(pid) or {}
            prof = (entry.get("hermes") or {}).get("profile")
            home = svc._profile_home(prof) if isinstance(prof, str) and prof != "default" else None
            if home is None or not valid_id(prof):
                raise Refused("this twin has no Hermes bot of its own")
            if not made:  # (before pair_id is in res: a refusal leaves pairs.json as it was too)
                refuse_botport_paired(name, home)
            res.update(pair_id=pid, profile=prof, created=made)
            store.ensure_dir(home)
            srefs = secret_ref.Refs(pid)  # keys by reference (docs/SECRETS.md): the bot's words again, for this twin
            doc, counts = build_export(name, instructions, skills, memory, routines_meta, srefs)
            res["counts"] = counts
            eng = svc.engine_for(pid)
            if not hasattr(eng, "bundle_sync"):
                raise Refused("this twin is the sample; twin a real Grok bot")
            res["converted"] = make_bot_driven(svc, pid, home)  # (only a twin made just now can still be owned)
            if made:
                with contextlib.suppress(Exception):  # (a twin without it still syncs; its test then says so)
                    res["model_server"] = same_server_as_owner(svc, pid, home, res)
            snap = snapshot(pid, home, svc)
            export_file = store.ensure_dir(_folder() / "exports") / f"{pid}.json"
            store.atomic_write_json(export_file, doc)  # kept (0600): `botport drift` can be rerun by hand
            from .sync_both import write_spec
            spec = str(write_spec(svc, pid, prof))
            synced = eng.bundle_sync(prof, str(export_file), spec)
            res["changed"] = not synced.get("in_sync", False)
            if synced.get("_rc") == 3:  # botport: conflicts left (both sides edited); reported, then FAIL below
                res["conflicts"] = max(1, len([i for i in synced.get("items") or [] if isinstance(i, dict)
                                               and str(i.get("status", "")).lower() == "conflict"]))
            if counts["routines"]:
                imp = svc.import_setup(pid, json.dumps(doc), apply=True, bot=name,
                                       skip=["instructions", "connectors"])
                res["routines"] = {"added": imp.get("added", 0),
                                   "not_added": sum(1 for r in imp.get("routines", []) if r.get("state") not in
                                                    ("added", "exists"))}
            res["memory"] = merge_memory(home, doc["bots"][0]["memories"])
            # safe profile defaults by rule on what was just imported (twin#54), before the behaviour test or
            # anything else runs in this profile; the owner's own choice is kept. config.yaml is in the snapshot.
            from . import profile_safety
            got = profile_safety.apply_default(prof, home)
            res["safety"] = got["preset"]
            if got.get("capabilities") and got["preset"] != "open":  # twin#71: the PASS line names them
                res["capabilities"] = profile_safety.capability_words(got["capabilities"])
            if got.get("headless"):
                res["headless"] = got["headless"]
            drift = eng.bundle_drift(prof, str(export_file), spec)
            res["drift"] = "clean" if drift.get("_rc") == 0 else "differs"
            test = _behaviour(svc, pid, export_file)
            cases = [c for c in test.get("failed_cases") or [] if isinstance(c, dict)]
            still = {c.get("id") for c in cases}
            res["test"] = {"passed": test.get("passed"), "total": test.get("total"),
                           "retried": len([i for i in test.get("retried") or [] if i not in still])}
            if cases:
                res["test"]["failed"] = [f"{c.get('id')} ({c.get('reason')})" for c in cases]
            kept_failing = not test.get("ok") and keeps_failing_import(test, cases)
            with contextlib.suppress(EngineError, Refused):
                par = svc.parity(pid)
                res["compare"] = {"passed": par.get("passed"), "total": par.get("total")}
            leaks = written_secrets(home, snap)
            fails = []
            if res["drift"] != "clean":
                fails.append("the Hermes bot does not match what the Grok bot sent (botport drift)")
            if not test.get("ok") and not kept_failing:
                fails.append(f"behaviour test {test.get('passed')}/{test.get('total')}"
                             + (f" (failed twice: {', '.join(res['test']['failed'])})" if cases else ""))
            if res.get("conflicts"):
                fails.append(f"botport left {res['conflicts']} conflict(s): edited in both Hermes and Grok since the "
                             "last run; make the two the same, then try again")
            if leaks:
                fails.append(f"{leaks} written file(s) look like they hold a password or key")
            if res.get("routines", {}).get("not_added"):
                fails.append(f"{res['routines']['not_added']} routine(s) could not be added")
            if fails:
                raise Refused("; ".join(fails))
            if kept_failing:  # twin#74: kept, and the twin marked "test failing" (only model-behaviour cases failed)
                res["test"]["kept_failing"] = True
                after.append(lambda: note_bot(svc, pid, {"test_failing": [c.get("id") for c in cases]}))
            elif test.get("ok"):
                after.append(lambda: note_bot(svc, pid, {"test_failing": []}))
            _no_secret_in(res)  # before anything is turned on: a blanked answer must be a restoring FAIL
            res["secrets"] = srefs.report()
            if move:
                res["move"] = _move_routines(svc, pid, refs)
            after.append(lambda: _keep_refs(srefs, home))  # .env only on the final PASS (never in a snapshot)
            if history:
                after.append(lambda: res.__setitem__("history", _history(name, history, pid, prof)))
            res["ok"] = True
    except Exception as exc:  # noqa: BLE001  (the bot always gets one line, and the twin its snapshot back)
        _why(res, exc)
    try:
        return _finish(TOOL, shown_name, res, snap, home, started, _line, svc, after)
    finally:
        stack.close()


@contextlib.contextmanager
def _locked_until_finished(stack: contextlib.ExitStack, name: str):
    """`bot_lock(name)` entered on `stack`: it stays held after the block, through `_finish` (restore, the PASS-only
    steps, the git commit), and the caller closes the stack. No other run of this bot gets in between."""
    stack.enter_context(bot_lock(name))
    yield


def _history(name: str, history: Any, pid: str, prof: str) -> dict:
    """The bot's own conversations -> Hermes chats (twin/history.py). Never fails the twin: errors are reported."""
    from . import history as history_mod
    try:
        return history_mod.import_history(name, history, pid=pid, profile=prof)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)[:200]}


def _why(res: dict, exc: Exception) -> None:
    if isinstance(exc, Refused):
        res["why"] = str(exc)
    elif isinstance(exc, EngineError):
        res["why"] = safe.clean_summary(exc.message, 300) + (f" ({safe.clean_summary(exc.hint, 200)})"
                                                              if exc.hint else "")
    else:
        res["why"] = f"unexpected error: {safe.clean_summary(type(exc).__name__, 60)}"


def _keep_refs(refs: Any, home: Path) -> dict:
    """On PASS only: the values the twin's text now refers to (${NAME}) into its profile's own .env, Hermes' place
    for keys, and the list of names saved. Never in a snapshot (a FAIL before this leaves them only in the OS
    store). -> names and counts, never a value."""
    refs.to_env(home)
    refs.done()
    return refs.report()


def _refs_note(res: dict) -> str:
    """"; 1 key kept by reference (OPENAI_API_KEY)": names only, never a value; or why none could be kept."""
    r = res.get("secrets") or {}
    if r.get("names"):
        return f"; {len(r['names'])} key(s) kept by reference ({', '.join(r['names'])})"
    return f"; keys hidden, not kept ({r['not_kept']})" if r.get("not_kept") else ""


def _no_secret_in(res: dict) -> None:
    if _secrets.has_secret(json.dumps(res, ensure_ascii=False, default=str)):
        raise Refused("the answer looked like it held a password or key, so nothing was changed and it is not shown")


def _finish(tool: str, shown_name: str, res: dict, snap: Optional[Path], home: Optional[Path], started: float,
            line: Any, svc: Any = None, after: Optional[list] = None) -> dict:
    """Shared end of both tools, still under the bot's lock: the answer's secret grep, snapshot back on FAIL, the
    line and ITS grep, and only then the PASS-only steps (`after`: the profile's .env, the move record, the bot's
    chats) and the git commit. So a FAIL found here has nothing to undo but the snapshot, and the git note (a push
    warning, say) can never turn a PASS into a FAIL: a note that looks secret is left out of the line."""
    def fail(why: str) -> dict:
        return {**{k: res.get(k) for k in ("pair_id", "profile", "created", "grok_paused")}, "ok": False,
                "restored": False, "why": why}
    if res["ok"] and _secrets.has_secret(json.dumps(res, ensure_ascii=False, default=str)):
        res = fail("the answer looked like it held a password or key, so it is not shown")
    if res["ok"] and _secrets.has_secret(line(shown_name, res)):
        res = fail("the answer looked like it held a password or key, so it is not shown")
    if not res["ok"] and snap is not None and home is not None:
        try:
            restore(snap, home)
            res["restored"] = True
        except OSError:
            res["restore_failed"] = str(snap)
    res["line"] = line(shown_name, res)
    if not res["ok"] and _secrets.has_secret(res["line"]):  # (a refusal's own words: never shown either)
        res["line"] = "FAIL: the answer looked like it held a password or key, so it is not shown."
    if res["ok"]:
        for step in after or []:
            with contextlib.suppress(Exception):  # (each is reported in its own way; none undoes the PASS)
                step()
        hist = res.get("history")
        if isinstance(hist, dict) and hist.get("conversations"):
            res["line"] += (f" Conversations: {hist.get('conversations', 0)} sent, {hist.get('new_messages', 0)} new "
                            "message(s) in Hermes chats \"From Grok: …\""
                            + (f", {hist['failed']} not imported" if hist.get("failed") else "") + ".")
        from .git_mirror import after_pass  # optional git history (off by default)
        kind = "back" if tool == BACK_TOOL else "move" if res.get("move") else "twin" if res.get("created") else "sync"
        note = after_pass(res.get("pair_id"), home, kind)
        res["line"] += note if not _secrets.has_secret(note) else " Git history: committed (its note is not shown)."
    if svc is not None and res.get("pair_id"):
        note_bot(svc, res["pair_id"], {"last_call": {"at": now_iso(), "result": "PASS" if res["ok"] else "FAIL",
                                                    "tool": tool}})
    log_call({"at": now_iso(), "tool": tool, "bot": safe.clean_name(shown_name, NAME_MAX),
              "result": "PASS" if res["ok"] else "FAIL", "pair_id": res.get("pair_id"),
              "counts": res.get("counts"), "drift": res.get("drift"), "test": res.get("test"),
              "restored": res.get("restored"), "ms": int((time.monotonic() - started) * 1000)})
    return res


def _line(name: str, res: dict) -> str:
    if not res["ok"]:
        tail = ((" The new twin was put back to empty." if res.get("created") else
                 " The twin was put back as it was before this call.") if res.get("restored") else "")
        if res.get("restore_failed"):
            tail = " The twin could NOT be put back by itself; run hermes twin doctor."
        if res.get("grok_paused"):
            tail += (" Your Grok routines are still paused and Hermes did not take them over: re-enable them in Grok "
                     "with UpdateRoutine: " + ", ".join(res["grok_paused"]) + ".")
        return f"FAIL: {name}: {res.get('why') or 'not twinned'}.{tail}"
    c = res.get("counts") or {}
    test = res.get("test")
    tested = f"behaviour test {test['passed']}/{test['total']}" + (
        f" ({test['retried']} case(s) passed only on a retry)" if test.get("retried") else "")
    if test.get("kept_failing"):
        tested += (f", test failing: {', '.join(test.get('failed') or [])} (model behaviour; the import is kept, "
                   "run hermes twin test again)")
    what = (f"{c.get('skills', 0)} skills, {c.get('memory', 0)} memories, "
            f"{(res.get('routines') or {}).get('added', 0)} routines added switched off")
    scrubbed = f"; {c['scrubbed_lines']} line(s) left out as password-like" if c.get("scrubbed_lines") else ""
    full = (res.get("memory") or {}).get("left_out")
    scrubbed += f"; {full} memories not kept in Hermes' memory (it is full)" if full else ""
    verb = "twinned to" if res.get("created") else ("synced with" if res.get("changed") else "already level with")
    moved = ""
    if res.get("move"):
        m = res["move"]
        moved = (f" Moved: {m['hermes_routines_on']} routine(s) on in Hermes; paused in Grok: "
                 f"{', '.join(m['grok_routines_paused']) or 'none'}.")
    scrubbed += _refs_note(res)
    from .model_key import note as _key_note
    scrubbed += _key_note(res.get("model_key"))
    if res.get("capabilities"):
        scrubbed += f"; capabilities: {res['capabilities']}"
    if res.get("headless"):
        scrubbed += f"; {res['headless']}"
    return (f"PASS: {name} {verb} Hermes (profile {res.get('profile')}): {what}; matches what the bot sent; {tested}{scrubbed}."
            + moved)



# ---- move to Hermes, and back (issue #44) ---------------------------------------------------------------------
def routine_refs(routines_meta: Any) -> list:
    """What the Grok bot calls each routine it sent (its `id`, else its name): the ones it pauses or re-enables."""
    refs = []
    for r in _list(routines_meta, ROUTINES_MAX, "routines_meta"):
        ref = r.get("id") or r.get("name") if isinstance(r, dict) else None
        ref = safe.clean_name(_text(ref, ROUTINE_ID_MAX * 4, "a routine's id"), ROUTINE_ID_MAX) if ref else ""
        if ref and not _secrets.has_secret(ref) and ref not in refs:
            refs.append(ref)
    return refs


def _moved_file(pid: str) -> Path:
    return store.ensure_dir(_folder() / "moved") / f"{pid}.json"


def _move_routines(svc: Any, pid: str, refs: list) -> dict:
    """`hermes twin switch` for this twin: turn on its switched-off routines; remember the Grok ones to pause."""
    jobs = [j["job_id"] for j in svc.checklist(pid)["switch"]["hermes_jobs_paused"]]
    got = svc.switch(pid, jobs) if jobs else {"resumed": [], "failed": []}
    if got.get("failed"):
        raise Refused("Hermes refused to turn on routine(s) " + ", ".join(f["job_id"] for f in got["failed"]))
    store.atomic_write_json(_moved_file(pid), {"at": now_iso(), "grok_routines": refs})
    return {"hermes_routines_on": len(got.get("resumed") or []), "grok_routines_paused": refs}


def twin_back_to_grok(svc: Any, allowed: list, bot_name: Any, instructions: Any = None, skills: Any = None,
                      memory: Any = None) -> dict:
    """Bring a moved bot back: `sync_bot` both ways, `switch --undo` (Hermes routines paused), and the bundle the
    Grok bot applies itself (UpdateMemory, UpdateSkill, UpdateRoutine to re-enable). Hermes-side memory and skills
    are in the bundle only when the owner allowed Hermes -> Grok for this twin (`hermes twin to-grok TWIN allow`);
    otherwise they stay in Hermes and the bundle carries only `routines_to_enable` (the bot's own routines it paused
    when it moved). -> {"ok", "line", "bundle"}"""
    from .sync_both import HOW, sync_bot
    started = time.monotonic()
    stack, after = contextlib.ExitStack(), []
    res: dict = {"ok": False, "restored": False}
    shown_name, snap, home = "this bot", None, None
    try:
        name = check_name(bot_name, allowed)
        shown_name = name
        doc, counts = build_export(name, instructions, skills, memory, None)
        res["counts"] = counts
        with _locked_until_finished(stack, name):
            hits = [pid for pid, e in svc._registry().items() if _same((e.get("grok") or {}).get("name"), name)]
            if len(hits) != 1:
                raise Refused("this bot has no Hermes twin to come back from" if not hits else
                              "more than one twin has that bot's name; run hermes twin status to see them")
            pid = hits[0]
            prof = ((svc._registry().get(pid) or {}).get("hermes") or {}).get("profile")
            home = svc._profile_home(prof) if isinstance(prof, str) and prof != "default" else None
            if home is None or not valid_id(prof):
                raise Refused("this twin has no Hermes bot of its own")
            refuse_botport_paired(name, home)  # (never converted here: the owner's hermes twin bot-driven does)
            res.update(pair_id=pid, profile=prof)
            srefs = secret_ref.Refs(pid)
            doc, counts = build_export(name, instructions, skills, memory, None, srefs)
            res["counts"] = counts
            note_bot(svc, pid, {"driver": "bot"})
            snap = snapshot(pid, home, svc)
            synced = sync_bot(svc, pid, doc, write_env=False)  # (.env: only on the final PASS)
            res["drift"] = "clean" if synced.get("ok") else "differs"
            if not synced.get("ok"):  # nothing is paused in Hermes when the two sides are not level
                raise Refused(safe.clean_summary(str(synced.get("line")).removeprefix("FAIL: "), 300))
            moved = store.read_json(_moved_file(pid), {}) if _moved_file(pid).is_file() else {}
            refs = [r for r in (moved.get("grok_routines") or []) if isinstance(r, str)][:ROUTINES_MAX]
            fg = synced.get("for_grok") or {}
            mem, skl = fg.get("memory") or [], fg.get("skills") or []
            if not _to_grok_allowed(svc, pid):  # the owner's one Hermes -> Grok switch; off: nothing is handed over
                res["kept_in_hermes"] = {"memory": len(mem), "skills": len(skl)}
                mem, skl = [], []
            res["bundle"] = {"memory": mem, "skills": skl,
                             "routines_to_enable": refs, "how": HOW,
                             **({"secrets_needed": fg["secrets_needed"], "secrets_how": fg.get("secrets_how")}
                                if fg.get("secrets_needed") else {})}
            _no_secret_in(res)  # before Hermes pauses anything: Grok's routines must not end up paused everywhere
            undo = svc.switch(pid, None, undo=True)
            res["hermes_routines_paused"] = len(undo.get("paused") or [])
            fails = []
            if undo.get("failed"):
                fails.append("Hermes could not pause routine(s) " + ", ".join(f["job_id"] for f in undo["failed"]))
            if fails:
                raise Refused("; ".join(fails))
            res["secrets"] = srefs.report()
            env_names = list(synced.get("refs_used") or [])
            after.append(lambda: (_keep_refs(srefs, home), secret_ref.write_names(home, env_names)))

            def _forget_move() -> None:
                with contextlib.suppress(OSError):
                    _moved_file(pid).unlink()
            after.append(_forget_move)  # the move record goes only once the bot is back for good
            res["ok"] = True
    except Exception as exc:  # noqa: BLE001
        _why(res, exc)
    try:
        return _finish(BACK_TOOL, shown_name, res, snap, home, started, _back_line, svc, after)
    finally:
        stack.close()


def _to_grok_allowed(svc: Any, pid: str) -> bool:
    """Whether the owner allowed Hermes -> Grok for this twin (anything at all on `hermes twin to-grok TWIN allow`).
    Read only, from the same state the to-grok commands keep; a state that cannot be read counts as not allowed."""
    from . import h2g
    try:
        return bool(h2g.H2G(svc.central, None, hermes=lambda p: {}, bot=lambda p: "").allowed(pid))
    except Exception:  # noqa: BLE001
        return False


def _back_line(name: str, res: dict) -> str:
    if not res["ok"]:
        tail = " The twin was put back as it was before this call." if res.get("restored") else ""
        if res.get("restore_failed"):
            tail = " The twin could NOT be put back by itself; run hermes twin doctor."
        return f"FAIL: {name}: {res.get('why') or 'not brought back'}.{tail}"
    b = res["bundle"]
    enable = ", ".join(b["routines_to_enable"]) or "none"
    kept = res.get("kept_in_hermes")
    what = (f"{kept['memory']} memories and {kept['skills']} skills stay in Hermes: Hermes → Grok is off for this "
            f"twin (the owner turns it on with hermes twin to-grok {res['pair_id']} allow)" if kept else
            f"{len(b['memory'])} memories and {len(b['skills'])} skills to write with UpdateMemory/UpdateSkill")
    return (f"PASS: {name} back to Grok: {what}; {res['hermes_routines_paused']} routine(s) paused in Hermes; re-enable in "
            f"Grok with UpdateRoutine: {enable}{_refs_note(res)}"
            + (f"; set up in Grok by name only: {', '.join(b['secrets_needed'])}" if b.get("secrets_needed") else "")
            + ".")
