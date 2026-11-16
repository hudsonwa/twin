"""twin#69: a second twin of the same bot is "Name 2" everywhere (folder, Hermes display name, Telegram name and
username), numbered across the whole fleet. Invented names only."""
from __future__ import annotations

import re

import yaml

from twin_testlib import config, home, service  # noqa: F401
from test_fleet_units import SRC, T1, T2, _apply, _linked, _list
from hermes_plugins.grok_bot_twin.twin import fleet, fleet_profiles as fp

T3 = "t-0f0e0d0c0b0a0908"
TG = re.compile(r"\A[a-z][a-z0-9_]{3,30}bot\Z")


def _t(tid, name="Acme Support", n=None):
    t = {"id": tid, "name": name, "description": "Answers questions.", "version": 1, "updated_at": None}
    if n:
        t["n"] = n
    return t


def test_plain_name_is_kept_when_nothing_collides(home):  # noqa: F811
    assert fp.unique_profile("Acme Support") == "acme-support"
    assert fp.unique_profile("Acme Support", {"acme-support"}) == "acme-support-2"  # as before
    assert fp.shown_name("acme-support", "Acme Support") == "Acme Support"
    assert fp.instance_number("acme-support", "Acme Support") == 1
    assert fp.telegram_username("acme-support") == "acme_support_twin_bot"


def test_number_matches_display_name_and_telegram_name(home):  # noqa: F811
    prof = fp.unique_profile("Acme Support", {"acme-support"})
    assert fp.shown_name(prof, "Acme Support") == "Acme Support 2"
    assert fp.instance_number(prof, "Acme Support") == 2
    assert fp.telegram_username(prof) == "acme_support_2_twin_bot"


def test_fleet_numbers_are_never_reused_on_another_computer(home):  # noqa: F811
    # another computer already holds "2": this one makes "3", not a second "2"
    assert fp.unique_profile("Acme Support", {"acme-support"}, fleet={1, 2}) == "acme-support-3"
    # the number the fleet gave it is taken, also when the plain name is free here
    assert fp.unique_profile("Acme Support", (), number=3, fleet={1, 2}) == "acme-support-3"
    # removing "2" renumbers nothing: 3 stays 3, the next one takes the free 2
    assert fp.unique_profile("Acme Support", {"acme-support"}, fleet={1, 3}) == "acme-support-2"
    # the wanted number is busy here: the next free one, never the plain name
    assert fp.unique_profile("Acme Support", {"acme-support-2"}, number=2, fleet={1}) == "acme-support-3"


def test_telegram_username_follows_telegram_rules(home):  # noqa: F811
    for prof in ("acme-support", "acme-support-2", "a", "9lives-2", "x" * 40 + "-17", "ab-cd" * 12 + "-999",
                 "twin", "default-2"):
        u = fp.telegram_username(prof)
        assert TG.match(u) and 5 <= len(u) <= 32, (prof, u)
    long = fp.telegram_username("very-long-invented-helper-name-17")
    assert long.endswith("_17_twin_bot") and len(long) <= 32


def test_the_wire_carries_only_the_number(home, tmp_path):  # noqa: F811
    lst = fleet.clean_list(_list([_t(T1), _t(T2, n=2), _t(T3, n="2"), ]))
    by = {t["id"]: t for t in lst["twins"]}
    assert "n" not in by[T1] and by[T2]["n"] == 2 and "n" not in by[T3]
    assert fleet._wire_number({"profile": "acme-support-2", "name": "Acme Support"}) == {"n": 2}
    assert fleet._wire_number({"profile": "acme-support", "name": "Acme Support"}) == {}
    assert fleet._wire_number({"profile": None, "name": "Acme Support"}) == {}


def test_a_follower_uses_the_fleet_numbers(home, tmp_path):  # noqa: F811
    _linked(home, tmp_path)
    # a Hermes bot of the owner's already sits at acme-support-2 here
    (home / "profiles" / "acme-support-2").mkdir(parents=True)
    (home / "profiles" / "acme-support-2" / "config.yaml").write_text("model: x\n", encoding="utf-8")
    counts = _apply(_list([_t(T1), _t(T2, n=2)]))
    assert counts["added"] == 2 and counts["failed"] == 0
    held = fleet.load()["link"]["twins"]
    assert held[T1]["profile"] == "acme-support"
    # "2" is busy here, so the fleet's second instance takes the next free number, never the plain name
    assert held[T2]["profile"] == "acme-support-3"
    meta = yaml.safe_load((home / "profiles" / "acme-support-3" / "profile.yaml").read_text(encoding="utf-8"))
    assert meta["display_name"] == "Acme Support 3"


def test_a_follower_keeps_the_sources_number(home, tmp_path):  # noqa: F811
    _linked(home, tmp_path)
    assert _apply(_list([_t(T2, n=2), _t(T1)]))["added"] == 2
    held = fleet.load()["link"]["twins"]
    assert held[T1]["profile"] == "acme-support" and held[T2]["profile"] == "acme-support-2"
    meta = yaml.safe_load((home / "profiles" / "acme-support-2" / "profile.yaml").read_text(encoding="utf-8"))
    assert meta["display_name"] == "Acme Support 2"
