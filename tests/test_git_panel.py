"""The Twins page's git switch (git_mirror.panel / choose and the /git/panel routes): the same functions the CLI
uses, a remote address that never comes back, git missing said plainly. Invented bots only (Acme Support)."""
from __future__ import annotations

import json
import shutil
import types

import pytest

import fleet_testlib
from twin_testlib import ROOT, home, svc  # noqa: F401
from hermes_plugins.grok_bot_twin.twin import git_mirror as G
from hermes_plugins.grok_bot_twin.twin import sync_panel
from hermes_plugins.grok_bot_twin.twin.engine import EngineError

fleet_testlib._SHAPES.update(json.loads((ROOT / "tests" / "desktop" / "gitpanel_shapes.json").read_text("utf-8"))["shapes"])
URL = "https://forgejo.example/me/acme.git"  # (an address with a password or token in it is refused: S4)
TOKEN_URL = "https://oauth2:tok-SECRET@forgejo.example/me/acme.git"


@pytest.fixture(autouse=True)
def twins(monkeypatch):
    ctxs = [types.SimpleNamespace(pair_id="acme-support", name="Acme Support"),
            types.SimpleNamespace(pair_id="recipe-planner", name="Recipe Planner")]
    monkeypatch.setattr(sync_panel, "_contexts", lambda svc: ctxs)
    monkeypatch.setattr(G.shutil, "which", lambda n: "/usr/bin/git")


def test_off_by_default(svc, home):  # noqa: F811
    v = G.panel(svc)
    assert fleet_testlib.shape_problems(v, "GitPanel") == []
    assert [(t["id"], t["on"], t["last"]) for t in v["twins"]] == [("acme-support", False, None), ("recipe-planner", False, None)]
    assert v["git"] is True and v["install"] == ""


def test_switch_on_off_and_the_remote_never_comes_back(svc, home):  # noqa: F811
    v = G.choose(svc, "acme-support", True, URL)
    assert fleet_testlib.shape_problems(v, "GitPanel") == [] and v["said"]["sentence"] == "Git history for Acme Support: on."
    t = v["twins"][0]
    assert t["on"] and t["remote_set"] and t["remote_host"] == "forgejo.example"
    assert "SECRET" not in json.dumps(v) and not v["twins"][1]["on"]
    assert G.setting_for("acme-support")["remote"] == URL        # the CLI sees the same setting
    v = G.choose(svc, "acme-support", True)                       # no remote given: kept
    assert v["twins"][0]["remote_set"]
    v = G.choose(svc, "acme-support", True, "")                   # empty: cleared
    assert v["twins"][0]["on"] and not v["twins"][0]["remote_set"]
    v = G.choose(svc, "acme-support", False)
    assert not v["twins"][0]["on"] and G.setting_for("acme-support") is None


def test_every_twin_setting_shows_and_one_can_opt_out(svc, home):  # noqa: F811
    G.set_on(G.ALL, True)
    t = G.panel(svc)["twins"]
    assert all(x["on"] and x["every"] for x in t)
    t = G.choose(svc, "acme-support", False)["twins"]
    assert not t[0]["on"] and t[1]["on"]


def test_last_status_is_shown(svc, home):  # noqa: F811
    G._note_status("acme-support", commit="a1b2c3d", pushed=False, problem="The push failed: nope")
    G.set_on("acme-support", True)
    last = G.panel(svc)["twins"][0]["last"]
    assert last["commit"] == "a1b2c3d" and last["pushed"] is False and "push failed" in last["problem"] and last["at"]
    assert fleet_testlib.shape_problems(G.panel(svc), "GitPanel") == []


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_a_real_commit_records_its_status(svc, home, monkeypatch, tmp_path):  # noqa: F811
    from test_one_prompt import World, call
    monkeypatch.setattr(G.shutil, "which", shutil.which)  # the real git for this one
    World(svc, monkeypatch)
    G.set_on("acme-support", True)
    assert call(svc)["ok"]
    last = G.last_status("acme-support")
    assert last["commit"] and last["pushed"] is None


def test_no_git_is_said_plainly(svc, home, monkeypatch):  # noqa: F811
    monkeypatch.setattr(G.shutil, "which", lambda n: None)
    v = G.panel(svc)
    assert v["git"] is False and "install" in v["install"] and "xcode-select" in v["install"]
    with pytest.raises(EngineError) as e:
        G.choose(svc, "acme-support", True)
    assert e.value.code == "no_git" and "not installed" in str(e.value)
    assert G.choose(svc, "acme-support", False)["twins"][0]["on"] is False  # off always works


@pytest.mark.parametrize("bad", ["-oProxyCommand=x", "a b", "x" * 600, 5, "a\nb", TOKEN_URL])
def test_a_bad_remote_is_refused(svc, home, bad):  # noqa: F811
    with pytest.raises(EngineError) as e:
        G.choose(svc, "acme-support", True, bad)
    assert e.value.code == "bad_input" and G.setting_for("acme-support") is None


def test_unknown_twin_and_bad_input(svc, home):  # noqa: F811
    for pid, on in (("ghost", True), ("../x", True), ("acme-support", "yes")):
        with pytest.raises(EngineError):
            G.choose(svc, pid, on)


def test_the_local_routes(svc, home, monkeypatch):  # noqa: F811
    pytest.importorskip("fastapi")
    import importlib.util
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from twin_testlib import timer
    spec = importlib.util.spec_from_file_location("gbt_plugin_api_git", ROOT / "dashboard" / "plugin_api.py")
    api = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(api)
    monkeypatch.setattr(timer, "ensure_started", lambda *a, **k: False)
    monkeypatch.setattr(api, "_svc", lambda: svc)
    app = FastAPI()
    P = "/api/plugins/grok-bot-twin"
    app.include_router(api.router, prefix=P)
    c = TestClient(app)
    r = c.get(P + "/git/panel")
    assert r.status_code == 200 and fleet_testlib.shape_problems(r.json(), "GitPanel") == []
    r = c.post(P + "/git/panel", json={"twin": "acme-support", "on": True, "remote": URL})
    assert r.status_code == 200 and r.json()["twins"][0]["on"] and "SECRET" not in r.text
    r = c.post(P + "/git/panel", json={"twin": "acme-support", "on": True, "remote": "--x"})
    assert r.json()["error"]["code"] == "bad_input"
    r = c.post(P + "/git/panel", json={"twin": "acme-support", "on": True, "remote": TOKEN_URL})
    assert r.json()["error"]["code"] == "bad_input" and "SECRET" not in r.text
    for body in ({"twin": "acme-support"}, {"twin": "../x", "on": True}, {"twin": 5, "on": True},
                 {"twin": "acme-support", "on": "yes"}, {"twin": "acme-support", "on": True, "remote": 5}):
        assert c.post(P + "/git/panel", json=body).status_code == 400
