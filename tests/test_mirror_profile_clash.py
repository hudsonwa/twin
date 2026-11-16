"""Audit 16 Nov (twin#60): planning a twin must not silently pick a profile an earlier `botport mirror` pair keeps.

Invented bot only (Acme Support). The engine is stood in for: botport's dry run proposes the old mirror profile.
"""
from __future__ import annotations

import pytest

from twin_testlib import home, service, svc  # noqa: F401
from hermes_plugins.grok_bot_twin.twin import store
from hermes_plugins.grok_bot_twin.twin.engine import EngineError


class Eng:
    def __init__(self):
        self.made = []

    def create(self, gid, prof, dry_run=False):
        self.made.append((gid, prof, dry_run))
        return {"pairs": [{"grok_id": gid, "pair_id": "acme-support", "hermes": {"profile": prof}}]}


@pytest.fixture
def plan(svc, monkeypatch):
    eng = Eng()
    monkeypatch.setattr(svc, "_route_grok", lambda gid: eng)
    monkeypatch.setattr(svc, "_former_profile", lambda gid, taken: None)
    monkeypatch.setattr(svc, "_botport_default_profile", lambda e, gid: ("mirror-acme-support", None))
    monkeypatch.setattr(svc, "_old_twin_of", lambda e, gid, prof, taken: None)
    home = store.profile_home("mirror-acme-support")
    home.mkdir(parents=True)
    (home / "botport.mirror.json").write_text('{"schema": "x"}', encoding="utf-8")
    return eng


def test_an_old_mirror_profile_is_named_with_both_ways_out(svc, plan):
    with pytest.raises(EngineError) as exc:
        svc.create(["g-acme"])
    assert exc.value.code == "mirror_profile"
    assert "mirror-acme-support" in exc.value.message and "already mirrors this bot" in exc.value.message
    assert "Park it" in exc.value.hint and "--hermes-profile mirror-acme-support" in exc.value.hint
    assert not [m for m in plan.made if not m[2]]  # nothing was made, nothing adopted silently


def test_naming_the_mirror_profile_adopts_it_on_purpose(svc, plan):
    chosen, skipped, _e, _d = svc._plan_profiles(["g-acme"], {"g-acme": "mirror-acme-support"})
    assert chosen == {"g-acme": "mirror-acme-support"} and skipped == []


def test_a_plain_existing_profile_is_not_a_clash(svc, plan):
    (store.profile_home("mirror-acme-support") / "botport.mirror.json").unlink()
    chosen, skipped, _e, _d = svc._plan_profiles(["g-acme"], {})
    assert chosen == {"g-acme": "mirror-acme-support"} and skipped == []
