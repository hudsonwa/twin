"""Audit 16 Nov (twin#62): a fresh twin's stop must not say its config changed since the safe defaults when only a
later create step (the model choice) wrote config.yaml. Invented bot (Meal Planner); no network."""
from __future__ import annotations

from pathlib import Path

from twin_testlib import home, svc  # noqa: F401
from hermes_plugins.grok_bot_twin.twin import profile_safety as ps
from hermes_plugins.grok_bot_twin.twin.batch import BatchMixin

BASE = """model:
  provider: custom
  base_url: http://127.0.0.1:8000/v1
  default: local-model
toolsets: [terminal, web, memory]
approvals:
  mode: 'off'
"""


def _prof(home: Path) -> Path:
    h = home / "profiles" / "meals"
    h.mkdir(parents=True)
    (h / "config.yaml").write_text(BASE, encoding="utf-8")
    (h / "SOUL.md").write_text("Plan weekly meals.", encoding="utf-8")
    return h


def test_create_then_set_model_then_stop_puts_the_config_back(home):
    h = _prof(home)
    ps.apply_default("meals", h)
    assert BatchMixin._write_model(h, "other-local-model", "custom") == "set"  # a later create step
    assert ps.refingerprint("meals", h) is True
    out = ps.forget("meals", h)
    assert out["restored"] is True and out["backup"] is None  # no "changed since the safe defaults" note
    assert (h / "config.yaml").read_text(encoding="utf-8") == BASE


def test_a_change_to_a_safe_default_key_is_never_blessed(home):
    h = _prof(home)
    ps.apply_default("meals", h)
    c = ps.load_config(h)
    c["approvals"]["mode"] = "off"
    ps.write_config(h, c)
    assert ps.refingerprint("meals", h) is False
    out = ps.forget("meals", h)
    assert out["restored"] is False and out["backup"]  # still named as changed


def test_no_record_or_no_change_is_left_alone(home):
    h = _prof(home)
    assert ps.refingerprint("meals", h) is False
    ps.apply_default("meals", h)
    assert ps.refingerprint("meals", h) is False  # nothing written since
