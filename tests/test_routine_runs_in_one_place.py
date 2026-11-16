"""SM-3: a routine runs in one place. Hermes to Grok's runner (h2g.json) and routines between computers
(routines.json) each say where a twin's routine runs; neither may switch it on where the other says it runs
elsewhere. Invented bots only, in a throwaway Hermes folder (twin_testlib's `home`)."""
from __future__ import annotations

import json

import pytest

from twin_testlib import home, service, store, svc  # noqa: F401
from hermes_plugins.grok_bot_twin.twin import fleet, h2g, importer, routines, routines_jobs as rj
from hermes_plugins.grok_bot_twin.twin.engine import EngineError
from hermes_plugins.grok_bot_twin.twin.model import pair_ref

PID = "acme-support"
BOT = "b-acme-support-1"
ME = "m-aaaaaaaaaaaa"
LAPTOP = "m-bbbbbbbbbbbb"
RID = "j-00000000000000aa"
SCHED = {"kind": "cron", "expr": "0 9 * * *", "display": "0 9 * * *"}


@pytest.fixture(autouse=True)
def _no_panel_choice(monkeypatch):
    """The owner chose Hermes -> Grok for routines in What syncs (the panel gate is tested in test_h2g.py)."""
    try:
        from hermes_plugins.grok_bot_twin.twin import sync_panel
    except ImportError:
        return
    monkeypatch.setattr(sync_panel, "wanted", lambda pid, item: "both")


@pytest.fixture(autouse=True)
def _lock_order(monkeypatch):
    """store.not_inside must never fire in these tests (also where a caller would swallow its error)."""
    fired = []
    real = store.not_inside

    def watch(what):
        try:
            real(what)
        except RuntimeError:
            fired.append(what)
            raise
    monkeypatch.setattr(store, "not_inside", watch)
    yield
    assert fired == []


def _job(enabled: bool) -> dict:
    return {"id": "job-1", "name": "Morning digest", "prompt": "Say good morning to the team.", "schedule": SCHED,
            "enabled": enabled, "state": "scheduled" if enabled else "paused"}


def _machine() -> None:
    st = fleet.load()
    st["machine"]["id"] = ME
    fleet.save(st)


def _routines_item(holder: str, runs_on: str, job: str = "job-1") -> None:
    src = routines._blank_src()
    src["items"][RID] = {"name": "Morning digest", "prompt": "Say good morning to the team.", "schedule": SCHED,
                         "skills": [], "timezone": None, "twin": pair_ref(PID), "job": job, "on": True,
                         "version": 1, "updated_at": "2000-01-01T09:00:00Z", "runs_on": runs_on, "holder": holder,
                         "epoch": 1, "moved_at": 0}
    routines.save({"on": True, "can_run": False, "src": src, "dst": None, "restore": []})


@pytest.fixture
def acme(svc, home, monkeypatch):  # noqa: F811
    """Acme Support: a real twin whose routine runs in Hermes on this computer, allowed for Hermes to Grok, with a
    pretend Grok bot that has the routine (paused)."""
    _machine()
    store.atomic_write_json(svc.central / "pairs.json", {"pairs": [
        {"pair_id": PID, "grok": {"id": BOT, "name": "Acme Support"}, "hermes": {"profile": PID},
         "job_ids": ["job-1"]}]})
    prof = home / "profiles" / PID
    (prof / "cron").mkdir(parents=True)
    (prof / "SOUL.md").write_text("<!-- botport:begin persona-name -->\nAcme Support\n<!-- botport:end persona-name -->\n", encoding="utf-8")
    jobs = prof / "cron" / "jobs.json"
    jobs.write_text(json.dumps({"jobs": [_job(True)]}), encoding="utf-8")
    w = h2g.FakeGrokWriter()
    w.put_bot(BOT, name="Acme Support", routines=[{"key": "morning-digest", "name": "Morning digest",
                                                   "schedule": "0 9 * * *", "prompt": "Say good morning to the team.",
                                                   "enabled": False}])
    svc.h2g_test_writer = w
    calls = []

    def act(action, job_id, profile, ctx=None):
        calls.append(action)
        jobs.write_text(json.dumps({"jobs": [_job(action == "resume")]}), encoding="utf-8")
        return True, ""

    monkeypatch.setattr(importer, "_cron_action", act)
    svc.to_grok_allow(PID, ["routines"])
    return svc, jobs, w, calls


# ---- scenario A: routines between computers has it on the laptop; Hermes to Grok may not switch it on in Grok ----
def test_sm3_a_routine_held_by_another_computer_is_not_moved_to_grok(acme):
    svc, jobs, w, calls = acme
    _routines_item(holder=LAPTOP, runs_on=LAPTOP)
    state, job_file, grok = (svc.central / h2g.STATE_FILE).read_bytes(), jobs.read_bytes(), w.read(BOT)
    with pytest.raises(EngineError) as e:
        svc.to_grok_runner(PID, "Morning digest", "grok")
    assert e.value.code == "runs_elsewhere" and "another of your computers" in e.value.message
    assert (svc.central / h2g.STATE_FILE).read_bytes() == state and jobs.read_bytes() == job_file
    assert w.read(BOT) == grok and calls == []
    # a move under way to the laptop (the holder is still here) is refused the same way
    _routines_item(holder=ME, runs_on=LAPTOP)
    with pytest.raises(EngineError) as e:
        svc.to_grok_runner(PID, "Morning digest", "grok")
    assert e.value.code == "runs_elsewhere" and w.read(BOT) == grok and calls == []


def test_sm3_a_routine_this_computer_runs_moves_to_grok_as_before(acme):
    svc, jobs, w, calls = acme
    _routines_item(holder=ME, runs_on=ME)
    r = svc.to_grok_runner(PID, "Morning digest", "grok")
    assert r["runner"] == "grok" and calls == ["pause"] and w.read(BOT)["routines"][0]["enabled"] is True
    # and with no routines between computers at all
    svc.to_grok_runner(PID, "morning-digest", "hermes")
    routines.state_path().unlink()
    assert svc.to_grok_runner(PID, "morning-digest", "grok")["runner"] == "grok"


# ---- scenario B: Hermes to Grok runs it in Grok; routines' coming home does not switch the Hermes job on --------------
def _coming_home(svc, home, runner):  # noqa: F811
    """Test Scout's routine ran on the laptop and has come home (holder and runs_on are this computer); its Hermes
    job is still paused by the plugin. `runner`: where Hermes to Grok says it runs (None: never moved)."""
    pid, prof_id = "test-scout", "test-scout"
    store.atomic_write_json(svc.central / "pairs.json", {"pairs": [
        {"pair_id": pid, "grok": {"id": "b-test-scout-1", "name": "Test Scout"}, "hermes": {"profile": prof_id}}]})
    if runner:
        store.atomic_write_json(svc.central / h2g.STATE_FILE, {"v": h2g.V, "runner": {pid: {"morning-digest": runner}}})
    prof = home / "profiles" / prof_id
    (prof / "cron").mkdir(parents=True)
    job = rj.new_record({"name": "Morning digest", "prompt": "Say good morning.", "schedule": SCHED},
                        f"{rj.MARK}runs on Laptop")
    (prof / "cron" / "jobs.json").write_text(json.dumps({"jobs": [job]}), encoding="utf-8")
    _machine()
    tid = pair_ref(pid)
    st = fleet.load()
    st["share"] = {"list": {"twins": {tid: {"name": "Test Scout", "pair_id": pid, "profile": prof_id}}},
                   "followers": {}}
    R = {"on": True, "can_run": False, "dst": None, "restore": [], "src": routines._blank_src()}
    R["src"]["items"][RID] = {"name": "Morning digest", "twin": tid, "job": job["id"], "on": True, "runs_on": ME,
                              "holder": ME, "epoch": 2, "moved_at": 0}
    with fleet.locked():
        routines._progress(R, st)
        routines._progress(R, st)  # (a second pass writes nothing more)
    return rj.find(rj.load(prof), job["id"])


def test_sm3_b_a_routine_that_runs_in_grok_stays_paused_when_it_comes_home(svc, home):  # noqa: F811
    job = _coming_home(svc, home, "grok")
    assert not rj.runnable(job)
    assert "runs in Grok" in job["paused_reason"] and job["paused_reason"] == routines.IN_GROK_PAUSED


def test_sm3_b_a_routine_hermes_runs_is_switched_on_when_it_comes_home_as_before(svc, home):  # noqa: F811
    assert rj.runnable(_coming_home(svc, home, "hermes"))


def test_sm3_b_a_routine_never_moved_to_grok_is_switched_on_when_it_comes_home_as_before(svc, home):  # noqa: F811
    assert rj.runnable(_coming_home(svc, home, None))
