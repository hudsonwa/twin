"""quota 05: the weekly Grok usage line in `hermes twin status` (read through the engine: 0 turns)."""
from __future__ import annotations

import json

from twin_testlib import home  # noqa: F401
from hermes_plugins.grok_bot_twin.twin import config, grok_engine as ge, usage


def eng_answering(rc, data, seen):
    def runner(argv, timeout):
        seen.append(argv)
        return rc, json.dumps(data).encode(), b"", False
    return ge.GrokEngine("/invented/botport", runner=runner)


def test_line_through_the_engine_and_never_a_turn(home):
    seen = []
    got = usage.read(None, eng_answering(0, {"percent_used": 42.4, "resets_at": "2026-11-23T00:00:00Z",
                                             "available": True, "botport_turns_week": 7}, seen))
    assert got["ok"] and got["line"].startswith("Grok this week: 42% used (resets ")
    assert got["line"].endswith("; twin used 7 turns") and "warning" not in got
    assert [a[1:3] for a in seen] == [["grok", "usage"]]  # one read, no ask or send


def test_warning_past_the_owners_budget(home):
    config.set_override({"grok_turn_budget_week": 30})
    got = usage.read(None, eng_answering(0, {"percent_used": 90, "resets_at": None, "botport_turns_week": 31}, []))
    assert "resets unknown" in got["line"] and "past your budget of 30" in got["warning"]
    config.set_override({})
    got = usage.read(None, eng_answering(0, {"percent_used": 90, "botport_turns_week": 5, "usage_budget_week": 5}, []))
    assert "past your budget of 5" in got["warning"]


def test_older_botport_without_a_turn_count(home):
    got = usage.read(None, eng_answering(0, {"percent_used": 10, "resets_at": "2026-11-23T00:00:00Z"}, []))
    assert got["ok"] and "twin's turns not counted by this botport" in got["line"]


def test_engine_missing_or_port_closed_is_a_clear_note(home, monkeypatch):
    def missing(svc):
        raise ge.Unavailable("botport is not on this computer")
    monkeypatch.setattr(ge, "from_service", missing)
    got = usage.read(object())
    assert not got["ok"] and got["note"] == "Grok usage not shown: botport is not on this computer."
    closed = usage.read(None, eng_answering(5, {"proof": "FAIL: port closed"}, []))
    assert not closed["ok"] and closed["note"].startswith("Grok usage not shown: the engine could not read it")
