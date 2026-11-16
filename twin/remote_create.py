"""EXPERIMENTAL (twin#70): make a twin on another computer over SSH, one PASS/FAIL line per step.

Design: docs/design/remote-create.md. Hidden from `hermes twin --help`; nothing else calls it. Every remote command
goes through one injectable runner (`Runner`), so tests use a fake SSH runner and never touch the network.

`hermes twin remote-create COMPUTER TWIN --plan` lists every remote command and runs none of them (no SSH at all).
Without --plan it needs --yes. A step whose probe already passes is skipped, so a re-run continues where it stopped.
Hard limits: no sudo, no key copied, Hermes is installed only with --install-hermes, Windows targets are v2.
"""
from __future__ import annotations

import re
import shlex
import subprocess
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional, Tuple

MIN_HERMES = (0, 22, 7)
# Hermes' own installer, pinned (twin#70: the exact URL and digest are filled in when the installer publishes a
# versioned script; until then --install-hermes FAILs instead of piping an unpinned script to a shell).
HERMES_INSTALLER_URL = ""
HERMES_INSTALLER_SHA256 = ""
SSH_OPTS = ("-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-o", "StrictHostKeyChecking=yes")
_HOST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,252}$")
_VER_RE = re.compile(r"v?(\d+)\.(\d+)\.(\d+)")

# runner(host, remote_command, timeout_s) -> (exit status, stdout, stderr)
Runner = Callable[[str, str, int], Tuple[int, str, str]]


def ssh_runner(host: str, command: str, timeout: int) -> Tuple[int, str, str]:
    """The real runner: the owner's own ssh with BatchMode (never a password prompt)."""
    try:
        p = subprocess.run(["ssh", *SSH_OPTS, host, "--", command], capture_output=True, timeout=timeout,
                           stdin=subprocess.DEVNULL, check=False)
        return p.returncode, p.stdout.decode(errors="replace"), p.stderr.decode(errors="replace")
    except subprocess.TimeoutExpired:
        return 255, "", "timed out"
    except OSError as e:
        return 255, "", str(e)


@dataclass
class Step:
    name: str
    command: str            # the one remote command this step runs (shown by --plan)
    probe: str = ""         # read-only; exit 0 means the step is already done
    timeout: int = 60
    changes: bool = True


@dataclass
class Target:
    host: str
    hermes_home: str = ""   # EXPERIMENTAL: a throwaway HERMES_HOME on the target, for tests
    os: str = ""
    hermes: Optional[Tuple[int, int, int]] = None
    notes: List[str] = field(default_factory=list)


def check_host(host: str) -> Optional[str]:
    return None if _HOST_RE.match(host or "") else "COMPUTER must be an SSH host name or alias (letters, digits, . _ -)"


def instance_name(twin: str, taken: List[str]) -> str:
    """Next free "Name N" across the whole fleet (N starts at 2; "Name" itself is the first instance)."""
    have = set(taken)
    n = 2
    while f"{twin} {n}" in have:
        n += 1
    return f"{twin} {n}"


def _env(t: Target) -> str:
    return f"HERMES_HOME={shlex.quote(t.hermes_home)} " if t.hermes_home else ""


def _hermes(t: Target, args: str) -> str:
    # Absolute-ish lookup: a non-interactive ssh shell often lacks ~/.local/bin on PATH.
    return f'{_env(t)}"$(command -v hermes || echo $HOME/.local/bin/hermes)" {args}'


def plan(t: Target, twin: str, *, ref: str, install_hermes: bool, link_code: str = "CODE",
         name: str = "") -> List[Step]:
    q = shlex.quote
    name = name or instance_name(twin, [])
    steps = [
        Step("reach", "true", changes=False, timeout=20),
        Step("detect", "uname -s; uname -m; (command -v hermes || ls $HOME/.local/bin/hermes 2>/dev/null || echo -); "
                       + _hermes(t, "--version") + " 2>&1 | head -1", changes=False),
    ]
    if t.hermes_home:
        steps.append(Step("home", f"mkdir -p {q(t.hermes_home)}", probe=f"test -d {q(t.hermes_home)}"))
    if install_hermes:
        steps.append(Step("hermes", f"curl -fsSL {q(HERMES_INSTALLER_URL or '<pinned-installer-url>')} -o "
                                    f"/tmp/hermes-install.sh && echo {q(HERMES_INSTALLER_SHA256 or '<sha256>')}"
                                    "'  /tmp/hermes-install.sh' | sha256sum -c - && sh /tmp/hermes-install.sh "
                                    "--non-interactive", probe=_hermes(t, "--version"), timeout=600))
    steps += [
        Step("plugin", _hermes(t, f"plugins install hudsonwa/twin --ref {q(ref or '<commit>')} --enable"),
             probe=_hermes(t, "plugins list --enabled --plain --no-bundled") + " | grep -qw grok-bot-twin",
             timeout=300),
        # No probe: `setup --check` fails on a link target by design (no Grok app there), and `setup --auto` is
        # idempotent, so a re-run simply runs it again (live test 2026-11-17).
        Step("setup", _hermes(t, "twin setup --auto"), timeout=300),
        Step("link", _hermes(t, f"twin setup --link {q(link_code)} --yes"),
             probe=_hermes(t, "twin fleet --json") + " | grep -q '\"role\": *\"follower\"'", timeout=120),
        Step("instance", _hermes(t, f"twin instance create {q(twin)} --name {q(name)} --yes"),
             probe=_hermes(t, f"twin status --json") + f" | grep -qF {q(name)}", timeout=120),
        # Counts key lines in the target's own .env; never prints a value, nothing is copied.
        Step("check", "grep -cE '^[A-Z0-9_]*(API_KEY|TOKEN)=.+' \"${HERMES_HOME:-$HOME/.hermes}/.env\" "
                      "2>/dev/null || true" if not t.hermes_home else
             f"grep -cE '^[A-Z0-9_]*(API_KEY|TOKEN)=.+' {q(t.hermes_home + '/.env')} 2>/dev/null || true",
             changes=False),
    ]
    return steps


def paste_line(ref: str, code: str = "CODE") -> str:
    """The floor: the one line to paste on a computer this one cannot reach."""
    return (f"hermes plugins install hudsonwa/twin --ref {ref or '<commit>'} --enable && "
            f"hermes twin setup --auto && hermes twin setup --link {code} --yes")


def _ver(text: str) -> Optional[Tuple[int, int, int]]:
    m = _VER_RE.search(text or "")
    return tuple(int(x) for x in m.groups()) if m else None  # type: ignore[return-value]


def _count(text: str) -> int:
    last = (text or "").strip().splitlines()[-1:] or ["0"]
    return int(last[0]) if last[0].isdigit() else 0


def _local_link_code() -> str:
    """A fresh one-computer link code from this computer's fleet (never printed)."""
    try:
        from .fleet_cli import _svc
        return str(_svc().fleet_code()["code"]["code"])
    except Exception:
        return ""


def _linked_shared_secrets() -> List[str]:
    """Names of secrets the owner already shared with linked computers (`secret share NAME --linked`)."""
    try:
        from . import secret_ref
        return sorted(n for n, rec in secret_ref.load().items() if rec.get("linked"))
    except Exception:
        return []


def execute(t: Target, twin: str, *, ref: str, install_hermes: bool, runner: Runner,
            out: Callable[[str], None], link_code: Callable[[], str] = lambda: "",
            shared_secrets: Callable[[], List[str]] = lambda: [], stop_after: str = "") -> int:
    """Run the plan step by step. Returns 0 when every step passed, else 1 (the last line is a FAIL)."""
    def line(ok: bool, step: str, why: str) -> None:
        out(f"{'PASS' if ok else 'FAIL'}: remote-create {t.host} {step}: {why}")

    steps = plan(t, twin, ref=ref, install_hermes=install_hermes)
    for s in steps:
        if s.name == "reach":
            rc, _, err = runner(t.host, s.command, s.timeout)
            if rc != 0:
                line(False, "reach", f"cannot reach it with your SSH key ({(err.strip() or 'ssh failed')[:120]}); "
                                     f"paste this one line there: {paste_line(ref)}")
                return 1
            line(True, "reach", "SSH with your key works")
        elif s.name == "detect":
            rc, so, _ = runner(t.host, s.command, s.timeout)
            parts = so.split("\n")
            t.os = (parts[0] if parts else "").strip()
            path = parts[2].strip() if len(parts) > 2 else "-"
            said = parts[3].strip() if len(parts) > 3 else ""
            t.hermes = _ver(said) if path not in ("", "-") else None
            if t.os not in ("Linux", "Darwin"):
                line(False, "detect", f"{t.os or 'unknown system'}: SSH to Windows is not built yet (v2); "
                                      f"paste this one line there: {paste_line(ref)}")
                return 1
            if path not in ("", "-") and t.hermes is None:
                where = f" with HERMES_HOME={t.hermes_home}" if t.hermes_home else ""
                line(False, "detect", f"{t.os}: Hermes is at {path} but does not run{where} ({said[:120]})")
                return 1
            if t.hermes is None and not install_hermes:
                line(False, "detect", f"{t.os}: Hermes is missing; add --install-hermes to install it there "
                                      "(its own pinned installer, no sudo)")
                return 1
            if t.hermes is not None and t.hermes < MIN_HERMES:
                line(False, "detect", f"{t.os}: Hermes {'.'.join(map(str, t.hermes))} is older than "
                                      f"{'.'.join(map(str, MIN_HERMES))}; update it there first")
                return 1
            line(True, "detect", f"{t.os}, Hermes "
                 + ('.'.join(map(str, t.hermes)) if t.hermes else "missing (will install)"))
        else:
            if s.name == "hermes" and not (HERMES_INSTALLER_URL and HERMES_INSTALLER_SHA256):
                line(False, "hermes", "no pinned Hermes installer in this plugin version yet; install Hermes there "
                                      "yourself, then run this again")
                return 1
            if s.name == "hermes" and t.hermes is not None:
                line(True, "hermes", "already installed")
                continue
            if s.name == "check":
                rc, so, _ = runner(t.host, s.command, s.timeout)
                n = _count(so)
                shared = shared_secrets() if n < 1 else []
                if n < 1 and shared:
                    # Secret sharing is on here: the target fetches them over the link by reference (the same
                    # `secret pull` a linked computer runs). Nothing goes over this SSH session.
                    rc, so2, err = runner(t.host, _hermes(t, "twin secret pull"), 120)
                    n = _count(runner(t.host, s.command, s.timeout)[1]) if rc == 0 else 0
                    if n >= 1:
                        line(True, "check", f"a model key is set there (fetched by reference: {', '.join(shared)})")
                        continue
                if n < 1:
                    line(False, "check", "the twin needs a key on that computer (no key is copied; "
                                         "docs/SECRETS.md)")
                    return 1
                line(True, "check", "a model key is set there")
            else:
                if s.probe and runner(t.host, s.probe, s.timeout)[0] == 0:
                    line(True, s.name, "already done")
                else:
                    cmd = s.command
                    if s.name == "link":
                        code = link_code()
                        if not code:
                            line(False, "link", "no link code: on this computer `hermes twin share code` needs "
                                                "sharing on")
                            return 1
                        cmd = cmd.replace(shlex.quote("CODE"), shlex.quote(code))
                    rc, so, err = runner(t.host, cmd, s.timeout)
                    if rc != 0:
                        tail = (err.strip() or so.strip()).splitlines()[-1:] or ["exit " + str(rc)]
                        line(False, s.name, tail[0][:200])
                        return 1
                    line(True, s.name, "done")
        if stop_after and s.name == stop_after:
            out(f"(stopped after {stop_after}, as asked)")
            return 0
    return 0


# ---- CLI (hidden, experimental) ----

def cmd_remote_create(a: Any, *, runner: Optional[Runner] = None, out: Callable[[str], None] = print,
                      ref: Optional[str] = None, link_code: Callable[[], str] = _local_link_code,
                      shared_secrets: Callable[[], List[str]] = _linked_shared_secrets) -> int:
    err = check_host(a.computer)
    if err:
        out(f"FAIL: remote-create: {err}")
        return 2
    if ref is None:
        try:
            from .auto_setup import plugin_ref
            ref = plugin_ref()
        except Exception:
            ref = ""
    t = Target(a.computer, hermes_home=a.remote_hermes_home or "")
    out("EXPERIMENTAL (twin#70): remote-create is a prototype.")
    if a.plan:
        out(f"Plan for {a.twin!r} on {a.computer} (nothing runs; every command goes over "
            f"ssh {' '.join(SSH_OPTS)} {a.computer}):")
        for i, s in enumerate(plan(t, a.twin, ref=ref, install_hermes=a.install_hermes), 1):
            out(f"{i}. {s.name}{'' if s.changes else ' (read-only)'}: {s.command}")
            if s.probe:
                out(f"   skipped when already done: {s.probe}")
        out("No key, token or .env is copied over SSH. No sudo. If a key is missing there and you already shared "
            "secrets with linked computers (`hermes twin secret share NAME --linked`), the check step runs "
            "`hermes twin secret pull` there, which fetches them by reference over the link.")
        return 0
    if not a.yes:
        out("FAIL: remote-create: show the plan first (--plan), then run again with --yes")
        return 2
    return execute(t, a.twin, ref=ref, install_hermes=a.install_hermes, runner=runner or ssh_runner, out=out,
                   link_code=link_code, shared_secrets=shared_secrets, stop_after=a.stop_after or "")


def setup(subs: Any) -> None:
    import argparse
    p = subs.add_parser("remote-create")  # no help=: kept out of `hermes twin --help` while experimental
    p.add_argument("computer")
    p.add_argument("twin")
    p.add_argument("--plan", action="store_true")
    p.add_argument("--yes", action="store_true")
    p.add_argument("--install-hermes", action="store_true")
    p.add_argument("--remote-hermes-home", default="", help=argparse.SUPPRESS)
    p.add_argument("--stop-after", default="", help=argparse.SUPPRESS)


HANDLERS = {"remote-create": lambda a: cmd_remote_create(a)}
