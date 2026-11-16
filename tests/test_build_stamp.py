"""Audit 16 Nov (twin#58): the plugin folder's build stamp vs Hermes' install record. Invented revisions only."""
from __future__ import annotations

import json

import pytest

from twin_testlib import home, svc  # noqa: F401
from hermes_plugins.grok_bot_twin.twin import auto_setup

OLD, NEW = "4" * 40, "b" * 40


@pytest.fixture
def plug(tmp_path, monkeypatch):
    plugin = tmp_path / "plugins" / "grok-bot-twin"
    (plugin / "twin").mkdir(parents=True)
    monkeypatch.setattr(auto_setup, "PLUGIN_DIR", plugin)
    monkeypatch.setattr(auto_setup, "build_stamp", lambda: json.loads(
        (plugin / "twin" / "BUILD").read_text()) if (plugin / "twin" / "BUILD").exists() else {})

    def record(ref):
        (plugin.parent / ".install-metadata.json").write_text(json.dumps({"grok-bot-twin": {"commit": ref}}))

    def stamp(ref):
        (plugin / "twin" / "BUILD").write_text(json.dumps({"commit": ref}))
    return record, stamp


def test_a_stale_install_record_is_named(plug, svc):
    record, stamp = plug
    record(OLD)
    stamp(NEW)
    res = auto_setup.install_check()
    assert res["ok"] is False and NEW[:12] in res["message"] and OLD[:12] in res["message"]
    assert "--ref" in res["fix"] and "adopt" in res["fix"]
    assert auto_setup.plugin_ref() == NEW  # the stamp is the truth about the folder
    row = next(c for c in svc.doctor(probe_importers=False)["checks"] if c["id"] == "plugin_build")
    assert row["ok"] is False and "does not match" in row["message"]


def test_no_stamp_says_unknown_never_the_old_revision_as_the_build(plug):
    record, _stamp = plug
    record(OLD)
    res = auto_setup.install_check()
    assert res["ok"] is True and res["message"].startswith("plugin build: unknown")


def test_a_matching_stamp_passes(plug):
    record, stamp = plug
    record(NEW[:12])
    stamp(NEW)
    assert auto_setup.install_check()["ok"] is True


def test_the_real_reader_takes_only_plain_revisions(tmp_path, monkeypatch):
    f = auto_setup.Path(auto_setup.__file__).resolve().parent / auto_setup.BUILD_FILE
    if f.exists():
        pytest.skip("a stamped tree")
    assert auto_setup.build_stamp() == {}


def test_hermes_revision_key_is_read(plug):
    """Hermes' own install record names the commit as "revision" (seen on a real v0.5.0 install)."""
    _record, stamp = plug
    (auto_setup.PLUGIN_DIR.parent / ".install-metadata.json").write_text(
        json.dumps({"grok-bot-twin": {"pinned": True, "revision": NEW, "source": "https://example.invalid/twin.git"}}))
    stamp(NEW)
    res = auto_setup.install_check()
    assert res["ok"] is True and "matches" in res["message"]
