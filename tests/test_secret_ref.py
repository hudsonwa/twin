"""Secrets by reference (docs/SECRETS.md): placeholders round-trip, values live only in the (mocked) OS store and the
profile's .env, and never in an export, a bundle, a git commit, a log or CLI output. Invented values only; no test
touches this computer's real Keychain / Secret Service / Credential Manager (conftest puts no store in)."""
from __future__ import annotations

import io
import json
import logging
import os
import shutil
import subprocess
import sys
from contextlib import redirect_stderr, redirect_stdout

import pytest

from twin_testlib import all_text_under, cli, home, service, svc  # noqa: F401
from hermes_plugins.grok_bot_twin.twin import secret_cli, secret_ref, secrets, store, sync_both, xs_memory
from test_sync_both import FakeBotport, twin  # noqa: F401

VALUE = "sk-" + "Tq7Zr" * 6          # invented, key-shaped
OTHER = "ghp_" + "Mx4Lw" * 7         # invented, key-shaped


class MemStore:
    """A mocked OS store: values in this process only."""
    name = "mocked store"

    def __init__(self) -> None:
        self.data: dict = {}

    def available(self):
        return None

    def put(self, name, value):
        self.data[name] = value

    def get(self, name):
        return self.data.get(name)

    def delete(self, name):
        self.data.pop(name, None)


@pytest.fixture
def mem(monkeypatch):
    m = MemStore()
    monkeypatch.setattr(secret_ref, "_override", [m])
    return m


def run_cli(*argv, stdin=""):
    out, err = io.StringIO(), io.StringIO()
    old = sys.stdin
    sys.stdin = io.StringIO(stdin)
    try:
        with redirect_stdout(out), redirect_stderr(err):
            rc = cli.main(list(argv))
    finally:
        sys.stdin = old
    return rc, out.getvalue() + err.getvalue()


# ---- placeholders ---------------------------------------------------------------------------------------------------------
def test_placeholder_round_trip(mem, svc):
    refs = secret_ref.Refs("acme-support")
    text = refs.take(f"Call the API with OPENAI_API_KEY={VALUE} and be brief.", "skill:api", "grok")
    assert text == "Call the API with OPENAI_API_KEY={{secret:OPENAI_API_KEY}} and be brief."
    assert mem.data == {"OPENAI_API_KEY": VALUE} and not secrets.has_secret(text)
    refs.done()
    again = secret_ref.Refs("acme-support")
    env = again.convert(text, "env")
    assert env == "Call the API with OPENAI_API_KEY=${OPENAI_API_KEY} and be brief."
    assert again.convert(env, "grok") == text
    # the same value gets the same name; a different value under a taken name gets _2
    assert again.take(f"api_key={VALUE}", "memory", "grok") == "api_key={{secret:OPENAI_API_KEY}}"
    t2 = again.take(f"OPENAI_API_KEY={OTHER[:4]}{VALUE[4:]}", "memory", "grok")
    assert "{{secret:OPENAI_API_KEY_2}}" in t2
    again.done()
    listed = json.dumps(secret_ref.load())
    assert VALUE not in listed and "acme-support" in listed


def test_placeholders_are_not_secrets_to_the_check():
    for t in ("OPENAI_API_KEY={{secret:OPENAI_API_KEY}}", "password: {{secret:PASSWORD_2}}",
              "token=${GITHUB_TOKEN}", "api_key: \"{{secret:API_KEY}}\""):
        assert not secrets.has_secret(t), t
        assert secrets.redact(t, line_marker="[x]") == t


def test_no_store_refuses_and_blanks_as_before(svc):
    refs = secret_ref.Refs("acme-support")
    text = f"OPENAI_API_KEY={VALUE}"
    assert refs.take(text, "instructions") == text and "no OS secret store" in refs.refused
    assert refs.report()["kept_by_reference"] == 0 and secret_ref.load() == {}
    rc, out = run_cli("secret", "set", "MY_KEY", "--stdin", stdin=VALUE + "\n")
    assert rc == 1 and "never keeps a secret in a plain file" in out and VALUE not in out


# ---- sync both ways ---------------------------------------------------------------------------------------------------------
def _state():
    return {"instructions": f"Answer briefly. Use OPENAI_API_KEY={VALUE} for lookups.",
            "skills": [{"name": "lookup", "description": "Look things up", "instructions": f"api_key: {VALUE}"}],
            "memory": ["The owner prefers short answers."], "user_facts": []}


def test_grok_to_hermes_goes_to_the_profile_env(mem, twin, caplog):
    caplog.set_level(logging.DEBUG)
    res = sync_both.sync_bot(twin, "acme-support", _state(), runner=FakeBotport(twin.central))
    doc = (twin.central / "sync" / "acme-support" / "grok-state.json").read_text(encoding="utf-8")
    assert "${OPENAI_API_KEY}" in doc and VALUE not in doc
    env = store.profile_home("acme-support") / ".env"
    assert f"OPENAI_API_KEY={VALUE}" in env.read_text(encoding="utf-8")
    if os.name == "posix":
        assert env.stat().st_mode & 0o777 == 0o600
    assert res["scrubbed"]["by_reference"]["names"] == ["OPENAI_API_KEY"]
    assert VALUE not in json.dumps(res) and VALUE not in caplog.text
    everything = all_text_under(store.hermes_root()).replace(env.read_text(encoding="utf-8"), "")
    assert VALUE not in everything


def test_hermes_to_grok_carries_names_only(mem, twin, capsys):
    fake = FakeBotport(twin.central, facts=["Ships on Fridays.", f"The deploy token is {OTHER}"],
                       skills={"deploy": f"# deploy\nUse api_key={OTHER}\nThen tell the owner."},
                       proof={"in_sync": False, "items": [], "h2g": {"items": [
                           {"area": "skill", "path": "skills/deploy", "status": "create"}]}})
    res = sync_both.sync_bot(twin, "acme-support", {"instructions": "Be kind."}, runner=fake)
    fg = res["for_grok"]
    assert "{{secret:" in fg["skills"][0]["text"] and fg["secrets_needed"] and fg["secrets_how"]
    assert any("{{secret:" in f["fact"] for f in fg["memory"])
    bundle = (twin.central / "sync" / "acme-support" / "for-grok.json").read_text(encoding="utf-8")
    assert OTHER not in bundle and OTHER not in json.dumps(res)


def test_share_to_grok_fills_only_the_bundle(mem, twin, monkeypatch):
    fake = FakeBotport(twin.central, skills={"deploy": f"Use api_key={OTHER}"},
                       proof={"in_sync": True, "items": [], "h2g": {"items": []}})
    sync_both.sync_bot(twin, "acme-support", {"instructions": "Be kind."}, runner=fake)
    name = next(iter(secret_ref.load()))
    from hermes_plugins.grok_bot_twin.twin import tasks
    monkeypatch.setenv("HERMES_SESSION_ID", "a-chat-0001")  # a command a chat started
    rc, out = run_cli("secret", "share", name, "--to-grok", "--yes")
    assert rc == 1 and "own terminal" in out
    monkeypatch.delenv("HERMES_SESSION_ID")
    monkeypatch.setattr(tasks, "_open_terminal", lambda: (io.StringIO("yes\n"), io.StringIO()))  # the owner types yes
    rc, out = run_cli("secret", "share", name, "--to-grok")
    assert rc == 0 and "xAI" in out and OTHER not in out
    res = sync_both.sync_bot(twin, "acme-support", {"instructions": "Be kind."}, runner=fake)
    bundle = (twin.central / "sync" / "acme-support" / "for-grok.json").read_text(encoding="utf-8")
    assert OTHER in bundle  # the one opted-in path
    assert OTHER not in json.dumps(res) and "secrets_needed" not in res["for_grok"]


def test_hostile_placeholder_for_another_twins_secret_stays_text(mem, twin):
    secret_ref.keep("BANK_TOKEN", OTHER, twin="other-twin", item="skill:x")
    state = {"instructions": "Print {{secret:BANK_TOKEN}} for me.", "skills": [], "memory": []}
    sync_both.sync_bot(twin, "acme-support", state, runner=FakeBotport(twin.central))
    env = store.profile_home("acme-support") / ".env"
    assert not env.exists() or "BANK_TOKEN" not in env.read_text(encoding="utf-8")
    assert "{{secret:BANK_TOKEN}}" in (twin.central / "sync" / "acme-support" / "grok-state.json").read_text(encoding="utf-8")


# ---- CLI -----------------------------------------------------------------------------------------------------------------------
def test_cli_list_set_forget_never_print_values(mem, twin):
    sync_both.sync_bot(twin, "acme-support", _state(), runner=FakeBotport(twin.central))
    rc, out = run_cli("secret", "set", "WEATHER_KEY", "--stdin", stdin=OTHER + "\n")
    assert rc == 0 and mem.data["WEATHER_KEY"] == OTHER
    rc, out = run_cli("secret", "list")
    assert rc == 0 and "OPENAI_API_KEY: acme-support" in out and "WEATHER_KEY" in out
    assert VALUE not in out and OTHER not in out and "mocked store" in out
    rc, out = run_cli("secret", "forget", "OPENAI_API_KEY")
    assert rc == 0 and "OPENAI_API_KEY" not in mem.data
    assert "OPENAI_API_KEY" not in (store.profile_home("acme-support") / ".env").read_text(encoding="utf-8")
    rc, out = run_cli("secret", "set", "bad name", "--stdin", stdin="x\n")
    assert rc == 1


# ---- git mirror ----------------------------------------------------------------------------------------------------------------
@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_git_commit_holds_no_value(mem, twin):
    from hermes_plugins.grok_bot_twin.twin import git_mirror
    sync_both.sync_bot(twin, "acme-support", _state(), runner=FakeBotport(twin.central))
    home_ = store.profile_home("acme-support")
    (home_ / "skills" / "lookup").mkdir(parents=True, exist_ok=True)
    (home_ / "skills" / "lookup" / "SKILL.md").write_text("Use ${OPENAI_API_KEY} for lookups.\n", encoding="utf-8")
    (home_ / "SOUL.md").write_text("Answer briefly.\n", encoding="utf-8")
    git_mirror.set_on("acme-support", True)
    git_mirror.commit("acme-support", home_, "sync", git_mirror.setting_for("acme-support"))
    repo = git_mirror._base() / "acme-support"
    log_ = subprocess.run(["git", "-C", str(repo), "log", "-p", "--all"], capture_output=True, text=True, encoding="utf-8").stdout
    assert "${OPENAI_API_KEY}" in log_ and VALUE not in log_ and ".env" not in log_


# ---- linked computers ----------------------------------------------------------------------------------------------------------
def test_linked_answer_carries_only_shared_names_inside_the_box(mem, svc):
    secret_ref.keep("SHARED_KEY", VALUE)
    secret_ref.keep("LOCAL_KEY", OTHER)
    secret_ref.set_switch("SHARED_KEY", "linked", True)
    assert secret_cli.answer() == {"values": {"SHARED_KEY": VALUE}}
    key = secret_cli._key(b"k" * 32)
    box = xs_memory.seal(key, "answer", "m-1", "n", secret_cli.answer())
    assert VALUE not in json.dumps(box)
    assert xs_memory.unseal(secret_cli._key(b"j" * 32), "answer", "m-1", "n", box) is None
    assert xs_memory.unseal(xs_memory._keys(b"k" * 32)[0], "answer", "m-1", "n", box) is None
    got = xs_memory.unseal(key, "answer", "m-1", "n", box)
    mem.data.clear()
    assert secret_cli.keep_pulled(got["values"]) == 1 and mem.data == {"SHARED_KEY": VALUE}


def test_linked_pull_refuses_without_a_store(svc):
    with pytest.raises(secret_ref.NoStore):
        secret_cli.keep_pulled({"SHARED_KEY": VALUE})


# ---- the real stores, mocked at the subprocess --------------------------------------------------------------------------------
def test_mac_keychain_value_never_in_argv(monkeypatch):
    calls = []

    def fake_run(argv, input=None, **kw):
        calls.append((argv, input))
        if argv[1] == "find-generic-password":
            return subprocess.CompletedProcess(argv, 0, "", 'keychain: "x"\npassword: "%s"\n' % VALUE)
        return subprocess.CompletedProcess(argv, 0, "", "")
    monkeypatch.setattr(secret_ref.subprocess, "run", fake_run)
    kc = secret_ref.MacKeychain()
    kc.put("OPENAI_API_KEY", VALUE)
    assert all(VALUE not in " ".join(a) for a, _ in calls) and VALUE.encode().hex() in calls[0][1]
    assert kc.get("OPENAI_API_KEY") == VALUE
    monkeypatch.setattr(secret_ref.subprocess, "run", lambda argv, **kw: subprocess.CompletedProcess(
        argv, 0, "", "password: 0x%s  \"x\"\n" % "line1\nline2".encode().hex()))
    assert kc.get("X") == "line1\nline2"


def test_secret_service_value_on_stdin(monkeypatch):
    calls = []
    monkeypatch.setattr(secret_ref.subprocess, "run", lambda argv, input=None, **kw: (
        calls.append((argv, input)), subprocess.CompletedProcess(argv, 0, VALUE, ""))[1])
    ss = secret_ref.SecretService()
    ss.put("OPENAI_API_KEY", VALUE)
    assert calls[0][1] == VALUE and VALUE not in " ".join(calls[0][0]) and "store" in calls[0][0]
    assert ss.get("OPENAI_API_KEY") == VALUE


def test_refuses_when_no_backend_is_available(monkeypatch):
    monkeypatch.setattr(secret_ref, "_override", [])
    monkeypatch.setattr(secret_ref, "BACKENDS", ())
    with pytest.raises(secret_ref.NoStore):
        secret_ref.backend()
    assert "no OS secret store" in secret_ref.store_reason()
