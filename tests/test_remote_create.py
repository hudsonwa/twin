"""twin#70 remote-create prototype (twin/remote_create.py): a fake SSH runner, invented host `example-desktop`.

No network: every remote command goes to FakeSSH, which answers from a small table of what the target has.
"""
from __future__ import annotations

import argparse
import io
from contextlib import redirect_stdout

from twin_testlib import cli, home  # noqa: F401

pytestmark = __import__("pytest").mark.usefixtures("home")
from hermes_plugins.grok_bot_twin.twin import remote_create as RC

REF = "0" * 40


class FakeSSH:
    def __init__(self, system="Linux", hermes="Hermes Agent v0.22.9 (2026.11.1)", reachable=True, keys=1,
                 done=(), pull_gives=0):
        self.system, self.hermes, self.reachable, self.keys, self.done = system, hermes, reachable, keys, set(done)
        self.pull_gives = pull_gives
        self.calls = []

    def __call__(self, host, cmd, timeout):
        self.calls.append(cmd)
        assert host == "example-desktop"
        assert "sudo" not in cmd
        if not self.reachable:
            return 255, "", "ssh: connect to host example-desktop port 22: No route to host"
        if cmd == "true":
            return 0, "", ""
        if cmd.startswith("uname -s"):
            path = "/home/u/.local/bin/hermes" if self.hermes else "-"
            return 0, f"{self.system}\nx86_64\n{path}\n{self.hermes}\n", ""
        if cmd.endswith("--version") and not self.hermes:
            return 127, "", "hermes: not found"
        if "secret pull" in cmd:
            self.keys += self.pull_gives
            return 0, "PASS: 1 secret(s) kept from the computer that shares\n", ""
        if cmd.startswith("grep -cE"):
            return 0, f"{self.keys}\n", ""
        for name in self.done:
            if name in cmd and ("list" in cmd or "--check" in cmd or "fleet --json" in cmd or "status --json" in cmd):
                return 0, "", ""
        if " list " in cmd or "--check" in cmd or "--json" in cmd or cmd.startswith("test -d"):
            return 1, "", ""
        return 0, "ok\n", ""


def args(**kw):
    d = dict(computer="example-desktop", twin="Acme Support", plan=False, yes=True, install_hermes=False,
             remote_hermes_home="", stop_after="")
    d.update(kw)
    return argparse.Namespace(**d)


def run(fake, **kw):
    lines = []
    rc = RC.cmd_remote_create(args(**kw), runner=fake, out=lines.append, ref=REF,
                              link_code=lambda: "7KQ4-M2XD-P9RA", shared_secrets=lambda: [])
    return rc, lines


def test_plan_lists_every_command_and_runs_nothing():
    fake = FakeSSH()
    rc, lines = run(fake, plan=True, yes=False)
    assert rc == 0 and fake.calls == []
    text = "\n".join(lines)
    for step in ("reach", "detect", "plugin", "setup", "link", "instance", "check"):
        assert f". {step}" in text
    assert f"--ref {REF}" in text and "sudo " not in text and "No key, token or .env is copied" in text


def test_needs_yes_without_plan():
    fake = FakeSSH()
    assert run(fake, yes=False)[0] == 2 and fake.calls == []


def test_linux_happy_path_every_step_a_line():
    fake = FakeSSH()
    rc, lines = RC.execute(RC.Target("example-desktop"), "Acme Support", ref=REF, install_hermes=False,
                           runner=fake, out=(out := []).append, link_code=lambda: "7KQ4-M2XD-P9RA"), None
    assert rc == 0, out
    assert [x.split(":")[1].split()[-1] for x in out] == ["reach", "detect", "plugin", "setup", "link", "instance",
                                                         "check"]
    assert all(x.startswith("PASS") for x in out)
    assert any("--link 7KQ4-M2XD-P9RA" in c for c in fake.calls)
    assert any("'Acme Support 2'" in c for c in fake.calls)


def test_macos_detected():
    out = []
    RC.execute(RC.Target("example-desktop"), "Acme Support", ref=REF, install_hermes=False,
               runner=FakeSSH(system="Darwin"), out=out.append, stop_after="detect")
    assert out[1] == "PASS: remote-create example-desktop detect: Darwin, Hermes 0.22.9"


def test_hermes_missing_fails_without_opt_in():
    fake = FakeSSH(hermes="")
    rc, lines = run(fake)
    assert rc == 1 and "Hermes is missing; add --install-hermes" in lines[-1]
    assert not any("plugins install" in c for c in fake.calls)


def test_install_hermes_refuses_unpinned_installer():
    rc, lines = run(FakeSSH(hermes=""), install_hermes=True)
    assert rc == 1 and lines[-1].startswith("FAIL: remote-create example-desktop hermes: no pinned Hermes installer")


def test_hermes_present_but_broken_for_this_home():
    fake = FakeSSH(hermes="hermes: no dependency environment is committed for this install")
    rc, lines = run(fake, remote_hermes_home="/home/u/twin-remote-test/x/hermes-home")
    assert rc == 1 and "Hermes is at /home/u/.local/bin/hermes but does not run with HERMES_HOME=" in lines[-1]


def test_old_hermes_fails():
    rc, lines = run(FakeSSH(hermes="Hermes Agent v0.22.4 (2026.9.24)"))
    assert rc == 1 and "older than 0.22.7" in lines[-1]


def test_unreachable_gives_the_paste_line():
    rc, lines = run(FakeSSH(reachable=False))
    assert rc == 1 and "paste this one line there: hermes plugins install hudsonwa/twin --ref " + REF in lines[-1]


def test_windows_is_v2():
    rc, lines = run(FakeSSH(system="MINGW64_NT-10.0"))
    assert rc == 1 and "Windows is not built yet (v2)" in lines[-1]


def test_no_key_fails_check_and_copies_nothing():
    fake = FakeSSH(keys=0)
    out = []
    rc = RC.execute(RC.Target("example-desktop"), "Acme Support", ref=REF, install_hermes=False, runner=fake,
                    out=out.append, link_code=lambda: "7KQ4-M2XD-P9RA")
    assert rc == 1 and "needs a key on that computer" in out[-1]
    assert not any(".env" in c and ("scp" in c or "cat " in c or ">" in c.split(".env")[0][-3:]) for c in fake.calls)


def test_rerun_skips_done_steps():
    fake = FakeSSH(done=("grok-bot-twin", "setup --check"))
    out = []
    RC.execute(RC.Target("example-desktop"), "Acme Support", ref=REF, install_hermes=False, runner=fake,
               out=out.append, stop_after="setup")
    assert "PASS: remote-create example-desktop plugin: already done" in out
    assert not any(c.endswith(f"--ref {REF} --enable") for c in fake.calls)


def test_remote_hermes_home_prefixes_every_hermes_call():
    steps = RC.plan(RC.Target("example-desktop", hermes_home="/home/u/twin-remote-test/x/hermes-home"),
                    "Acme Support", ref=REF, install_hermes=False)
    for s in steps:
        if "hermes" in s.command and s.name not in ("reach",):
            assert "HERMES_HOME=/home/u/twin-remote-test/x/hermes-home" in s.command or \
                   "/home/u/twin-remote-test/x/hermes-home" in s.command


def test_bad_host_refused():
    rc, lines = run(FakeSSH(), computer="-oProxyCommand=evil")
    assert rc == 2 and lines[-1].startswith("FAIL")


def test_instance_name_next_free():
    assert RC.instance_name("Acme Support", ["Acme Support 2", "Acme Support 3"]) == "Acme Support 4"


def test_hidden_from_help():
    buf = io.StringIO()
    with redirect_stdout(buf):
        try:
            cli.main(["--help"])
        except SystemExit:
            pass
    assert "remote-create" not in buf.getvalue()


# ---- twin#70 Accept: fake SSH runner, invented host example-desktop ----

def _full(fake, **kw):
    out = []
    rc = RC.execute(RC.Target("example-desktop"), "Acme Support", ref=REF, install_hermes=False, runner=fake,
                    out=out.append, link_code=lambda: "7KQ4-M2XD-P9RA", **kw)
    return rc, out


def test_macos_full_run_passes_every_step():
    rc, out = _full(FakeSSH(system="Darwin"))
    assert rc == 0 and all(x.startswith("PASS: remote-create example-desktop ") for x in out)
    assert [x.split()[3].rstrip(":") for x in out] == ["reach", "detect", "plugin", "setup", "link", "instance",
                                                      "check"]


def test_linux_hermes_missing_runs_nothing_that_changes():
    fake = FakeSSH(system="Linux", hermes="")
    rc, out = _full(fake)
    assert rc == 1 and out[-1] == ("FAIL: remote-create example-desktop detect: Linux: Hermes is missing; add "
                                   "--install-hermes to install it there (its own pinned installer, no sudo)")
    assert fake.calls[0] == "true" and fake.calls[1].startswith("uname -s") and len(fake.calls) == 2


def test_plan_opens_no_ssh_and_lists_each_remote_command():
    fake = FakeSSH()
    rc, lines = run(fake, plan=True, yes=False, install_hermes=True)
    assert rc == 0 and fake.calls == []
    steps = RC.plan(RC.Target("example-desktop"), "Acme Support", ref=REF, install_hermes=True)
    for s in steps:
        assert any(s.command in x for x in lines)
        if s.probe:
            assert any(s.probe in x for x in lines)


def test_unreachable_is_one_fail_line_with_the_paste_line():
    rc, lines = run(FakeSSH(reachable=False))
    fails = [x for x in lines if x.startswith("FAIL")]
    assert rc == 1 and len(fails) == 1 and fails[0] == lines[-1]
    assert fails[0].endswith("paste this one line there: " + RC.paste_line(REF))


def test_no_key_and_sharing_off_never_pulls():
    fake = FakeSSH(keys=0, pull_gives=1)
    rc, out = _full(fake, shared_secrets=lambda: [])
    assert rc == 1 and out[-1].endswith("check: the twin needs a key on that computer (no key is copied; "
                                        "docs/SECRETS.md)")
    assert not any("secret" in c for c in fake.calls)


def test_no_key_with_linked_sharing_on_pulls_by_reference():
    fake = FakeSSH(keys=0, pull_gives=1)
    rc, out = _full(fake, shared_secrets=lambda: ["OPENAI_API_KEY"])
    assert rc == 0 and out[-1] == ("PASS: remote-create example-desktop check: a model key is set there (fetched by "
                                   "reference: OPENAI_API_KEY)")
    assert sum("twin secret pull" in c for c in fake.calls) == 1
    assert not any("OPENAI_API_KEY" in c for c in fake.calls)


def test_sharing_on_but_pull_brings_nothing_still_fails():
    fake = FakeSSH(keys=0, pull_gives=0)
    rc, out = _full(fake, shared_secrets=lambda: ["OPENAI_API_KEY"])
    assert rc == 1 and "needs a key on that computer" in out[-1]


def test_link_code_is_sent_but_never_printed():
    fake = FakeSSH()
    rc, out = _full(fake)
    assert rc == 0 and any("--link 7KQ4-M2XD-P9RA" in c for c in fake.calls)
    assert not any("7KQ4" in x for x in out)


# ---- instances, fleet-wide naming, installer pin, the agent tool (twin#70 remaining gaps) ----

import json as _json

from hermes_plugins.grok_bot_twin.twin import instances as INST

PIN = {"version": "0.23.1", "url": "https://example.invalid/hermes/v0.23.1/install.sh", "sha256": "ab" * 32}


class FleetSSH(FakeSSH):
    def __init__(self, names=(), **kw):
        super().__init__(**kw)
        self.names = list(names)

    def __call__(self, host, cmd, timeout):
        if cmd.endswith("twin instance list --json"):
            self.calls.append(cmd)
            return 0, _json.dumps({"instances": [{"name": n} for n in self.names]}), ""
        return super().__call__(host, cmd, timeout)


def test_instance_create_and_list_local():
    rec = INST.create("Acme Support")
    assert rec["name"] == "Acme Support 2" and rec["profile"] == "acme-support-2" and rec["created"]
    assert INST.create("Acme Support", "Acme Support 2")["created"] is False
    assert INST.create("Acme Support")["name"] == "Acme Support 3"
    assert [r["name"] for r in INST.load()] == ["Acme Support 2", "Acme Support 3"]


def test_instance_cli_needs_yes_and_lists_json():
    out = []
    a = argparse.Namespace(what="create", twin="Acme Support", name="", yes=False, json=False)
    assert INST.cmd_instance(a, out=out.append) == 2 and INST.load() == []
    a.yes = True
    assert INST.cmd_instance(a, out=out.append) == 0 and out[-1].startswith("PASS: instance 'Acme Support 2'")
    out.clear()
    INST.cmd_instance(argparse.Namespace(what="list", twin="", name="", yes=False, json=True), out=out.append)
    assert _json.loads(out[0])["instances"][0]["name"] == "Acme Support 2"


def test_instance_bad_name_refused():
    assert INST.cmd_instance(argparse.Namespace(what="create", twin="a/b", name="", yes=True, json=False),
                             out=lambda _x: None) == 2


def test_remote_instance_name_is_next_free_across_fleet():
    fake = FleetSSH(names=["Acme Support 2"])
    out = []
    rc = RC.execute(RC.Target("example-desktop"), "Acme Support", ref=REF, install_hermes=False, runner=fake,
                    out=out.append, link_code=lambda: "7KQ4-M2XD-P9RA", local_names=lambda: ["Acme Support 3"])
    assert rc == 0, out
    assert any("--name 'Acme Support 4'" in c for c in fake.calls)
    assert not any("'Acme Support 2' --yes" in c for c in fake.calls)


def test_installer_pin_placeholder_is_not_a_pin(tmp_path):
    assert RC.installer_pin() is None  # the shipped file is a placeholder until a real digest is pinned
    p = tmp_path / "pin.json"
    p.write_text(_json.dumps({"installer": PIN}))
    assert RC.installer_pin(p) == PIN
    for bad in ({**PIN, "sha256": "x" * 64}, {**PIN, "url": "http://example.invalid/i.sh"},
                {**PIN, "url": "https://example.invalid/i.sh; rm"}, {**PIN, "version": "latest"}):
        p.write_text(_json.dumps({"installer": bad}))
        assert RC.installer_pin(p) is None


def test_install_hermes_with_pin_checks_digest_before_running():
    fake = FakeSSH(hermes="")
    out = []
    rc = RC.execute(RC.Target("example-desktop"), "Acme Support", ref=REF, install_hermes=True, runner=fake,
                    out=out.append, link_code=lambda: "7KQ4-M2XD-P9RA", pin=lambda: PIN, stop_after="hermes")
    assert rc == 0 and out[-2] == "PASS: remote-create example-desktop hermes: done", out
    cmd = next(c for c in fake.calls if "curl" in c)
    assert PIN["url"] in cmd and PIN["sha256"] in cmd and "--proto =https" in cmd
    assert cmd.index(PIN["sha256"]) < cmd.index('sh "$f" --non-interactive') and "sudo" not in cmd
    assert "| sh " not in cmd and "|sh " not in cmd  # never curl | sh


def test_install_hermes_without_pin_runs_nothing_that_changes():
    fake = FakeSSH(hermes="")
    out = []
    rc = RC.execute(RC.Target("example-desktop"), "Acme Support", ref=REF, install_hermes=True, runner=fake,
                    out=out.append, pin=lambda: None)
    assert rc == 1 and "no pinned Hermes installer" in out[-1] and len(fake.calls) == 2


def _tool(args, fake, t=[1000.0]):
    return RC.remote_create_tool(args, runner=fake, ref=REF, now=lambda: t[0])


def test_tool_plans_first_and_needs_the_owners_confirm(monkeypatch):
    monkeypatch.setattr(RC, "_local_link_code", lambda: "7KQ4-M2XD-P9RA")
    monkeypatch.setattr(RC, "_linked_shared_secrets", lambda: [])
    fake = FleetSSH()
    first = _tool({"computer": "example-desktop", "twin": "Acme Support"}, fake)
    assert first["verdict"].startswith("PLAN:") and fake.calls == [] and first["confirm"]
    assert any(". instance" in x for x in first["lines"])
    assert _tool({"computer": "example-desktop", "twin": "Acme Support", "confirm": "nope"}, fake)[
        "verdict"].startswith("FAIL") and fake.calls == []
    done = _tool({"computer": "example-desktop", "twin": "Acme Support", "confirm": first["confirm"]}, fake)
    assert done["verdict"] == "PASS: remote-create example-desktop: every step passed", done
    assert not any("--install-hermes" in c or "curl" in c for c in fake.calls)
    again = _tool({"computer": "example-desktop", "twin": "Acme Support", "confirm": first["confirm"]}, fake)
    assert again["verdict"].startswith("FAIL") and "not for this computer" in again["verdict"]  # one use


def test_tool_confirm_is_tied_to_computer_twin_and_time():
    fake = FleetSSH()
    first = _tool({"computer": "example-desktop", "twin": "Acme Support"}, fake)
    other = _tool({"computer": "example-desktop", "twin": "Other Bot", "confirm": first["confirm"]}, fake)
    assert "not for this computer" in other["verdict"] and fake.calls == []
    first = _tool({"computer": "example-desktop", "twin": "Acme Support"}, fake)
    late = RC.remote_create_tool({"computer": "example-desktop", "twin": "Acme Support", "confirm": first["confirm"]},
                                 runner=fake, ref=REF, now=lambda: 1000.0 + RC.APPROVE_S + 1)
    assert "older than 10 minutes" in late["verdict"] and fake.calls == []


def test_tool_refuses_messaging_and_bad_host():
    fake = FleetSSH()
    r = _json.loads(RC.twin_remote_create({"computer": "example-desktop", "twin": "Acme Support"},
                                          platform="telegram"))
    assert r["verdict"].startswith("FAIL") and "messaging" in r["verdict"]
    r = _tool({"computer": "-oProxyCommand=x", "twin": "Acme Support"}, fake)
    assert r["verdict"].startswith("FAIL") and fake.calls == []


def test_tool_is_registered():
    from hermes_plugins.grok_bot_twin import __init__ as _pkg  # noqa: F401
    assert RC.TWIN_REMOTE_CREATE_SCHEMA["name"] == RC.TOOL == "twin_remote_create"
    assert "install_hermes" not in _json.dumps(RC.TWIN_REMOTE_CREATE_SCHEMA["parameters"])
