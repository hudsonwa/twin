"""Final setup step: the reliability recipe is offered (opt-in) to twins on a local or smaller model, from one
pinned release, and twin/fleet SOUL blocks stay before the recipe's blocks."""
from __future__ import annotations

import types
from pathlib import Path

from twin_testlib import home  # noqa: F401
from hermes_plugins.grok_bot_twin.twin import fleet_profiles as fp, recipe_offer as ro


class FakeSvc:
    def __init__(self, homes: dict):
        self.homes = homes
        self.demo = types.SimpleNamespace(profiles=lambda: {"demo-bot": "d1"})

    def profiles_in_use(self):
        return {p: f"pair-{p}" for p in self.homes} | {"demo-bot": "d1"}

    def _profile_home(self, prof):
        return self.homes.get(prof)


def mk(root: Path, name: str, model: str, recipe: bool = False) -> Path:
    h = root / "profiles" / name
    (h / "state").mkdir(parents=True)
    (h / "config.yaml").write_text(model)
    (h / "SOUL.md").write_text("bot\n")
    if recipe:
        (h / "state" / "reliability-recipe-root.txt").write_text("/x\n")
    return h


LOCAL = "model:\n  default: big-model\n  base_url: http://192.168.1.20:8000/v1\n"
CLOUD = "model:\n  default: frontier-large\n  base_url: https://api.example.com/v1\n"
SMALL = "model:\n  default: qwen3-30b-a3b\n  base_url: https://api.example.com/v1\n"


def test_weaker():
    assert ro.weaker({"base_url": "http://localhost:8000/v1"})
    assert ro.weaker({"default": "qwen3-30b"})
    assert not ro.weaker({"default": "qwen3-235b", "base_url": "https://api.example.com"})
    assert not ro.weaker({"default": "frontier-large", "base_url": "https://api.example.com"})


def test_candidates_pick_local_and_small_skip_cloud_installed_demo(home):
    s = FakeSvc({"a": mk(home, "a", LOCAL), "b": mk(home, "b", CLOUD), "c": mk(home, "c", SMALL),
                 "d": mk(home, "d", LOCAL, recipe=True)})
    assert [p for p, _ in ro.candidates(s)] == ["a", "c"]


def run_offer(svc, monkeypatch, commit="", **flags):
    monkeypatch.setattr(ro, "RECIPE_COMMIT", commit)
    out, calls, asked = [], [], []
    a = types.SimpleNamespace(**flags)

    def fake_run(cmd, **kw):
        calls.append(cmd)
        if cmd[:2] == ["git", "-C"]:
            return types.SimpleNamespace(stdout=commit + "\n", returncode=0)
        return types.SimpleNamespace(returncode=0, stdout="")
    rc = ro.offer(svc, a, out.append, lambda q: asked.append(q) or flags.get("_answer", False), run=fake_run)
    return rc, out, calls, asked


def test_unreleased_installs_nothing(home, monkeypatch):
    s = FakeSvc({"a": mk(home, "a", LOCAL)})
    rc, out, calls, asked = run_offer(s, monkeypatch, with_recipe=True)
    assert rc == 0 and not calls and not asked and any("not released yet" in o for o in out)


def test_no_yes_installs_nothing(home, monkeypatch):
    s = FakeSvc({"a": mk(home, "a", LOCAL)})
    rc, out, calls, asked = run_offer(s, monkeypatch, commit="c" * 40, _answer=False)
    assert rc == 0 and asked and not calls and any("--with-recipe" in o for o in out)


def test_yes_installs_pinned_pack(home, monkeypatch):
    s = FakeSvc({"a": mk(home, "a", LOCAL)})
    rc, out, calls, _ = run_offer(s, monkeypatch, commit="c" * 40, with_recipe=True, recipe_owner="Ann")
    assert rc == 0
    assert calls[0][:2] == ["git", "clone"] and "--branch" in calls[0] and ro.RECIPE_TAG in calls[0]
    inst = calls[-1]
    assert inst[1].endswith("scripts/install.sh") and inst[inst.index("--pack") + 1] == "operating"
    assert inst[inst.index("--owner") + 1] == "Ann" and inst[inst.index("--captcha") + 1] == "handoff"


def test_wrong_commit_refused(home, monkeypatch):
    s = FakeSvc({"a": mk(home, "a", LOCAL)})
    monkeypatch.setattr(ro, "RECIPE_COMMIT", "c" * 40)
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return types.SimpleNamespace(stdout="d" * 40, returncode=0)
    out = []
    rc = ro.offer(s, types.SimpleNamespace(with_recipe=True), out.append, lambda q: True, run=fake_run)
    assert rc == 1 and not any("install.sh" in " ".join(c) for c in calls)


def test_no_recipe_flag(home, monkeypatch):
    s = FakeSvc({"a": mk(home, "a", LOCAL)})
    rc, out, calls, asked = run_offer(s, monkeypatch, commit="c" * 40, no_recipe=True)
    assert rc == 0 and not out and not calls and not asked


def test_twin_block_stays_before_recipe_blocks():
    soul = "bot\n# Reliability (hermes-reliability-recipe)\n- x\n\n<!-- hrr:begin operating-pack v=0.3.0 -->\ny\n<!-- hrr:end operating-pack -->\n"
    out = fp.set_block(soul, fp.TWIN_BEGIN, fp.TWIN_END, "twin text")
    assert out.index(fp.TWIN_BEGIN) < out.index("# Reliability (hermes-reliability-recipe)")
    again = fp.set_block(out, fp.TWIN_BEGIN, fp.TWIN_END, "twin text 2")
    assert again.count(fp.TWIN_BEGIN) == 1 and again.index(fp.TWIN_BEGIN) < again.index("hrr:begin")
    plain = fp.set_block("bot\n", fp.TWIN_BEGIN, fp.TWIN_END, "t")
    assert plain.endswith(fp.TWIN_END + "\n")
