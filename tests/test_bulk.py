"""quick --all, link-computer and stop NAME (twin/bulk.py): one command each, the last line PASS: or FAIL:.

Invented bots only (Acme Support, Recipe Planner, Test Scout). botport is mocked: the bot list comes from a stand-in
grok_list, quick's own steps from a stand-in cmd_quick, and the fleet from stand-in share and code calls.
"""
from __future__ import annotations

import argparse
import io
import inspect
from contextlib import redirect_stderr, redirect_stdout

import pytest

from twin_testlib import cli, home, service, svc  # noqa: F401
from hermes_plugins.grok_bot_twin.twin import bulk, fleet, quick_cli, tasks
from hermes_plugins.grok_bot_twin.twin import engine as E

BOTS = {"bots": [{"grok_id": "g-acme", "name": "Acme Support"}, {"grok_id": "g-recipe", "name": "Recipe Planner"},
                 {"grok_id": "g-demo", "name": "Test Scout", "demo": True}]}


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = cli.main(argv)
    return rc, out.getvalue(), err.getvalue()


def last(out: str) -> str:
    return out.strip().splitlines()[-1]


@pytest.fixture
def bots(svc, monkeypatch):
    monkeypatch.setattr(svc, "grok_list", lambda *a, **k: BOTS)
    seen = []

    def fake_quick(a, fail=()):
        seen.append(a)
        print(f"{'FAIL' if a.name in fake_quick.fail else 'PASS'}: quick setup of \"{a.name}\"")
        return 1 if a.name in fake_quick.fail else 0
    fake_quick.fail = set()
    monkeypatch.setattr(quick_cli, "cmd_quick", fake_quick)
    return seen, fake_quick


# ---------------------------------------------------------------------------------------------- quick --all

def test_quick_all_runs_quick_for_every_real_bot_and_passes(bots):
    seen, _fq = bots
    rc, out, _ = run(["quick", "--all", "--model", "grok-4.7", "--yes"])
    assert rc == 0, out
    assert [a.name for a in seen] == ["Acme Support", "Recipe Planner"]  # never the sample's bot
    assert all(a.yes and a.model == "grok-4.7" and not a.all for a in seen)
    assert last(out) == "PASS: quick setup of 2 of 2 bots"


def test_quick_all_fails_when_one_bot_fails(bots):
    _seen, fq = bots
    fq.fail.add("Recipe Planner")
    rc, out, _ = run(["quick", "--all", "--yes"])
    assert rc == 1 and " ✗ Recipe Planner" in out and last(out) == "FAIL: quick setup of 1 of 2 bots"


def test_quick_all_with_no_bots_fails(svc, monkeypatch):
    monkeypatch.setattr(svc, "grok_list", lambda *a, **k: {"bots": []})
    rc, out, _ = run(["quick", "--all", "--yes"])
    assert rc == 1 and last(out).startswith("FAIL:")


def test_quick_all_refuses_one_bots_export(bots):
    rc, _out, err = run(["quick", "--all", "--stdin", "--yes"])
    assert rc != 0 and "quick NAME" in err


def test_quick_needs_a_name_or_all(bots):
    rc, _out, err = run(["quick", "--yes"])
    assert rc != 0 and "--all" in err


def test_quick_all_is_refused_in_a_requests_turn(bots, monkeypatch):
    monkeypatch.setattr(tasks, "asked_turn", lambda: True)
    rc, _out, err = run(["quick", "--all", "--yes"])
    assert rc != 0 and "another computer" in err


def test_quick_all_library_function(bots):
    res = bulk.quick_all(model="grok-4.7")
    assert res["ok"] and res["verdict"] == "PASS: quick setup of 2 of 2 bots"


# ---------------------------------------------------------------------------------------------- link-computer

class Fleet:
    def __init__(self, svc, monkeypatch, joins_after=None, role="source", sharing=False):
        self.followers, self.polls, self.joins_after = {}, 0, joins_after
        self.shared = []
        monkeypatch.setattr(svc, "fleet", lambda: {"role": role, "share": {"on": sharing}})
        monkeypatch.setattr(svc, "fleet_share", lambda on: self.shared.append(on) or {})
        monkeypatch.setattr(svc, "fleet_code", lambda: {"code": {"code": "7KQ4-M2XD-P9RA"}})
        monkeypatch.setattr(fleet, "load", self._load)
        monkeypatch.setattr(bulk, "POLL_S", 0)

    def _load(self):
        self.polls += 1
        if self.joins_after is not None and self.polls > self.joins_after:
            self.followers = {"m-0123456789ab": {"name": "Laptop"}}
        return {"share": {"followers": dict(self.followers)}}


def test_link_computer_prints_the_code_and_passes_when_a_computer_links(svc, monkeypatch):
    f = Fleet(svc, monkeypatch, joins_after=3)
    rc, out, _ = run(["link-computer"])
    assert rc == 0, out
    assert f.shared == [True] and "hermes twin setup --link 7KQ4-M2XD-P9RA --yes" in out
    assert last(out) == "PASS: another computer is linked"


def test_link_computer_wait_is_bounded(svc, monkeypatch):
    Fleet(svc, monkeypatch, joins_after=None, sharing=True)
    clock = iter(range(0, 10_000, 30))
    monkeypatch.setattr(bulk.time, "monotonic", lambda: next(clock))
    rc, out, _ = run(["link-computer", "--wait", "2"])
    assert rc == 1 and last(out).startswith("FAIL: no computer used the code in 2 min")


def test_link_computer_turns_sharing_off_again_on_timeout(svc, monkeypatch):
    """L3: sharing this command switched on goes back off when no computer links."""
    f = Fleet(svc, monkeypatch, joins_after=None, sharing=False)
    clock = iter(range(0, 10_000, 30))
    monkeypatch.setattr(bulk.time, "monotonic", lambda: next(clock))
    rc, out, _ = run(["link-computer", "--wait", "1"])
    assert rc == 1 and f.shared == [True, False] and "sharing is off again" in last(out)
    f2 = Fleet(svc, monkeypatch, joins_after=None, sharing=True)  # it was on before: left on
    monkeypatch.setattr(bulk.time, "monotonic", lambda: next(clock))
    run(["link-computer", "--wait", "1"])
    assert f2.shared == []


def test_link_computer_wait_cannot_outlast_the_code(svc):
    with pytest.raises(SystemExit), redirect_stderr(io.StringIO()):
        cli.build_parser().parse_args(["link-computer", "--wait", "11"])


def test_link_computer_on_a_follower_fails(svc, monkeypatch):
    Fleet(svc, monkeypatch, role="follower")
    rc, out, _ = run(["link-computer"])
    assert rc == 1 and last(out) == "FAIL: link another computer"


def test_link_computer_library_function(svc, monkeypatch):
    Fleet(svc, monkeypatch, joins_after=1)
    res = bulk.link_computer(wait=60)
    assert res["ok"] and res["verdict"] == "PASS: another computer is linked"


# ---------------------------------------------------------------------------------------------- stop NAME

class Stop:
    def __init__(self, svc, monkeypatch):
        self.calls = []
        monkeypatch.setattr(cli, "_resolve", lambda s, given: "acme-support")
        monkeypatch.setattr(cli, "_names", lambda s: {"acme-support": "Acme Support"})
        monkeypatch.setattr(svc, "remove", self._remove)
        monkeypatch.setattr(svc.demo, "pair_ids", lambda: [])

    def _remove(self, pid, dry_run=False, keep_data=False):
        self.calls.append((pid, dry_run, keep_data))
        return {"removed": ["records of acme-support"]}


def test_stop_needs_the_twin_named(svc, monkeypatch):
    s = Stop(svc, monkeypatch)
    rc, out, err = run(["stop", "--yes"])
    assert rc == 2 and "Say which twin" in err and last(out).startswith("FAIL:")
    assert s.calls == []


def test_stop_named_keeps_data_by_default(svc, monkeypatch):
    s = Stop(svc, monkeypatch)
    rc, out, _ = run(["stop", "Acme Support", "--yes"])
    assert rc == 0 and s.calls[-1] == ("acme-support", False, True)
    assert "Kept: its full transcripts" in out and last(out) == 'PASS: stop "Acme Support"'


def test_stop_remove_data_deletes_it(svc, monkeypatch):
    s = Stop(svc, monkeypatch)
    rc, out, _ = run(["stop", "Acme Support", "--yes", "--remove-data"])
    assert rc == 0 and s.calls[-1] == ("acme-support", False, False)


def test_stop_dry_run_changes_nothing(svc, monkeypatch):
    s = Stop(svc, monkeypatch)
    rc, out, _ = run(["stop", "Acme Support", "--dry-run"])
    assert rc == 0 and [c[1] for c in s.calls] == [True] and last(out).endswith("(dry run)")


def test_stop_library_function_is_a_dry_run_and_never_removes_data(svc, monkeypatch):
    s = Stop(svc, monkeypatch)
    assert bulk.stop_twin("Acme Support")["verdict"].endswith("(dry run)")
    assert [c[1] for c in s.calls] == [True]
    assert bulk.stop_twin("Acme Support", confirm=True)["ok"]
    assert s.calls[-1] == ("acme-support", False, True)
    assert "remove_data" not in inspect.signature(bulk.stop_twin).parameters
    assert not bulk.stop_twin("")["ok"]


def test_no_model_tool_deletes():
    from hermes_plugins.grok_bot_twin import tools  # noqa: F401
    import hermes_plugins.grok_bot_twin as plugin
    src = inspect.getsource(plugin.register)
    assert "stop" not in src and "remove" not in src and "bulk" not in src


@pytest.mark.parametrize("keep", [True, False])
def test_service_remove_keeps_transcripts_and_sync_choices_only_when_asked(svc, monkeypatch, keep):
    from hermes_plugins.grok_bot_twin.twin import sync_panel, transcripts

    class Eng:
        def remove(self, pid, dry_run):
            return {"removed": []}
    svc._save_registry({"acme-support": {"pair_id": "acme-support", "grok": {"id": "g-acme", "name": "Acme Support"},
                                         "hermes": {"profile": "acme-support"}, "created_at": "2026-11-01T00:00:00Z"}})
    monkeypatch.setattr(svc, "engine_for", lambda pid: Eng())
    forgot = []
    monkeypatch.setattr(sync_panel, "forget_twin", lambda pid: forgot.append("syncs"))
    monkeypatch.setattr(transcripts, "forget", lambda pid: forgot.append("transcripts"))
    svc.remove("acme-support", False, keep_data=keep)
    assert forgot == ([] if keep else ["syncs", "transcripts"])
    assert "acme-support" not in svc.pair_ids()
