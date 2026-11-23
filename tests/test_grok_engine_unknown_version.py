"""Live 24 Nov 2026: after a Grok app update to a version botport had not tested, every ask was refused
(exit 4, unknown_version_writes) and twin had no way past it. Now twin runs botport's read-only canary once and
retries; a failed canary sends nothing and says why."""
import json

from twin import grok_engine as ge

REFUSED = (4, json.dumps({"exit": 4, "proof": "FAIL: refused: unknown_version_writes (Grok Bot 9.9.9 is not tested)"}))
ASKED = (0, json.dumps({"exit": 0, "proof": "PASS: reply received; bot idle", "reply": "hi"}))
CANARY_OK = (0, json.dumps({"exit": 0, "proof": "PASS: canary 9.9.9 read 7/7"}))
CANARY_BAD = (1, json.dumps({"exit": 1, "proof": "FAIL: canary 9.9.9 read 4/7; bots failed"}))


def engine(script):
    calls = []

    def runner(argv, _t):
        cmd = argv[2]
        calls.append(cmd)
        rc, out = script[cmd].pop(0)
        return rc, out.encode(), b"", False
    return ge.GrokEngine("/x/botport", runner=runner), calls


def test_untested_version_runs_the_canary_once_then_retries():
    eng, calls = engine({"ask": [REFUSED, ASKED], "canary": [CANARY_OK]})
    res = eng.ask("Acme Support", "hello", 60)
    assert res.ok and calls == ["ask", "canary", "ask"]
    assert "canary PASS" in res.proof


def test_a_failed_canary_sends_nothing_more_and_says_why():
    eng, calls = engine({"ask": [REFUSED], "canary": [CANARY_BAD]})
    res = eng.ask("Acme Support", "hello", 60)
    assert not res.ok and calls == ["ask", "canary"]
    assert "nothing was sent" in res.proof and "has not tested" in res.proof


def test_other_refusals_are_not_retried():
    other = (4, json.dumps({"exit": 4, "proof": "FAIL: refused: allowlist"}))
    eng, calls = engine({"ask": [other]})
    res = eng.ask("Acme Support", "hello", 60)
    assert not res.ok and calls == ["ask"]
