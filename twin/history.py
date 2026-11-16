"""The Grok bot's own chat history, Grok -> Hermes, in the one-prompt flow.

Grok keeps a bot's conversations server-side, so the bot reads its own recent conversations and passes them in
(`history` on twin_from_grok): [{"title", "started", "messages": [{"role", "text", "time"}]}].

import_history() then, for one twin:
1. scrubs each message the botport v0.2.1 way (`export --with-history`): a message holding credential-like text is
   replaced whole by botport's marker; tool output / hidden reasoning is dropped and lengths capped
   (transcripts._norm_messages);
2. stores the messages the botport way, in SQLite: a `messages` table of (agent_id, seq, entry_id, role,
   timestamp_ms, body), the shape of the box's search-index.db that `--with-history` snapshots. The body is sealed
   with the transcripts archive's key (transcripts.seal_row), so nothing is readable at rest;
3. imports them as Hermes chats through the plugin's transcripts path (transcripts.ingest_grok, then
   transcripts.import_to_hermes -> `hermes sessions import --from claude`).

Idempotent: entry_id is a digest of (conversation, role, time, text), so a message already stored is skipped. A
conversation seen before that gained messages is imported as a continuation holding only the new ones; nothing
already in Hermes is imported twice. Continuous chat sync (twin/chat_sync.py) sends only the newest messages of a
conversation, so two more rules keep those runs free of duplicates:
- a conversation's own `id` (the Grok chat's id, when the bot or the engine has one) is its key; without it the
  key is (`started`, title) as before, so the sync sends the conversation's real `started`, not its first new
  message's time;
- a message is also skipped when the same (role, whole second, text) is already stored for this twin under any
  conversation (`seen`: an HMAC with the archive's key, never the text in the clear). That covers a title or a
  time format that changed between runs, and an older import made before the conversation had an id. Limits: MAX_CONVS conversations, MAX_MSGS messages each, MAX_CHARS in all.
"""
from __future__ import annotations

import hashlib
import hmac
import sqlite3
from typing import Any, Optional

from . import secrets, transcripts as tr

MAX_CONVS = 200
MAX_MSGS = 2000
MAX_CHARS = 2_000_000  # over every message text (one_prompt.TOTAL_MAX)
REDACTED = "[redacted by botport: credential-like text]"
DB_NAME = "grok-history.sqlite"
SCHEMA = ("CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY, agent_id TEXT NOT NULL, conv TEXT NOT NULL, "
          "seq INTEGER NOT NULL, entry_id TEXT NOT NULL, role TEXT NOT NULL, timestamp_ms INTEGER, body BLOB, "
          "UNIQUE(agent_id, entry_id));"
          "CREATE TABLE IF NOT EXISTS conversations (agent_id TEXT NOT NULL, conv TEXT NOT NULL, title TEXT, "
          "parts INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(agent_id, conv));"
          "CREATE TABLE IF NOT EXISTS seen (agent_id TEXT NOT NULL, digest TEXT NOT NULL, "
          "PRIMARY KEY(agent_id, digest));"
          "CREATE TABLE IF NOT EXISTS seen_filled (agent_id TEXT PRIMARY KEY);")
CONV_ID_MAX = 200


class HistoryError(ValueError):
    pass


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(tr._private_dir(tr.folder()) / DB_NAME))
    conn.executescript(SCHEMA)
    return conn


def scrub(text: str) -> str:
    return REDACTED if secrets.has_secret(text) else text


def _clean(conversations: Any) -> list:
    """The bot's list -> [{"key", "title", "messages": [{"role", "text", "at"}]}], scrubbed and capped."""
    if not isinstance(conversations, list):
        raise HistoryError("history must be a list of conversations")
    if len(conversations) > MAX_CONVS:
        raise HistoryError(f"history has more than {MAX_CONVS} conversations")
    out, total = [], 0
    for c in conversations:
        if not isinstance(c, dict):
            continue
        raw = c.get("messages")
        if isinstance(raw, list) and len(raw) > MAX_MSGS:
            raise HistoryError(f"a conversation has more than {MAX_MSGS} messages")
        msgs = tr._norm_messages(raw)
        for m in msgs:
            m["text"] = scrub(m["text"])
            total += len(m["text"])
        if total > MAX_CHARS:
            raise HistoryError(f"history is larger than {MAX_CHARS} characters")
        if not msgs:
            continue
        title = tr._title_of(c.get("title"), msgs)
        cid = c.get("id")
        if isinstance(cid, str) and cid.strip() and len(cid) <= CONV_ID_MAX and not secrets.has_secret(cid):
            key = hashlib.sha256(f"id\n{cid.strip()}".encode("utf-8", "replace")).hexdigest()[:24]
        else:
            started = tr._clean_text(c.get("started"), 64) or str(msgs[0]["at"])
            key = hashlib.sha256(f"{started}\n{title}".encode("utf-8", "replace")).hexdigest()[:24]
        out.append({"key": key, "title": title, "messages": msgs})
    return out


def _entry_id(conv: str, m: dict) -> str:
    return hashlib.sha256(f"{conv}\n{m['role']}\n{m['at']}\n{m['text']}".encode("utf-8", "replace")).hexdigest()[:32]


def _seen_digest(key: bytes, pid: str, role: str, at: Any, text: str) -> Optional[str]:
    """(role, whole second, text) of one twin's message, keyed with the archive's key; None without a time (two
    messages without a time are told apart only within their conversation)."""
    if at is None:
        return None
    msg = f"{pid}\n{role}\n{int(at)}\n{text}".encode("utf-8", "replace")
    return hmac.new(key, b"grok-bot-twin seen 1\n" + msg, hashlib.sha256).hexdigest()[:32]


def _fill_seen(conn: sqlite3.Connection, key: bytes, pid: str) -> None:
    """Once per twin: the `seen` digests of messages stored before that table existed (opened with the key)."""
    if conn.execute("SELECT 1 FROM seen_filled WHERE agent_id = ?", (pid,)).fetchone():
        return
    for conv, seq, role, ts, body in conn.execute("SELECT conv, seq, role, timestamp_ms, body FROM messages "
                                                  "WHERE agent_id = ?", (pid,)).fetchall():
        text = tr.open_row(key, tr._bind(pid, "history:" + conv, seq, role), body)
        d = _seen_digest(key, pid, role, ts / 1000 if ts is not None else None, text) if text is not None else None
        if d:
            conn.execute("INSERT OR IGNORE INTO seen (agent_id, digest) VALUES (?, ?)", (pid, d))
    conn.execute("INSERT OR IGNORE INTO seen_filled (agent_id) VALUES (?)", (pid,))


def _store_new(conn: sqlite3.Connection, key: bytes, pid: str, conv: dict) -> tuple:
    """Insert the messages not stored yet (in this conversation, or for this twin at all: `seen`).
    -> (new messages, part number: 0 for a first import)."""
    _fill_seen(conn, key, pid)
    have = {r[0] for r in conn.execute("SELECT entry_id FROM messages WHERE agent_id = ? AND conv = ?",
                                       (pid, conv["key"]))}
    seq0 = len(have)
    new = []
    for m in conv["messages"]:
        eid = _entry_id(conv["key"], m)
        if eid in have:
            continue
        have.add(eid)
        digest = _seen_digest(key, pid, m["role"], m["at"], m["text"])
        if digest is not None:
            if conn.execute("SELECT 1 FROM seen WHERE agent_id = ? AND digest = ?", (pid, digest)).fetchone():
                continue
            conn.execute("INSERT INTO seen (agent_id, digest) VALUES (?, ?)", (pid, digest))
        at = int(m["at"] * 1000) if m["at"] is not None else None
        conn.execute("INSERT INTO messages (agent_id, conv, seq, entry_id, role, timestamp_ms, body) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (pid, conv["key"], seq0 + len(new), eid, m["role"], at,
                      tr.seal_row(key, tr._bind(pid, "history:" + conv["key"], seq0 + len(new), m["role"]),
                                  m["text"])))
        new.append(m)
    row = conn.execute("SELECT parts FROM conversations WHERE agent_id = ? AND conv = ?",
                       (pid, conv["key"])).fetchone()
    part = row[0] if row else 0
    if new:
        conn.execute("INSERT INTO conversations (agent_id, conv, title, parts) VALUES (?, ?, ?, 1) "
                     "ON CONFLICT(agent_id, conv) DO UPDATE SET parts = parts + 1", (pid, conv["key"], None))
    return new, part


def import_history(bot: str, conversations: Any, *, pid: Optional[str] = None,
                   profile: Optional[str] = None) -> dict:
    """Scrub, store and import the bot's own conversations as Hermes chats of its twin (pid / profile; both
    default to the bot name). -> {"conversations", "new_messages", "redacted", "imported", "failed"}."""
    pid = pid or bot
    profile = profile or pid
    convs = _clean(conversations)
    redacted = sum(1 for c in convs for m in c["messages"] if m["text"] == REDACTED)
    if not tr.is_on(pid):
        tr.switch(pid, True)  # the bot passed its history because the owner asked for it
    pid, _rec, key = tr._need_on(pid)
    parts = []
    with tr._LOCK, _db() as conn:
        for c in convs:
            new, part = _store_new(conn, key, pid, c)
            if new:
                title = c["title"] if part == 0 else f"{c['title']} (continued {part + 1})"
                parts.append({"id": f"history:{c['key']}:{part}", "title": title, "messages":
                              [{"role": m["role"], "text": m["text"], "at": m["at"]} for m in new]})
    res = {"conversations": len(convs), "new_messages": sum(len(p["messages"]) for p in parts),
           "redacted": redacted, "imported": 0, "failed": 0}
    if parts:
        tr.ingest_grok(pid, {"conversations": parts})
    with _db() as conn:  # every part of these conversations: one a failed import left behind is retried
        known = conn.execute("SELECT conv, parts FROM conversations WHERE agent_id = ?", (pid,)).fetchall()
    mine = {c["key"] for c in convs}
    ids = [tr._conv_id(pid, "grok", tr._origin(key, f"history:{k}:{i}")) for k, n in known if k in mine
           for i in range(n)]
    if not ids:
        return res
    done = tr.import_to_hermes(pid, profile, ids=ids)
    res["imported"], res["failed"] = len(done["imported"]), len(done["failed"])
    return res
