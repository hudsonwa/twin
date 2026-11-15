"""One prompt against a REAL botport v0.2.1, in a temporary HERMES_HOME: twin_from_grok -> hermes twin sync ->
twin_back_to_grok, on a plain profile and on a mirrored one.

Set BOTPORT_TEST_BIN to a botport build (for example `cargo build --release` of tag v0.2.1); skipped otherwise.
The behaviour test (a real chat with the twin's model) and compare are stood in for; everything botport does is
real. HOME, XDG_* and HERMES_HOME are all under tmp_path and PATH is the system folders only, so nothing can reach a
real Hermes install or Grok app. Invented bots only (Acme Helper).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess

import pytest

from twin_testlib import config, home, service, timer  # noqa: F401
from hermes_plugins.grok_bot_twin.twin import engine as E
from hermes_plugins.grok_bot_twin.twin import one_prompt, store, sync_both

BIN = os.environ.get("BOTPORT_TEST_BIN", "")
pytestmark = pytest.mark.skipif(not (BIN and os.path.isfile(BIN) and os.access(BIN, os.X_OK)),
                                reason="set BOTPORT_TEST_BIN to a botport v0.2.1 build to run these")
NAME, PID = "Acme Helper", "acme-helper"
ALLOWED = [NAME]
SKILLS = [{"name": "widget-faq", "description": "Widget FAQ", "instructions": "# Widget FAQ\nAnswer briefly."}]
MEMORY = ["The owner prefers short answers."]
INSTRUCTIONS = "You answer questions about Acme widgets."


@pytest.fixture
def rig(home, tmp_path, monkeypatch):
    os.chmod(tmp_path, 0o700)
    sand = tmp_path / "user-home"
    sand.mkdir(mode=0o700)
    monkeypatch.setenv("HOME", str(sand))
    for k in ("XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME"):
        monkeypatch.setenv(k, str(tmp_path / "xdg" / k.lower()))
    bindir = tmp_path / "bin"
    bindir.mkdir(mode=0o755)
    exe = bindir / "botport"
    shutil.copyfile(os.path.realpath(BIN), exe)
    exe.chmod(0o755)
    assert E.check_path_safety(str(exe.resolve())) is None
    version = subprocess.run([str(exe), "--version"], capture_output=True, text=True, timeout=30).stdout
    if "0.2.1" not in version:
        pytest.skip(f"BOTPORT_TEST_BIN is not botport 0.2.1 ({version.strip()})")
    monkeypatch.setattr(timer, "ensure_started", lambda *a, **k: False)
    config.set_override({"botport_path": str(exe)})
    service.reset_service()
    svc = service.get_service()
    assert svc.trust_botport(True)["trusted"] is True  # the recorded local-build opt-out
    svc._save_registry({PID: {"pair_id": PID, "grok": {"id": "b-acme-0001", "name": NAME},
                              "hermes": {"profile": PID}, "created_at": "2026-11-01T00:00:00Z"}})
    store.ensure_dir(store.profile_home(PID))
    tests = []
    def behaviour_test(self, pid, battery=None, from_export=None):  # (botport `test` asks a model: stood in for)
        tests.append(from_export)
        if from_export:
            store.ensure_dir(self._battery_path(pid).parent)
            self._battery_path(pid).write_text("{}")
        return {"passed": 1, "total": 1, "ok": True}
    monkeypatch.setattr(type(svc), "behaviour_test", behaviour_test)
    monkeypatch.setattr(type(svc), "parity", lambda self, pid: {"passed": 1, "total": 1})
    yield {"svc": svc, "exe": exe, "prof": store.profile_home(PID), "tmp": tmp_path, "tests": tests}


def _tree(root):
    """Every file under a profile -> its bytes (symlinks as their target), to prove a FAIL left nothing."""
    out = {}
    for p in sorted(root.rglob("*")):
        rel = str(p.relative_to(root))
        if p.is_symlink():
            out[rel] = "->" + os.readlink(p)
        elif p.is_file():
            out[rel] = p.read_bytes()
    return out


def _from_grok(svc, **kw):
    kw.setdefault("instructions", INSTRUCTIONS)
    kw.setdefault("skills", SKILLS)
    kw.setdefault("memory", MEMORY)
    return one_prompt.twin_from_grok(svc, ALLOWED, NAME, **kw)


def test_plain_profile_from_grok_then_sync_then_back(rig):
    svc, prof = rig["svc"], rig["prof"]
    res = _from_grok(svc)
    assert res["ok"], res
    assert (prof / "SOUL.md").read_text().strip().endswith(INSTRUCTIONS) or INSTRUCTIONS in (prof / "SOUL.md").read_text()
    assert list(prof.glob("skills/*/widget-faq/SKILL.md")), _tree(prof).keys()
    # botport 0.2.1 keeps the Grok bot's memory as a memory skill, not in Hermes' memories/
    assert any("short answers" in p.read_text() for p in prof.glob("skills/*/*-memory/SKILL.md")), sorted(_tree(prof))
    assert list(prof.glob("backups/botport/*"))
    assert res["drift"] == "clean" and rig["tests"]  # cases made from this export

    again = _from_grok(svc)  # the same words: a no-op sync, the kept cases reused
    assert again["ok"] and "already level with" in again["line"], again
    assert len([t for t in rig["tests"] if t]) == 1

    # Hermes learns a fact; the Grok bot learns another. `hermes twin sync` brings them level both ways.
    mem = prof / "memories" / "MEMORY.md"
    mem.parent.mkdir(exist_ok=True)
    mem.write_text("Ships on Fridays.")
    state = {"instructions": INSTRUCTIONS, "skills": SKILLS, "memory": MEMORY + ["Lives in Lisbon."]}
    synced = sync_both.sync_bot(svc, PID, state)
    assert synced["ok"], synced
    assert any("Lisbon" in p.read_text() for p in prof.glob("skills/*/*-memory/SKILL.md"))
    assert any("Fridays" in f["fact"] for f in synced["for_grok"]["memory"]), synced["for_grok"]

    back = one_prompt.twin_back_to_grok(svc, ALLOWED, NAME, instructions=INSTRUCTIONS, skills=SKILLS,
                                        memory=MEMORY + ["Lives in Lisbon.", "Ships on Fridays."])
    assert back["ok"], back
    assert back["line"].startswith(f"PASS: {NAME} back to Grok:")


def test_real_botport_writes_are_all_in_the_snapshot(rig, monkeypatch):
    """M2 against the real thing: a FAILed first call leaves none of botport's own files behind."""
    svc, prof = rig["svc"], rig["prof"]
    before = _tree(prof)
    rig_tests = rig["tests"]
    monkeypatch.setattr(type(svc), "behaviour_test", lambda self, pid, battery=None, from_export=None:
                        rig_tests.append(from_export) or {"passed": 0, "total": 1, "ok": False})
    res = _from_grok(svc)
    assert not res["ok"] and res["restored"], res
    assert _tree(prof) == before
    assert not svc._battery_path(PID).exists()


def test_mirrored_profile_is_refused_and_left_as_it_was(rig):
    """A profile the owner's own `botport mirror` keeps (no twin pair owns it, so it cannot be made bot-driven):
    botport 0.2.1 refuses spec-driven sync on it; every path FAILs and nothing changes."""
    svc, prof, exe, tmp = rig["svc"], rig["prof"], rig["exe"], rig["tmp"]
    (prof / "SOUL.md").write_text("Mirrored soul.\n")
    env = {"PATH": "/usr/bin:/bin", "HOME": os.environ["HOME"], "NO_COLOR": "1",
           **{k: os.environ[k] for k in ("XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME")}}
    local = tmp / "mirror-local"
    local.mkdir()
    cp = subprocess.run([str(exe), "mirror", "init", "--pair=acme", f"--profile-dir={prof}", "--transport=local",
                         f"--local-dir={local}", "--no-pair-key", "--json"], env=env, capture_output=True,
                        timeout=120)
    if not (prof / "botport.mirror.json").is_file():  # (mirror init's own needs vary; the refusal reads this file)
        (prof / "botport.mirror.json").write_text("{}")
    assert cp.returncode in (0, 1, 2)
    before = _tree(prof)
    res = _from_grok(svc)
    assert not res["ok"] and "mirrored profile" in res["line"], res
    assert _tree(prof) == before
    with pytest.raises(E.EngineError) as exc:
        sync_both.sync_bot(svc, PID, {"instructions": INSTRUCTIONS, "memory": MEMORY})
    assert "mirrored profile" in exc.value.message
    back = one_prompt.twin_back_to_grok(svc, ALLOWED, NAME, instructions=INSTRUCTIONS, memory=MEMORY)
    assert not back["ok"] and "mirrored profile" in back["line"], back  # (refused before any snapshot: nothing to restore)
    assert _tree(prof) == before
