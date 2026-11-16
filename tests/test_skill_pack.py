"""twin#65: the twin skill pack (four read-only plugin skills) in each twin's profile, and the four places it is
left out: skill sync, send-to-grok, compare's own-skills count, and the linked-computer skill copy.
Invented bots only (Acme Support)."""
from __future__ import annotations

import json
import re

import pytest
import yaml

from twin_testlib import ROOT, home, service, svc  # noqa: F401
from hermes_plugins.grok_bot_twin.twin import fleet_skills, hermes_side, origin, skill_pack, store, sync_both
from hermes_plugins.grok_bot_twin.twin.model import PLUGIN_VERSION

from test_sync_both import STATE, FakeBotport  # noqa: E402

PACK_SRC = ROOT / "skills" / "twin-pack"


def _register(svc, profile="acme-support"):
    svc._save_registry({profile: {"pair_id": profile, "grok": {"id": "g-acme", "name": "Acme Support"},
                                  "hermes": {"profile": profile}, "created_at": "2026-11-01T00:00:00Z"}})
    h = store.profile_home(profile)
    h.mkdir(parents=True, exist_ok=True)
    return h


def _front(text):
    return yaml.safe_load(text.split("---", 2)[1])


# ---- the pack itself ---------------------------------------------------------------------------------------------
def test_four_read_only_skills_tagged_origin_plugin():
    names = sorted(p.name for p in PACK_SRC.iterdir() if p.is_dir())
    assert names == sorted(skill_pack.NAMES)
    for n in names:
        text = (PACK_SRC / n / "SKILL.md").read_text(encoding="utf-8")
        fm = _front(text)
        assert fm["name"] == n and fm["origin"] == "plugin" and fm["metadata"]["hermes"]["origin"] == "plugin"
        assert fm["description"] and "## Rules" in text


def test_update_skill_explains_and_never_runs_an_update():
    text = (PACK_SRC / "twin-update" / "SKILL.md").read_text(encoding="utf-8")
    assert "never runs an update" in text.lower() and "hermes twin verify" in text
    nc = (PACK_SRC / "twin-new-computer" / "SKILL.md").read_text(encoding="utf-8")
    assert "--link" in nc and "experimental" in nc


def test_pack_has_no_hosts_ips_or_personal_paths():
    blob = "".join(p.read_text(encoding="utf-8") for p in PACK_SRC.rglob("*.md"))
    assert not re.search(r"\b\d{1,3}(\.\d{1,3}){3}\b", blob)
    assert not re.search(r"/Users/|/home/|\.local\b|\.lan\b|tailscale|ts\.net", blob, re.I)
    assert "(invented)" in blob


# ---- install and refresh -----------------------------------------------------------------------------------------
def test_new_twin_lists_the_four_skills_with_a_version_marker(svc, home):  # noqa: F811
    h = _register(svc)
    origin.refresh(svc)
    assert skill_pack.listed(h) == list(skill_pack.NAMES)
    marker = json.loads((h / "skills" / "twin-pack" / skill_pack.MARKER).read_text())
    assert marker == {"version": PLUGIN_VERSION, "origin": "plugin", "skills": sorted(skill_pack.NAMES)}
    assert skill_pack.refresh(["acme-support"]) == 0  # same version: nothing written


def test_plugin_update_refreshes_and_deleted_skill_stays_deleted_until_repair(svc, home):  # noqa: F811
    h = _register(svc)
    origin.refresh(svc)
    dest = h / "skills" / "twin-pack"
    f = dest / "twin-health" / "SKILL.md"
    f.write_text("old text", encoding="utf-8")
    (dest / "twin-update" / "SKILL.md").unlink()
    (dest / "twin-update").rmdir()
    m = json.loads((dest / skill_pack.MARKER).read_text())
    (dest / skill_pack.MARKER).write_text(json.dumps({**m, "version": "0.0.1"}))  # as an older plugin left it
    assert skill_pack.refresh(["acme-support"]) == 1
    assert f.read_text(encoding="utf-8") == (PACK_SRC / "twin-health" / "SKILL.md").read_text(encoding="utf-8")
    assert "twin-update" not in skill_pack.listed(h)
    assert json.loads((dest / skill_pack.MARKER).read_text())["version"] == PLUGIN_VERSION
    origin.refresh(svc, repair_pack=True)
    assert "twin-update" in skill_pack.listed(h)


def test_sample_and_default_profiles_get_no_pack(svc, home):  # noqa: F811
    svc._save_registry({"s": {"pair_id": "s", "sample": True, "hermes": {"profile": "sample-bot"}},
                        "d": {"pair_id": "d", "hermes": {"profile": "default"}}})
    store.profile_home("sample-bot").mkdir(parents=True)
    origin.refresh(svc)
    assert skill_pack.listed(store.profile_home("sample-bot")) == []


# ---- exclusions --------------------------------------------------------------------------------------------------
def test_linked_computer_copy_leaves_the_pack_out(svc, home):  # noqa: F811
    h = _register(svc)
    origin.refresh(svc)
    own = h / "skills" / "support" / "refunds"
    own.mkdir(parents=True)
    (own / "SKILL.md").write_text("---\nname: refunds\n---\nCheck the order.\n", encoding="utf-8")
    assert sorted(fleet_skills.skill_dirs("acme-support")) == ["support/refunds"]


def test_skill_sync_never_takes_a_pack_name_from_grok(svc, home):  # noqa: F811
    from hermes_plugins.grok_bot_twin.twin.connect import BadInput
    _register(svc)
    with pytest.raises(BadInput, match="twin skill pack"):
        svc.skill_sync_take("acme-support", add=["twin-health"])
    origin.refresh(svc)
    # Hermes has them, so skill sync never offers a Grok skill of the same name
    assert set(skill_pack.NAMES) <= svc._hermes_skill_names({"hermes": {"profile": "acme-support"}})


def test_send_to_grok_never_carries_the_pack(svc, home, monkeypatch):  # noqa: F811
    _register(svc)
    origin.refresh(svc)
    monkeypatch.setattr(svc, "engine_for", lambda pid: pytest.fail("the fake runner stands in for botport"))
    fake = FakeBotport(svc.central, skills={"triage": "# triage\nSort tickets.", "twin-health": "plugin text"},
                       proof={"in_sync": False, "items": [], "h2g": {"items": [
                           {"area": "skill", "path": "skills/triage", "status": "create"},
                           {"area": "skill", "path": "skills/twin-pack/twin-about-me", "status": "create"}]}})
    res = sync_both.sync_bot(svc, "acme-support", STATE, runner=fake)
    assert [s["name"] for s in res["for_grok"]["skills"]] == ["triage"]
    assert res["ok"]  # the pack is not a difference that send-to-grok has to carry
    assert hermes_side.skill_text(store.profile_home("acme-support"), "twin-health") is None
    applied = [{"kind": "skill", "direction": "h2g", "item": "skill:twin-update"},
               {"kind": "skill", "direction": "h2g", "item": "skill:triage"}]
    assert sum(1 for a in applied if not skill_pack.is_pack_item(a)) == 1


def test_compare_does_not_count_pack_skills_as_the_bots(svc, home, monkeypatch):  # noqa: F811
    rows = [{"id": "skill:refunds", "name": "skill refunds", "pass": True, "detail": "same"},
            {"id": "skill:twin-health", "name": "skill twin-health", "pass": False, "detail": "only in Hermes"},
            {"id": "skill:twin-about-me", "name": "skill twin-about-me", "pass": True, "detail": "same"}]
    monkeypatch.setattr(svc, "require_pair", lambda pid: pid)
    monkeypatch.setattr(svc, "engine_for", lambda pid: svc.demo)
    monkeypatch.setattr(svc.demo, "parity", lambda pid: {"passed": 2, "total": 3, "checks": rows})
    par = svc.parity("acme-support")
    assert [c["id"] for c in par["checks"]] == ["skill:refunds"]
    assert (par["passed"], par["total"]) == (1, 1)


def test_git_history_leaves_the_pack_out(svc, home):  # noqa: F811
    from hermes_plugins.grok_bot_twin.twin import git_mirror
    h = _register(svc)
    origin.refresh(svc)
    own = h / "skills" / "support" / "refunds"
    own.mkdir(parents=True)
    (own / "SKILL.md").write_text("Check the order.\n", encoding="utf-8")
    assert sorted(git_mirror._tree(h, "skills", "skills")) == ["skills/support/refunds/SKILL.md"]


# ---- twin#65 follow-up: the safety rule never reads the pack as the bot's text -----------------------------------
def test_harmless_twin_with_the_pack_stays_standard_and_names_no_words(svc, home):  # noqa: F811
    from hermes_plugins.grok_bot_twin.twin import profile_safety as ps
    h = _register(svc, "meals")
    (h / "SOUL.md").write_text("Plan weekly meals.", encoding="utf-8")
    assert skill_pack.install_home(h)  # the real pack: twin-update's text names "terminal"
    pack_text = " ".join(p.read_text(encoding="utf-8") for p in (h / "skills" / skill_pack.PACK_DIR).rglob("SKILL.md"))
    assert "terminal" in ps.risky_words([pack_text])
    assert ps.choose(ps.profile_texts(h)) == ("standard", [])  # (before: strict, because of "terminal")
    got = ps.apply_default("meals")
    assert got["preset"] == "parity" and got["words"] == []
    own = h / "skills" / "ops" / "SKILL.md"  # the bot's own skills are still read
    own.parent.mkdir(parents=True)
    own.write_text("Use ssh to check the server.", encoding="utf-8")
    assert ps.choose(ps.profile_texts(h))[0] == "strict"
