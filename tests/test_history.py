"""The Grok bot's own chat history in the one-prompt flow (twin/history.py): scrub, botport-shaped SQLite store,
Hermes import through the transcripts path, idempotent re-import, limits. Invented bots and fake secrets only."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from twin_testlib import home  # noqa: F401
from hermes_plugins.grok_bot_twin.twin import history as H
from hermes_plugins.grok_bot_twin.twin import mcp_server, one_prompt
from hermes_plugins.grok_bot_twin.twin import transcripts as tr

BOT = "test-scout"
FAKE_KEY = "sk-" + "a" * 30


def _conv(title, *texts, started="2000-01-02T00:00:00Z"):
    return {"title": title, "started": started,
            "messages": [{"role": ("user", "assistant")[i % 2], "text": t, "time": 946771200 + 60 * i}
                         for i, t in enumerate(texts)]}


@pytest.fixture
def runner(monkeypatch):
    calls = []

    def fake(tail, profile):
        if tail[:2] == ["sessions", "import"]:
            lines = [json.loads(x) for x in Path(tail[-1]).read_text(encoding="utf-8").splitlines()]
            calls.append((profile, lines))
            return 0, f"Imported Claude Code session as 20001231_120000_{len(calls):08x}\n"
        return 0, ""

    monkeypatch.setattr(tr, "_run_hermes", fake)
    return calls


def _texts(lines):
    return [x["message"]["content"] for x in lines[1:]]


def test_imports_scrubbed_and_stores_sealed(home, runner):
    res = H.import_history(BOT, [_conv("Soup", "How long to simmer leek soup?", "About 20 minutes."),
                                 _conv("Keys", f"my key is {FAKE_KEY}", "Do not share that.", started="x2")])
    assert res == {"conversations": 2, "new_messages": 4, "redacted": 1, "imported": 2, "failed": 0}
    assert all(p == BOT for p, _ in runner)
    every = [t for _, lines in runner for t in _texts(lines)]
    assert H.REDACTED in every and not any(FAKE_KEY in t for t in every)
    db = tr.folder() / H.DB_NAME
    raw = db.read_bytes()
    assert b"leek" not in raw and FAKE_KEY.encode() not in raw
    cols = [r[1] for r in sqlite3.connect(str(db)).execute("PRAGMA table_info(messages)")]
    assert {"agent_id", "seq", "entry_id", "role", "timestamp_ms", "body"} <= set(cols)


def test_reimport_adds_only_new_messages(home, runner):
    first = _conv("Soup", "How long to simmer leek soup?", "About 20 minutes.")
    H.import_history(BOT, [first])
    again = H.import_history(BOT, [first])
    assert again["new_messages"] == 0 and again["imported"] == 0 and len(runner) == 1
    longer = _conv("Soup", "How long to simmer leek soup?", "About 20 minutes.", "And with potatoes?")
    res = H.import_history(BOT, [longer])
    assert res["new_messages"] == 1 and res["imported"] == 1
    assert _texts(runner[-1][1]) == ["And with potatoes?"]
    assert "continued" in runner[-1][1][0]["summary"]


def test_failed_hermes_import_is_retried_next_time(home, runner, monkeypatch):
    monkeypatch.setattr(tr, "_run_hermes", lambda tail, profile: (1, "boom"))
    res = H.import_history(BOT, [_conv("Soup", "Leek soup?", "Yes.")])
    assert res["failed"] == 1
    calls = []
    monkeypatch.setattr(tr, "_run_hermes", lambda t, p: (calls.append(t), (0, "session as 20001231_120000_abcd1234"))[1])
    res = H.import_history(BOT, [_conv("Soup", "Leek soup?", "Yes.")])
    assert res["imported"] == 1 and res["new_messages"] == 0


@pytest.mark.parametrize("bad", ["not a list", [_conv("x", "y")] * (H.MAX_CONVS + 1),
                                 [_conv("big", *(["a"] * (H.MAX_MSGS + 1)))],
                                 [_conv("huge", "z" * 90_000)] * 30])
def test_limits_refuse_before_anything_is_stored(home, runner, bad):
    with pytest.raises(H.HistoryError):
        H.import_history(BOT, bad)
    assert not runner and not (tr.folder() / H.DB_NAME).exists()


def test_history_argument_is_wired_into_the_one_prompt_tool(monkeypatch):
    assert "history" in mcp_server.ARGS
    assert mcp_server.TOOL_SPEC["inputSchema"]["properties"]["history"]["type"] == "array"
    seen = {}
    monkeypatch.setattr(H, "import_history", lambda bot, convs, **kw: seen.update(bot=bot, kw=kw) or {"imported": 1})
    assert one_prompt._history("Acme Support", [_conv("a", "b")], "acme-support", "acme-support") == {"imported": 1}
    assert seen == {"bot": "Acme Support", "kw": {"pid": "acme-support", "profile": "acme-support"}}
    monkeypatch.setattr(H, "import_history", lambda *a, **k: (_ for _ in ()).throw(H.HistoryError("too big")))
    assert one_prompt._history("Acme Support", [], "p", "p") == {"error": "too big"}
