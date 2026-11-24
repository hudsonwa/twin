"""Owner's ask (24 Nov 2026): a twin's Hermes approvals follow its Grok app's "Execution on Local Computer" setting.
Always allow -> yolo (approvals off, nothing asks first), Ask -> manual, Never -> no shell, code, browser or computer use."""
from twin import profile_safety as ps


def _cfg(grok):
    return ps.want({}, "parity", grok=grok)


def test_always_allow_is_yolo_with_every_grok_tool_on():
    c = _cfg("always")
    assert c["approvals"] == ps.YOLO_APPROVALS
    assert not set(ps.PARITY_ON) & set(c["agent"]["disabled_toolsets"])
    assert ps.problems(c, "parity", grok="always") == []
    assert "yolo" in ps.approvals_words(c)
    assert all(x["note"] in ("", "nothing asks first (yolo)") for x in ps.capabilities(c, "parity"))


def test_ask_keeps_manual_approvals():
    c = _cfg("ask")
    assert c["approvals"] == ps.MANUAL_APPROVALS
    assert ps.problems(c, "parity", grok="ask") == []
    assert ps.problems(_cfg("always"), "parity", grok="ask") == ["approvals.mode"]


def test_never_turns_off_local_execution():
    c = _cfg("never")
    assert set(ps.NEVER_OFF) <= set(c["agent"]["disabled_toolsets"])
    assert c["approvals"]["mode"] == "manual"
    assert ps.problems(c, "parity", grok="never") == []


def test_other_presets_never_go_yolo():
    for preset in ("strict", "standard"):
        assert ps.want({}, preset, grok="always")["approvals"]["mode"] == "manual"


def test_setting_is_remembered_and_unknown_is_ignored(tmp_path, monkeypatch):
    monkeypatch.setattr(ps.store, "central_dir", lambda: tmp_path)
    assert ps.grok_permission() == "ask"
    assert ps.note_grok_permission("always") is True
    assert ps.grok_permission() == "always"
    assert ps.note_grok_permission("unknown") is False
    assert ps.grok_permission() == "always"
    assert ps.note_grok_permission("always") is False
