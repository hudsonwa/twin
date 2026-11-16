# Design: a twin on another computer from one prompt (twin#70)

Status: **design + experimental prototype**. `hermes twin remote-create` is hidden from `hermes twin --help`, prints
`EXPERIMENTAL` first, and nothing else calls it. Shipped behaviour does not change.

## What the owner asked for

One prompt ("put Acme Support on example-desktop too") makes an instance "Acme Support 2" of a twin on another
computer, with no other setup there. Today that needs Hermes and the plugin installed on the target and a link code
typed on it ([SHARING.md](../SHARING.md)).

## Command and tool

```
hermes twin remote-create COMPUTER TWIN --plan              # every remote command, runs none
hermes twin remote-create COMPUTER TWIN --yes [--install-hermes]
```

The tool `twin_remote_create(computer, twin)` (later, not in the prototype) calls the same code, and like
`requests on` it is one explicit owner prompt that names the computer. A bot cannot pass `--install-hermes` on its
own initiative.

COMPUTER is an SSH host name or alias from the owner's own `~/.ssh/config` (checked against `[A-Za-z0-9._-]`, so it
cannot smuggle an ssh option), or, in v2, an already-linked fleet computer.

## Steps: one PASS/FAIL line each

Every line is `PASS: remote-create COMPUTER STEP: reason` or `FAIL: ...`; the first FAIL ends the run. Each changing
step has a read-only probe; when the probe passes the step prints `already done`, so a re-run continues where it
stopped.

| # | Step | Remote command (all over `ssh -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=yes`) | Changes |
|---|---|---|---|
| 1 | reach | `true` | no |
| 2 | detect | `uname -s; uname -m`, where `hermes` is, `hermes --version` | no |
| 3 | hermes | Hermes' own installer, pinned URL + SHA-256, `--non-interactive`; only with `--install-hermes` | yes |
| 4 | plugin | `hermes plugins install hudsonwa/twin --ref COMMIT --enable` (COMMIT = this plugin's own commit) | yes |
| 5 | setup | `hermes twin setup --auto` (link side: the target needs no Grok app, no botport) | yes |
| 6 | link | `hermes twin setup --link CODE --yes`; CODE is made locally and never shown | yes |
| 7 | instance | make "Name N" (N = next free across the fleet, from fleet state) | yes |
| 8 | check | count key lines in the target's own `.env` (prints a number, never a value) | no |

FAIL wording the accept criteria require:

- unreachable: `FAIL: ... reach: cannot reach it with your SSH key (...); paste this one line there: hermes plugins
  install hudsonwa/twin --ref COMMIT --enable && hermes twin setup --auto && hermes twin setup --link CODE --yes`
  (the floor: a computer with neither SSH nor a link needs one pasted line).
- no key: `FAIL: ... check: the twin needs a key on that computer (no key is copied; docs/SECRETS.md)`.
- Hermes missing without opt-in: `FAIL: ... detect: Linux: Hermes is missing; add --install-hermes ...`.
- Hermes too old (< 0.22.7): `FAIL: ... detect: Linux: Hermes 0.22.4 is older than 0.22.7; update it there first`.

## Hard limits

- **`--plan` first.** Without `--plan` the command needs `--yes`; `--plan` opens no SSH connection at all.
- **No sudo**, ever (a test asserts no remote command contains it). No package manager, no system service.
- **`--install-hermes` is a separate opt-in**, never implied by "make a twin": it runs Hermes' *own* installer at a
  pinned version, checked against a SHA-256 this plugin version carries, the same way botport pins work
  (`twin/botport_pins.json`). Until such a pin exists the step FAILs instead of piping an unpinned script to a shell.
- **The plugin is pinned and attested**: the exact commit of the plugin doing the create; nothing floats.
- **Credentials stay per machine.** The target gets the model name/provider only. No key, token, `.env` or twin
  pass is copied. `secret share --linked` can move a key by reference only if the owner already turned it on.
- **The log stays local**; the target keeps only what Hermes and the plugin write there.
- **Windows targets are v2.** Linking a Windows computer by hand works; SSH-push to Windows is not built
  (`FAIL: ... SSH to Windows is not built yet (v2); paste this one line there: ...`).
- The Telegram bot for "Name 2" still needs its one confirm-tap (twin#6x managed bots).

## Instances, not copies

An instance follows the same Grok bot read-only, like a linked copy, but has its own chats, memory and (later)
Telegram bot. Writes back to Grok stay with one computer (the one-runner rule for routines). The name is
"Acme Support 2", profile `acme-support-2`; N is the next free number across the whole fleet so two computers never
both make a "2".

## The prototype (twin/remote_create.py)

- All remote work goes through one injectable `Runner(host, command, timeout) -> (rc, stdout, stderr)`; the real one
  is the owner's `ssh` with BatchMode. Tests use a fake SSH runner with the invented host `example-desktop`
  covering Linux, macOS, Windows, Hermes missing, Hermes present-but-broken, Hermes too old, unreachable, no key,
  and a re-run that skips done steps (`tests/test_remote_create.py`).
- Hidden test-only options: `--remote-hermes-home PATH` (every remote `hermes` call runs with that HERMES_HOME;
  for live tests in a throwaway folder) and `--stop-after STEP`.
- Not built yet: the `instance` remote command (`hermes twin instance create`) needs fleet-wide naming (idea item 7),
  the local link-code hand-off in `execute` is a callable the CLI does not wire up yet, and the agent tool.

## Found in the live test (Linux test computer, 2026-11-16)

A throwaway `HERMES_HOME` cannot run Hermes: the Hermes install lives inside the default home
(`~/.hermes/hermes-agent`) and refuses another home with "no dependency environment is committed for this install".
So detect now tells "Hermes is there but does not run with HERMES_HOME=..." apart from "Hermes is missing". A fully
isolated live test of steps 3-8 needs Hermes installed into the throwaway home itself, i.e. `--install-hermes` with a
pinned installer.

## Live test 2 (Linux test computer, 2026-11-17)

Hermes 0.23.1 was installed with its own `install.sh --non-interactive` into a throwaway `HOME` (so its launcher, shell
rc lines and `~/.hermes` all stayed inside the test folder); the computer's own Hermes (0.22.4) was not touched.
remote-create then ran over real SSH with every command prefixed by that `HOME`:

- `--plan`: 7 steps listed, 0 SSH calls.
- An unknown host: one FAIL line ending in the paste line.
- reach, detect (`Linux, Hermes 0.23.1`), plugin (pinned commit), setup: PASS. A re-run printed `plugin: already
  done`. Fixed from this run: the plugin probe (Hermes prints `enabled  git pinned@... NAME`, name last) and the setup
  probe (`setup --check` fails on a link target by design, so setup has no probe and simply runs again).
- link: FAIL `no link code` as expected; a real link needs a sharing computer with twins (a Grok app), which the
  test computer does not have. The check step's key count there was 0, so it would FAIL with "needs a key".
- The CLI now hands a fresh local link code to the link step (never printed), and when the owner already shared
  secrets with linked computers the check step runs `hermes twin secret pull` there (by reference over the link);
  otherwise nothing secret is touched.
