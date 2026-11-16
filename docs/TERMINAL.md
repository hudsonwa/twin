# Grok Bot Twin in the terminal

Everything on the Twins page has a command. Plain `hermes twin` prints your twins and the one next step.

Install with the line in the [README's Install section](../README.md#install).

```sh
hermes twin            # your twins and what to do next
hermes twin demo       # a sample twin with invented data; hermes twin demo remove ends it
```

On a computer without the Grok app, plain `hermes twin` names the one next step there, the link:
`hermes twin link CODE` (see [SHARING.md](SHARING.md)).

To update later, run the install line from the README again with `--force` added (it looks up the newest
commit). Your twins, links and settings stay as they are.

Without `--enable` Hermes asks whether to switch the plugin on; over a remote shell it cannot ask and leaves it
off, and `hermes plugins enable grok-bot-twin` switches it on.

## One setup command

`hermes twin setup` sets up the computer it runs on, from wherever that computer stands. Its marks: `✓` done,
`→` this run will do it, `!` yours to do, `·` waits for an earlier step, `–` optional or not needed here.

```sh
hermes twin setup --check                        # where this computer stands and who does what is left; changes nothing
hermes twin setup --plan --bot "Acme Support"    # exactly what a run with these options would do; changes nothing
hermes twin setup --bot "Acme Support"           # does it; asks once first (--yes: do not ask)
hermes twin setup --all --share --yes            # every Grok bot gets a twin, and sharing is switched on
hermes twin setup --link 7KQ4-M2XD-P9RA --yes    # on a computer without the Grok app: link it
```

- `--check` ends with exit status 0 when nothing is left on this computer, and 1 when something is; every line
  that is left says who does it. `--json` gives the same answer to a program.
- A plain run verifies botport, as it always did. It asks once before anything more: before it uses a botport
  download it found in your Downloads folder, twins a bot, switches sharing on, or links this computer.
- Run it as often as you like. A bot that has a twin is left alone, sharing that is on makes no new code, and
  a computer that is linked stays linked.
- It counts your twins and never prints the name of a bot you did not type, and it never repeats a link code
  you typed. So the answer can be shown in a chat with an agent.
- `--check` and `--plan` read the plugin's own records and look whether files are there. They do not run
  botport and do not ask Grok for anything.

## Zero-touch setup, Telegram and twin safety

`hermes twin setup --auto` sets this computer up with no question and no manual step, and ends with one PASS or
FAIL line naming the step. It needs botport 0.3.0 or newer (the Grok engine), which this
plugin version pins; with an older release chosen in `botport_release_tag` it FAILs at once with "needs botport
0.3.0 or newer (the Grok engine); the botport_release_tag setting chooses 0.2.1". The steps: botport fetched (pinned release, SHA-256 checked) and verified; `hermes twin`
made to work from the profile your terminal is on (no `-p default`; the plugin is linked into that profile and
enabled there, and the PASS line says so; a twin's own profile is refused); the Grok app's PATH checked; botport's Grok engine
checked, its `fast` preset set only if no Grok policy was saved; Grok's Execution setting read before and after,
never written. `--open-port` also opens the Grok port now (restarts the Grok app); without it the port opens on
demand. `hermes twin setup --install-line` prints the pinned one-line install for this plugin version.

After an update, a twin's own gateway (its Telegram bot) still runs the old code until it restarts, and an
interrupted `gateway restart` can leave it stopped. So `setup --auto` restarts only the twin gateways that were
running, one at a time: it waits until each says it is running again, starts it once more when the restart left it
stopped, and the PASS line names any twin still offline and the command to start it. A gateway that was not running
is left alone. `--no-gateway-restart` leaves all of them as they are (they then keep the old code until you restart
them yourself).

When a new twin uses a model server that needs a key, the key is kept by reference: the twin's `config.yaml` says
`api_key: ${NAME}` and the value goes through your OS secret store into the twin's own private `.env`, taken from
your model setup or the source profile. The PASS line names the key and where it came from, never its value. With no
OS secret store the line says the key was not kept, and why; give the twin its key yourself then.

When Hermes runs with no screen (started over ssh on a Mac, or no display on Linux), a twin's profile gets a headless
browser (`browser.headed` off), so its screenshots do not time out; the PASS line says so.

`hermes twin telegram on TWIN...` (or `--all`) lets you reach twins through the Telegram bot one of your Hermes
profiles already has: no BotFather, no new token. In that bot's chat: `/twin to TWIN TEXT`, or `/twin use TWIN`
and then `/twin say TEXT` (`/twin use off` to stop). Only direct messages from your own numeric Telegram id (the
one the profile already allows; `--owner ID` when it allows several) are answered; groups and other people are
refused. A step in the twin's turn that needs approval is asked in your DM ("Approve once" / "Deny", the step
redacted like every reply), the same as on a twin's own bot; no answer counts as deny. The token is never read, copied or written: the plugin
only checks that the profile has one. `telegram on` links this plugin into that profile and enables it there
(`hermes -p PROFILE plugins enable grok-bot-twin`) when it does not have it yet, and the PASS line says so; only
that profile's bot answers `/twin to|use|say`. `--via PROFILE` picks the profile; `telegram off`, `telegram status`.
Stopping a twin takes it off the route.
With no Telegram bot in any profile it FAILs and names the one human step (@BotFather).

### A Telegram bot per twin (experimental)

Not usable yet: keep it off. Turning `telegram_bot_per_twin` on prints an `EXPERIMENTAL ... not usable yet` line first, because nothing receives Telegram's answer after your tap. Then a new twin, or `hermes twin telegram bot TWIN`, makes
your Hermes Telegram bot send you one "Create NAME" button in your DM. You tap it and confirm in Telegram; Telegram
makes a bot with the twin's name that belongs to you. The token is meant to go straight into the OS secret store and
reach the twin's profile only by reference (`secrets.command`, which runs `hermes twin telegram token TWIN` for Hermes
alone; you never run that yourself). The twin's bot answers only you, only in a direct chat, with strict tools and
manual approvals. `hermes twin stop` turns it off and forgets the token.

It FAILs, and says why, before asking anything when: Bot Management Mode is off for your Hermes bot, the computer runs
one gateway per profile (run `hermes gateway migrate` yourself first), the bot's profile allows more than one Telegram
user, there is no OS secret store, or the twin's safe defaults were not applied.

What still needs you: making your first Hermes Telegram bot with @BotFather; switching on Bot Management Mode for it
in BotFather's Mini App; one tap and confirm per twin bot (a button not tapped within 15 minutes expires; run the
command again); deleting a twin's bot in Telegram. Not finished in this release candidate: the code that takes
Telegram's answer after your tap (and stores the token) is tested only against a pretend Telegram, and nothing in
Hermes hands it that answer yet, so a real tap does not finish the twin's bot. Design and open questions:
[design/managed-bots.md](design/managed-bots.md).

`hermes twin safety [TWIN] [parity|strict|standard|open]` shows or sets a twin's tool preset. By default every twin
gets `parity` (twin#71): what its Grok bot can do (browser, web, X search, shell, files, code, image generation,
computer use) on every platform, Telegram included; approvals manual, so a risky action asks first in its chat
(Telegram's buttons or `/approve`); agent scheduling, delegation and terminal environment passthrough stay off.
The PASS line lists every capability and its state. Words like shell, ssh, servers, trading, brokers, wallets or
credentials in the bot's text are named, and you narrow with `strict` (knowledge, memory, session search and todo only; approvals manual; no MCP server except those named
in the `twin_safe_mcp` setting; the twin's own Telegram off) or `standard` (no terminal, code,
delegation, cron, browser or computer use, and by default no web, x_search, file or image_gen and no MCP server
except those in `twin_safe_mcp`; approvals manual). `--apply` applies the rule's choice; naming a preset is your
choice and is kept. `hermes twin setup --auto` moves twins the rule set to `standard` or `strict` before 0.5.1 to
`parity` once and says what it turned on; a preset you chose is left alone. Widen `standard` one toolset at a time: `hermes twin safety TWIN standard --allow web` (also
`x_search`, `file`, `image_gen`, `mcp` for all its MCP servers; repeatable). A twin whose model is not local FAILs
the check until you record `--model-policy any`. Every write keeps a dated copy of the config (the newest five).
Stopping a twin puts its config.yaml back as it was before the safe defaults when nothing changed it since;
otherwise the stop names the kept copy (`.twin-pre-safety.yaml`).

`hermes twin check-model [TWIN]` (with no TWIN under `hermes -p TWIN`, the twin whose profile it runs in) sends the twin one fixed message, "Reply with the model and endpoint you are
configured to use", once through a Hermes turn and, when the twin is on the Telegram route, once through that
route, and compares each reply with the model in the twin's config.yaml. PASS when every reply names that model;
a FAIL names the channel that was wrong or silent. The terminal line may show the full endpoint address; anything
meant for Telegram shows only the provider, the model and either a public hostname or "custom endpoint on your
network", never a private address, a local or tailnet name, or a port. Replies of twins on the Telegram route get
the same redaction.

## The sample tour

The sample has invented bots: Acme Support (skills greet-visitors and fun-fact, routines "Morning summary" and
"Water reminder", connection example-files) and Recipe Planner. It needs no Grok account, no botport and no
network, it never writes to your Hermes profiles and it stays out of your chats: the sample lives in the
plugin's own data folder.

```sh
hermes twin demo                 # the sample twin of "Acme Support", up to date
hermes twin demo grok-edit       # change the sample bot's description in Grok
hermes twin check                # the twin follows (the background check would do it within a minute)
hermes twin demo secret          # paste an obviously fake password into the sample bot's description
hermes twin check                # "1 thing that looks like a password or key was not copied"
hermes twin demo grok-edit       # changes the description again, so the fake password is gone at the next check
hermes twin demo conflict        # change the skill greet-visitors in both places
hermes twin check                # "1 item changed in both places"
hermes twin conflicts            # both versions, line by line (commands pick the only twin when there is one)
hermes twin resolve skill:greet-visitors --keep grok   # the old Hermes version is kept as an earlier version
hermes twin versions             # earlier versions, numbered: " 1. greet-visitors (skill) · …"
hermes twin restore 1            # puts number 1 back
hermes twin approve "skill:greet-visitors"   # then hermes twin send-to-grok: the sample's Grok side takes it at once
hermes twin add --bot "Recipe Planner"   # a second sample twin (shows the summary first, then asks)
hermes twin demo remove          # "Sample removed. Nothing of yours was changed."
```

In a chat, `/twin` shows the same status.

## Get botport in the terminal (for your real bots)

The Twins page does this with two buttons. In the terminal, download botport for your computer from its
[release page](https://github.com/hudsonwa/botport/releases/tag/v0.3.3) (plain `hermes twin setup` prints the
name of the file for your computer), then hand the download to the plugin:

```sh
hermes twin setup --file ~/Downloads/botport-aarch64-apple-darwin.tar.gz   # the file you downloaded
hermes twin doctor
```

Hermes keeps its own copy of botport and verifies it before it is ever run. A botport you already have on your
`PATH` (or in `~/.local/bin`) works too: just run `hermes twin setup`.

<details>
<summary>How botport is checked (for the careful)</summary>

`hermes twin setup` checks that botport and its folders are owned by you (or root) and not writable by
others, keeps a private copy and verifies that copy: its SHA-256 must be on the list of release files that
ships with this plugin version, so no other program and no network is needed. Only then does it run botport
once to check its features, and it records the SHA-256. Before every run the plugin checks the digest again
and refuses to run a changed program. Only `hermes twin setup --auto` downloads botport: the pinned release
file for this computer, from the fixed GitHub release address, checked against the SHA-256 table before anything
else touches it (see "Zero-touch setup" below). Otherwise the plugin never downloads or updates botport; it only
copies the file you chose. `hermes twin setup --with-github` verifies botport against the publisher's signed build record on
GitHub instead (this needs GitHub's command-line tool, [`gh`](https://cli.github.com/), signed in once with
`gh auth login`) and prints the exact check it runs (and, while botport is not on this computer yet, the `gh`
command that downloads the release); `hermes twin verify` runs that check again later. If a file is not on the list and `gh` is already installed,
the plugin tries that check by itself. For a botport you built yourself there is a loud opt-out,
`hermes twin setup --allow-unattested` (REST: `{"allow_unattested": true}`): it is recorded, and
`hermes twin doctor` and `hermes twin status` show "botport is in use WITHOUT being verified (local build)"
until you verify a released build. The `gh` and `hermes` commands the plugin runs are resolved to their real
paths and get the same owner/permission check; doctor shows both paths.

`hermes twin setup` verifies against one release (v0.3.3); to accept another release
set "botport release to accept" (`botport_release_tag`) or run `hermes twin setup --tag vX.Y.Z` (a release this
plugin version has no list for is verified with `--with-github`). The plugin also
refuses to run if any folder from the Hermes root down to its data folder is a symlink, owned by someone else
or writable by others. The model sees a twin only as an internal id (`t-` plus a keyed hash with a random
per-install secret), never by name unless you turn on "Let the model see names" (`share_names_with_model`).

</details>

Then:

```sh
hermes twin list-grok            # the bots in your Grok app (narrow the list with the "Bots to list" setting)
hermes twin add --bot "Acme Support"   # shows what copies and what you do yourself, then asks
hermes twin add --bot "Recipe Planner" --hermes-profile recipe-planner   # name the twin's Hermes profile yourself
hermes twin
```

## Commands

`hermes twin --help` lists them in the same groups. `TWIN` is a twin's name in quotes ("Acme Support") or its
short name (`acme-support`); with exactly one twin you can leave it out, except for `stop`, which always needs it. Most commands take `--json`.

**Everyday**

| Command | What it does |
|---|---|
| `hermes twin` / `status` | Your twins and the one next step. |
| `add --bot NAME` (or `--all`) | Give a Grok bot a twin; shows what copies, then asks. `--hermes-profile NAME` names its Hermes profile. |
| `quick NAME --model MODEL` | One twin start to finish (see [quick](#quick)). |
| `finish [TWIN ...] [--all] [--model MODEL]` | Give new twins a model and print what to ask each bot for. |
| `stop TWIN` (also `remove`) | Stop twinning one bot; its Hermes bot and chats stay. Keeps full transcripts and What syncs choices unless `--remove-data`; `--dry-run` shows what it would do. |

**Your other computers** (details in [SHARING.md](SHARING.md#in-the-terminal))

| Command | What it does |
|---|---|
| `share on\|off\|code\|status` | Share your twins with your other computers; `code` shows the link code. |
| `link CODE` | On another computer: link it to the one that shares. |
| `link-computer [--wait MIN]` | Share, print a link code, and wait until another computer has used it (PASS or FAIL). |
| `unlink` | Stop following; this computer's twins leave it (kept 30 days). |
| `fleet` | Which computers hold your twins, and how up to date each is. Also `fleet once\|run\|remove\|name\|memory\|skills\|settings\|routines` ([SHARING.md](SHARING.md#in-the-terminal)). |
| `routines [on\|off]` | Copy each twin's routines to your other computers (`move ROUTINE COMPUTER`, `run-here on\|off`, `restore`). |
| `background on\|off` | Keep this computer's twins up to date while Hermes is closed. |

**Ask another computer**: `ask COMPUTER "TEXT"`, `requests` (the log), `requests on|off`, `requests approve|deny ID`,
`requests mode [here|safe]` ([SHARING.md](SHARING.md#ask-a-twin-on-another-computer)).

**Only you, at your own terminal.** `requests on`, `to-grok TWIN allow`, `to-grok TWIN apply`,
`secret share NAME --to-grok|--linked` and `bot-driven TWIN` ask at the terminal itself (`/dev/tty`; `CONIN$` on
Windows) and go ahead only on a `yes` typed there. `--yes` does not skip that question, and a command with no
terminal (a chat, a bot's shell, a script, `setsid`) or one a chat started is refused: "Only you can do this,
typing yes in your own terminal; a command without one (a chat, a bot, a script) is refused." The Twins page asks
nothing more.

**Fix things**

| Command | What it does |
|---|---|
| `conflicts [TWIN]` / `resolve [TWIN] ITEM --keep hermes\|grok` | What changed in both places; keep one version. |
| `instructions [TWIN]` | Grok's instructions kept in step: `check`, `on\|off`, `keep grok\|hermes`, `downloads on\|off`, `request`. |
| `versions [TWIN]` / `restore [TWIN] NUMBER` | Earlier versions kept for undo; put one back. |
| `doctor` | Check the setup and say what to fix. Its last line checks every twin gateway (read-only): `PASS twin gateways: running with Telegram up: ...`, or `FAIL twin gateways: offline, Telegram silent: TWIN (why). Fix: hermes -p TWIN gateway restart`. |
| `status` | Your twins at a glance, plus one line for this week's Grok usage, read through the engine (0 turns): `Grok this week: 42% used (resets Mon); twin used 7 turns`. Past your weekly budget (`grok_turn_budget_week`) a warning follows. If reading it opened the Grok app's port, the port is closed again afterwards; a reading is kept 15 minutes. Without the engine the line is left out and a note says why. |
| `setup` | Set up this computer or finish what is left ([below](#one-setup-command)). |

**One prompt in Grok** ([ONE-PROMPT.md](ONE-PROMPT.md))

| Command | What it does |
|---|---|
| `skill-text` | Print the skill to give a Grok bot once. |
| `from-grok --bot NAME` / `back-to-grok --bot NAME` | Run by the Grok bot itself, with its state as JSON on stdin. You do not run these by hand. |
| `from-hermes BOT` / `--all` | (A bot whose name, description, routines and last activity read the same as at its last PASS, with its twin still there, is skipped: 0 Grok turns, and the line says so; `--force` exports it anyway.) From Hermes, through botport's Grok engine: the bot exports its instructions, memory and skills with its own tools (no local command, no approval), Hermes checks the export as untrusted data and imports it; history and routines are read by the engine. `--file` asks for the file route, `--shared-skills` also imports skills other bots made, `--route shell` the old route (the bot runs from-grok here; `--wait` for a run left waiting); `--timeout S`; `--json`. Needs botport 0.3.0 or newer (`botport grok`; this version pins 0.3.3) ([ONE-PROMPT.md](ONE-PROMPT.md#from-hermes-and-chat-sync)). |
| `chat-sync` | Chat sync: `--status` (mode, interval, each twin's last run), `--pull [TWIN\|--all]` (read new messages through the engine now). `--bot NAME` is what the bot's routine runs, with its new messages as JSON on stdin. |
| `git on\|off\|status [TWIN\|--all]` | Optional git history of a twin (`--remote URL` to push, `--with-history`). |
| `bot-driven [TWIN]` | Your own step, once, for a twin made on the Twins page before its first one prompt ([below](#bot-driven)); `--dry-run` shows what changes. |
| `mcp --bot NAME` | The same two calls as a local MCP server, for a later Grok app; not used today. |

**Advanced**

| Command | What it does |
|---|---|
| `check [TWIN]` (also `sync`) | Check Grok now. `sync TWIN --from-file FILE` or `--stdin` brings a bot and its twin level both ways from the bot's own state. |
| `list-grok` | The bots in your Grok app. |
| `recent [TWIN]` | Recent activity (when and what kind; never content). |
| `compare [TWIN]` | Compare with Grok, item by item. |
| `test [TWIN]` | botport's behaviour test (see [test](#test)). |
| `copies` | What copies over and how: the whole table. |
| `checklist [TWIN]` | What you do yourself, and what moving routines to Hermes takes. |
| `syncs [TWIN]` | What syncs with Grok, which way, and when it last did. |
| `secret list\|set\|forget\|share\|pull [NAME]` | Keys kept by reference in this computer's OS store ([SECRETS.md](SECRETS.md)). |
| `import [TWIN] FILE` | Import a bot's setup export. Asks first (`--yes` skips); `--show` prints it whole; `--request` prints what to ask the bot; `--bot NAME` picks one bot of a file with several. |
| `import-exports DIR` | Import every setup export in a folder, each into its bot's twin, after one question (`--yes`, `--show`, `--twin NAME`). |
| `switch [TWIN]` (also `move`) | Move routines to Hermes: turn the copied routines on; `--undo` pauses them again. |
| `approve [TWIN] ITEM` / `skip [TWIN] ITEM` | Let one waiting change go ahead; keep a changed skill in Hermes only (`--undo`). |
| `send-to-grok [TWIN]` | Send approved skill changes to Grok (needs skill sync). |
| `skill-sync [TWIN]` | Skill sync: `--folder DIR` on, `--off`, `--status`, `--new-pass`, `--again`. |
| `digest [TWIN]` | The optional activity digest to Grok: preview, `--on`, `--off`. |
| `transcripts ACTION [TWIN]` | Whole conversations, encrypted and searchable (off by default): `on`, `off`, `add-grok`, `refresh`, `search`, `export`, `to-hermes`, `forget`. |
| `to-grok [TWIN]` | Changes made in Hermes, made in Grok by the sync bot: preview, `allow`, `disallow`, `apply`, `undo`, `resolve`, `runner`, `give-up` (each is in its `--help`). |
| `verify` | Check botport against GitHub's signed build record. |
| `demo [ACTION]` | A sample twin with invented data (`demo remove` ends it). |
| `uninstall` | Remove Grok Bot Twin: every twin and its records; Hermes bots and chats stay. |

Reading only, safe to run any time: `status`, `recent`, `compare`, `copies`, `checklist`, `syncs`, `fleet`.

Every flag of a command is in its `--help` (for example `quick --endpoint`, `finish --endpoint`, `requests
--step`, `demo start|hermes-edit`).

Older names that still work: `restore-points` (versions), `parity` (compare), `mirror` (skill-sync), `attest`
(verify). Removed in 0.3.6: `facts`, `briefs` and `transcripts to-grok-on|to-grok-off`.

Each twin's Hermes bot is its own Hermes profile. The option is `--hermes-profile`, because `hermes` itself
reads `--profile`/`-p` anywhere on the command line. `import`, `import-exports` and `quick` refuse when started
from the chat turn of a request another computer sent.

### quick

`hermes twin quick "Acme Support" --model MODEL --yes` does one twin start to finish: `add`, prints the request to
paste into the bot's chat in Grok, waits for the answer file in Downloads (`--wait MIN`, 15 by default, at most
120; files saved up to an hour before count), then `import-exports`, `finish` and `compare`. The last line is
`PASS: ...` or `FAIL: ...`. Each step asks as usual unless `--yes`. Run it again after a timeout: what is done is
skipped. `--from-file FILE` or `--stdin` takes the setup export directly, with no paste and no wait.
`quick --all --model MODEL --yes` does every Grok bot in turn. No model is called.

### test

`hermes twin test "Acme Support" --from-export FILE` (or `--battery FILE`) runs botport's behaviour test on the
twin: botport asks the twin each case and checks the answer, so each run costs what those chats cost.
`--from-export` makes the cases from a setup export once and keeps them; `--battery` uses your own. It prints
passed of total and one line per case, exits 1 when a case fails, and `hermes twin status` then shows
"test 5/6 ✗". Every one-prompt run also runs it. A model answer or reason that looks like a password or key is left
out of the report (the verdict stays), the same rule as botport 0.3.3.

In a from-hermes or one-prompt import, every failed case is asked once more and fails only when it fails twice. The
line names each failed case with a short fixed reason (`failed twice: memory-2 (no tool call)`), never the bot's
text. When only model-behaviour cases (memory, live tool calls) still fail, the import is kept and the twin marked
"test failing", since a different or better model may pass; set `import_test_failing: rollback` to put everything
back instead. A failing data case (persona, instructions, skills, gateway) always rolls back.

### bot-driven

`hermes twin bot-driven "Acme Support"` is your own step for the one-prompt route ([ONE-PROMPT.md](ONE-PROMPT.md)):
a twin that follows its Grok bot through botport is never switched by the bot's prompt (`from-grok` FAILs on it,
nothing written, and names this command). It copies botport's parts of the twin's Hermes folder to
`plugin-data/grok-bot-twin/one-prompt/converted/` and runs `botport twin remove` (the Hermes bot, its chats and
everything in it stay); from then on the bot keeps the twin in step with each prompt, and the twin no longer follows
renames and edits made in Grok between prompts. `--dry-run` shows that and changes nothing; otherwise it asks at
your own terminal and goes ahead only on a `yes` typed there; a twin already bot-driven is left as it is.

Slash command: `/twin [status | check [TWIN] | conflicts [TWIN] | recent [TWIN] | ask COMPUTER: TEXT | requests | demo ...]`.
Anything but status and recent works only in a chat that Hermes names as one of its own local surfaces (its
terminal, terminal UI or Desktop); a messaging app, or a caller that names no surface, gets status only.
Agent tools (what a Hermes chat model can call):

| Tool | What it does |
|---|---|
| `twin_status` | Plain-language state: last check, what to do yourself in Grok and in Hermes, changes waiting, items changed in both places, skill sync, the two things never copied from Grok. Reads only. |
| `twin_recent` | Recent activity (when and what kind). Reads only. |
| `twin_transcripts_search` | Searches a twin's whole conversations, when you switched those on for it. Reads only. |
| `twin_make` | Makes or syncs the twin of **one** Grok bot you named ("twin my Acme Support bot"): the steps of `quick` without asking (add, model, compare), then the behaviour test when the twin has cases, which calls the twin's model. Never deletes, never waits for a setup export, refused for requests from another computer. |

`twin_status` and `twin_recent` say "your Grok twin" and an internal id unless "Let the model see names" is on,
and say so when the twin is the sample. No tool asks
another computer: only you do (see [Ask a twin on another computer](SHARING.md#ask-a-twin-on-another-computer)).
