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
                 done=()):
        self.system, self.hermes, self.reachable, self.keys, self.done = system, hermes, reachable, keys, set(done)
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
    rc = RC.cmd_remote_create(args(**kw), runner=fake, out=lines.append, ref=REF)
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
