"""Stopping a twin deletes the files the removed session briefs and memory facts (0.3.5 and older) left for it."""
from twin import service, store


def _touch(p, text="x"):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def test_stop_deletes_old_briefs_and_memory_facts_files():
    root = store.central_dir()
    b_out = _touch(root / "briefs" / "pair-a" / "out" / "b-0123456789abcdef.md")
    b_in = _touch(root / "briefs" / "pair-a" / "in" / "b-fedcba9876543210.md")
    keep_other = _touch(root / "briefs" / "pair-a" / "out" / "notes.md")      # not a brief name: stays
    other_twin = _touch(root / "briefs" / "pair-b" / "out" / "b-0123456789abcdef.md")
    store.atomic_write_json(root / "briefs.json", {"v": 1, "twins": {"pair-a": {"to_grok": True}, "pair-b": {}}})
    ledger = _touch(root / "mem-facts" / "acme-support.json")
    lock = _touch(root / "mem-facts" / "acme-support.lock")
    point = _touch(root / "mem-facts-points" / "acme-support" / "MEMORY.md")
    stub = _touch(root / "mem-grok-stub" / "acme-support" / "facts.json")
    other_ledger = _touch(root / "mem-facts" / "recipe-planner.json")

    n = service.forget_old_layer_files("pair-a", "acme-support")

    assert n == 7
    assert not b_out.exists() and not b_in.exists()
    assert keep_other.exists() and other_twin.exists() and other_ledger.exists()
    assert store.read_json(root / "briefs.json")["twins"] == {"pair-b": {}}
    assert not ledger.exists() and not lock.exists()
    assert not point.parent.exists() and not stub.parent.exists()


def test_nothing_left_is_fine_and_no_profile_skips_memory_facts():
    root = store.central_dir()
    ledger = _touch(root / "mem-facts" / "acme-support.json")
    assert service.forget_old_layer_files("pair-z", None) == 0
    assert ledger.exists()
