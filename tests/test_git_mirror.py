"""Optional per-bot git history (git_mirror): off by default, commits after each one-prompt PASS, pushes to a
remote (a temp bare repository here), never fails a sync. Invented bots only (Acme Support)."""
from __future__ import annotations

import shutil
import subprocess
import types

import pytest

from twin_testlib import fake_key, home, svc  # noqa: F401
from test_one_prompt import World, call
from hermes_plugins.grok_bot_twin.twin import git_mirror as G
from hermes_plugins.grok_bot_twin.twin import store

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
KEY = "sk-ant-api03-" + "A1b2C3d4E5f6G7h8I9j0" * 4


def repo():
    return store.central_dir() / "git" / "acme-support"


def git(*args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout


def test_off_by_default_nothing_written(svc, home, monkeypatch):
    World(svc, monkeypatch)
    res = call(svc)
    assert res["ok"] and "Git history" not in res["line"]
    assert not repo().exists()


@needs_git
def test_commit_after_pass_and_push_to_bare_remote(svc, home, monkeypatch, tmp_path):
    bare = tmp_path / "remote.git"
    git("init", "-q", "--bare", str(bare))
    World(svc, monkeypatch)
    G.set_on("acme-support", True, remote=str(bare))
    res = call(svc)
    assert res["ok"] and "Git history: commit" in res["line"] and "Pushed." in res["line"], res["line"]
    assert (repo() / "instructions.md").read_text() == "You answer questions about Acme widgets."
    assert (repo() / "skills" / "grok" / "widget-faq" / "SKILL.md").is_file()
    msg = git("log", "-1", "--format=%s", cwd=repo()).strip()
    assert msg == "PASS twin from Grok: 1 skill changed, instructions changed, memory changed"  # (MEMORY.md, one_prompt)
    assert git("--git-dir", str(bare), "log", "--format=%s", "main").strip() == msg
    again = call(svc)  # nothing changed: no second commit
    assert again["ok"] and "commit" not in again["line"]
    call(svc, instructions="You answer questions about Acme widgets and gadgets.")
    assert git("log", "-1", "--format=%s", cwd=repo()).strip() == "PASS sync from Grok: 0 skills changed, instructions changed"


@needs_git
def test_push_failure_is_a_warning_not_a_fail(svc, home, monkeypatch, tmp_path):
    World(svc, monkeypatch)
    G.set_on("acme-support", True, remote=str(tmp_path / "missing.git"))
    res = call(svc)
    assert res["ok"] and res["line"].startswith("PASS") and "Warning: git push failed" in res["line"]
    assert str(tmp_path) not in res["line"]  # the remote URL is never shown


@needs_git
def test_secrets_scrubbed_history_excluded_and_key_files_never_read(svc, home, monkeypatch):
    World(svc, monkeypatch, twinned=True)
    h = store.profile_home("acme-support")
    (h / "memories").mkdir(parents=True)
    (h / "memories" / "MEMORY.md").write_text(f"Short answers.\napi key {KEY}\n")
    (h / ".env").write_text(f"ANTHROPIC_API_KEY={KEY}\n")
    (h / "state.db").write_text("not copied")
    G.set_on("acme-support", True)
    assert call(svc)["ok"]
    mirrored = git("ls-files", cwd=repo()).split()
    assert "memory/MEMORY.md" in mirrored and not any("env" in p or "state" in p or "history" in p for p in mirrored)
    text = (repo() / "memory" / "MEMORY.md").read_text()
    assert "Short answers." in text and KEY not in text
    assert KEY not in git("log", "-p", cwd=repo())


def test_git_missing_says_how_to_install_and_pass_stays(svc, home, monkeypatch):
    World(svc, monkeypatch)
    G.set_on("acme-support", True)
    monkeypatch.setattr(G.shutil, "which", lambda name: None)
    res = call(svc)
    assert res["ok"] and "git is not installed" in res["line"] and "xcode-select" in res["line"]


def test_all_setting_and_off(svc, home):
    G.set_on(G.ALL, True)
    assert G.setting_for("acme-support")["on"]
    G.set_on("acme-support", False)
    assert G.setting_for("acme-support") is None
    assert any("every twin: on" in ln for ln in G.status_lines())


def test_cli_on_off_status(svc, home, monkeypatch, capsys):
    from hermes_plugins.grok_bot_twin.twin import cli
    monkeypatch.setattr(cli, "_resolve", lambda s, name: "acme-support")
    a = types.SimpleNamespace(action="on", pair="Acme Support", all=False, remote=None, with_history=True)
    assert G.cmd_git(a) == 0
    assert G.setting_for("acme-support") == {"on": True, "remote": None, "history": True}
    a.action = "off"
    assert G.cmd_git(a) == 0 and G.setting_for("acme-support") is None
    assert G.cmd_git(types.SimpleNamespace(action="status")) == 0
    assert "PASS: git history off" in capsys.readouterr().out


def test_all_with_one_remote_is_refused(svc, home, capsys):
    """Each twin is its own repository: they cannot all push `main` to one address."""
    a = types.SimpleNamespace(action="on", pair=None, all=True, remote="git@forgejo.example:me/bots.git",  # privacy:allow
                              with_history=False)
    assert G.cmd_git(a) == 1 and G.setting_for("acme-support") is None
    assert "--remote is per twin" in capsys.readouterr().out


@needs_git
def test_a_remote_added_later_gets_the_earlier_commits_at_the_next_pass(svc, home, monkeypatch, tmp_path):
    """git on --all, the first prompt, then a remote: the next PASS pushes, even when nothing changed."""
    bare = tmp_path / "later.git"
    git("init", "-q", "--bare", str(bare))
    World(svc, monkeypatch)
    G.set_on("acme-support", True)
    first = call(svc)
    assert first["ok"] and "Git history: commit" in first["line"]
    G.set_on("acme-support", True, remote=str(bare))
    again = call(svc)  # nothing changed in the bot
    assert again["ok"] and "commit" not in again["line"] and "Warning" not in again["line"], again["line"]
    assert git("--git-dir", str(bare), "log", "--format=%s", "main").strip() == \
        git("log", "-1", "--format=%s", cwd=repo()).strip()
