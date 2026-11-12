"""The shared core of the memory layers (twin/mem_layers.py): briefs and transcripts.

Switches (off by default, the "What syncs" panel's choice wins when the build has it), the 0.2 sealed box with one
key per layer between the owner's computers (attack tests: tamper, replay into another layer, wrong link, reading
the bytes) and the transport hook for the Mirror. Invented data only.
"""
from __future__ import annotations

import base64
import json
import sys
import types

import pytest

from twin_testlib import fake_key, home  # noqa: F401
from hermes_plugins.grok_bot_twin.twin import mem_layers as ml

P = "test-scout"


@pytest.fixture(autouse=True)
def _own_switches(monkeypatch):
    """These tests drive the layer's own switches (by profile); with the What syncs panel in the build the owner's
    choice comes from the panel instead (tests/test_sync_panel.py and the panel tests below cover that)."""
    monkeypatch.setattr(ml, "_panel", lambda: None)
LINK = bytes(range(32))
MID = "m-" + "a" * 16


# ---- switches ----------------------------------------------------------------------------------------------------------
def test_every_layer_starts_off(home):
    for layer in ml.LAYERS:
        assert ml.direction(P, layer) == "off"
        assert not ml.allowed(P, layer, "to_hermes") and not ml.allowed(P, layer, "to_grok")
    ml.set_direction(P, "briefs", "grok_to_hermes")
    assert ml.allowed(P, "briefs", "to_hermes") and not ml.allowed(P, "briefs", "to_grok")
    assert ml.direction(P, "transcripts") == "off" and ml.direction("test-quill", "briefs") == "off"
    ml.set_direction(P, "briefs", "off")
    assert not ml.any_on()


def test_panel_choice_wins_when_present(home, monkeypatch):
    calls = []
    fake = types.SimpleNamespace(
        wanted=lambda pid, key: {"session_briefs": "both"}.get(key) if pid == "test-scout" else None,
        mark_synced=lambda pid, key, way: calls.append((pid, key, way)))
    monkeypatch.setattr(ml, "_panel", lambda: fake)
    ml.set_direction(P, "transcripts", "both")  # the fallback store is not believed while the panel is there
    assert ml.direction(P, "briefs") == "both"
    assert ml.direction(P, "transcripts") == "off"
    assert ml.direction("test-quill", "briefs") == "off"
    ml.mark_synced(P, "briefs", "grok_to_hermes")
    assert (P, "session_briefs", "grok_to_hermes") in calls


def test_mirror_ready_only_with_a_transport_plugged_in(home):
    assert not ml.mirror_ready()
    ml.set_transport_factory(lambda prof: ml.StubTransport(prof))
    try:
        assert ml.mirror_ready()
    finally:
        ml.set_transport_factory(None)
    assert not ml.mirror_ready()


def test_ARCH_1_memory_facts_are_gone(home, capsys):
    """Memory facts with Grok could never run (no Grok transport outside the tests): the layer, its row and its
    command are removed. "facts" is not a layer any more and `hermes twin facts` is not a command."""
    from hermes_plugins.grok_bot_twin.twin import cli, sync_panel
    assert ml.LAYERS == ("briefs", "transcripts") and "facts" not in ml.PANEL_KEYS and "facts" not in ml.SENTENCES
    assert ml.direction(P, "facts") == "off"
    with pytest.raises(ml.LayerError):
        ml.set_direction(P, "facts", "both")
    with pytest.raises(ValueError):
        ml.layer_key(LINK, "facts")
    assert "memory_facts" not in sync_panel.KEYS
    with pytest.raises(SystemExit):
        cli.main(["facts"])
    assert "invalid choice: 'facts'" in capsys.readouterr().err


# ---- the sealed box between computers ----------------------------------------------------------------------------------
NOTE = {"facts": ["Prefers short answers.", "Owner keeps a garden."], "secret_marker": "ZEBRA-41c7"}


def test_box_round_trip_and_unreadable_bytes():
    box = ml.seal(LINK, "briefs", "ask", MID, "bind-1", NOTE)
    assert ml.unseal(LINK, "briefs", "ask", MID, "bind-1", box) == NOTE
    raw = base64.b64decode(box["box"])
    assert b"ZEBRA" not in raw and b"garden" not in raw and b"ZEBRA" not in json.dumps(box).encode()
    assert len(raw) % 1024 == 0


@pytest.mark.parametrize("change", ["layer", "way", "machine", "bind", "link", "tamper", "nonce", "shape"])
def test_box_refuses_anything_not_made_for_this_use(change):
    box = ml.seal(LINK, "transcripts", "ask", MID, "bind-1", NOTE)
    args = dict(link=LINK, layer="transcripts", way="ask", machine=MID, bind="bind-1")
    if change == "layer":
        args["layer"] = "briefs"
    elif change == "way":
        args["way"] = "answer"
    elif change == "machine":
        args["machine"] = "m-" + "b" * 16
    elif change == "bind":
        args["bind"] = "bind-2"
    elif change == "link":
        args["link"] = bytes(32)
    elif change == "tamper":
        raw = bytearray(base64.b64decode(box["box"]))
        raw[10] ^= 1
        box = {**box, "box": base64.b64encode(bytes(raw)).decode()}
    elif change == "nonce":
        box = {**box, "nonce": "00" * 24}
    elif change == "shape":
        box = ["not", "a", "box"]
    assert ml.unseal(args["link"], args["layer"], args["way"], args["machine"], args["bind"], box) is None


def test_layer_keys_differ_and_differ_from_02_memory():
    from hermes_plugins.grok_bot_twin.twin import xs_memory
    keys = {ml.layer_key(LINK, layer) for layer in ml.LAYERS}
    assert len(keys) == 2
    box = ml.seal(LINK, "briefs", "ask", MID, "b", NOTE)
    assert xs_memory.unseal(LINK, "ask", MID, "b", box) is None  # a layer box is not a 0.2 memory box
    with pytest.raises(ValueError):
        ml.layer_key(LINK, "everything")


# ---- privacy helpers ---------------------------------------------------------------------------------------------------
def test_mask_secrets_for_local_archives():
    text = "Hello.\nThe wifi password is " + "trail" + "4821x\nkey: " + fake_key() + "\nBye."
    out = ml.mask_secrets(text)
    assert "4821" not in out and fake_key() not in out
    assert out.startswith("Hello.\n") and out.endswith("\nBye.")
    assert ml.held("Prefers short answers.") is None
    assert ml.held_words({"secret": 1, "order": 2}) == [
        "2 items: reads like an instruction, not a note", "1 item: looks like it holds a password or key"]
