# Changelog

## Unreleased

### Fixed
- twin#75: `tools/stamp_build.py` (and two plugin writes) no longer use `write_text(newline=)`, which is Python
  3.10+; the macOS system Python 3.9 runs it. `hermes -p TWIN twin check-model` checks the twin whose profile it
  runs in instead of asking which twin. `hermes twin setup --auto` restarts the twin gateways that were running
  through one helper (twin/gateways.py) that waits for each, starts it again when a restart left it stopped, and
  names any twin still offline in the PASS line; `--no-gateway-restart` leaves them as they are.

## 0.5.1 (17 November 2026)

Grok Bot Twin 0.5.1 ↔ botport 0.3.3 (pins unchanged).

**What this means for you:** each twin now knows where it came from and can check itself. Its `SOUL.md` gets a short
note saying which Grok Bot Twin and botport versions made it, kept up to date when the plugin updates (`origin_note: off`
removes it). Every twin also gets four read-only plugin skills, and `hermes twin check-model` confirms the twin answers
with the model you configured. A second twin of the same name is now "Acme Support 2" everywhere.

### Added

Fixes #64, fixes #65, fixes #66, fixes #69.

- Origin note: a version-stamped, fixed-wording `origin` block in each owned twin's `SOUL.md`, rewritten once when the
  plugin or botport version changes, plus one fixed line in the per-turn awareness note (#64). Owner text outside the
  markers stays byte for byte; the block is never sent to Grok.
- Skill pack `skills/twin-pack/` (`twin-about-me`, `twin-health`, `twin-update`, `twin-new-computer`), installed into
  every owned twin and refreshed with the origin note. It is never synced, sent to Grok, copied to linked computers or
  counted as the bot's own skills; `hermes twin doctor --repair-pack` puts back a deleted pack skill (#65).
- `hermes twin check-model [TWIN] [--json]`: asks the twin which model and endpoint it uses, through a Hermes turn and
  the Telegram route, and compares the answer with the profile's `config.yaml` (#66).
- Telegram-bound text never shows a private IP, a `.local`/`.lan`/`.internal`/tailnet name, a bare hostname or a port;
  an endpoint shows as its public hostname or "custom endpoint on your network" (#66).
- A second instance of a twin gets the same number in its profile id, display name and suggested Telegram username
  ("Acme Support 2", `acme-support-2`, `acme_support_2_twin_bot`); the sharing computer picks the lowest free number
  across the fleet (#69).

### Fixed

Fixes #71, fixes #72, fixes #73.

- A twin can do what its Grok bot can do (#71). The default preset is now `parity`: browser, web and X search,
  shell, files, code, image generation and computer use stay on, in the desktop app and Telegram alike. Risky
  actions still ask first in the chat they came from (Telegram's buttons or `/approve`), and the hard floors hold
  (manual approvals, deny when nobody is there, no agent scheduling or delegation, no terminal environment
  passthrough). The create and import PASS lines and `hermes twin safety` list every capability and its state;
  `strict` and `standard` are your opt-in. `hermes twin setup --auto` moves twins the rule set to `standard` or
  `strict` earlier to `parity` once and says what it turned on; a preset you chose is kept.
- A failed `hermes twin from-hermes` no longer leaves the Grok app running with its debug port open (#72):
  `botport grok restore` runs on every exit (PASS, FAIL, rollback, timeout, an error, Ctrl-C), a FAIL line says the
  port was closed, and a restore that failed is said first.
- `hermes twin doctor` reads the `revision` key of Hermes' install record for the build-stamp check (#73).
- The safety rule no longer reads the plugin's own skill pack as the bot's text (its `twin-update` skill names
  "terminal", which marked every twin risky).

## 0.5.0 (16 November 2026)

Grok Bot Twin 0.5.0 ↔ botport 0.3.3.

**What this means for you:** with botport's Grok engine (`botport grok`, in botport 0.3.3), you
can twin a Grok bot from Hermes without opening Grok: `hermes twin from-hermes "Acme Support"`, or "twin all my
Grok bots" in a Hermes chat on this computer. The bot exports itself with its own tools (no local command, no
approval) and Hermes imports and checks it; its Hermes chats then keep up by themselves. **This version pins
botport 0.3.3** (`twin/botport_pins.json`). Only an older release chosen with `botport_release_tag` makes `hermes
twin setup --auto` and `from-hermes` FAIL with "needs botport 0.3.0 or newer (the Grok engine); the
botport_release_tag setting chooses 0.2.1". Saying the prompt in Grok works as before.

### Fixed (audit 16 November, before release)

Fixes #55, fixes #56, fixes #57, fixes #58, fixes #59, fixes #60, fixes #61, fixes #62, fixes #63.

- Secret check: a link or folder path of plain lowercase parts is judged part by part, so a path is no longer taken
  for a key (#55); a refusal names the kind and the line.
- `setup --auto` leaves a non-default sticky profile alone unless `--link-profile` is given (#56).
- Grok's Execution setting is never reported as "unknown": it says "not read, port closed" (#57).
- `doctor` and `setup --check` read a build stamp in the plugin and name a mismatch with Hermes' install record (#58).
- `from-hermes`: a bot that made none of the account's skills says so; skipped entries are named with a reason (#59).
- `create` names an old botport mirror profile, with park or adopt, and never picks it silently (#60).
- Behaviour test: one at a time per model endpoint and profile, a per-case budget from the model's first answer,
  memory cases retried once, wall time on a FAIL (#61).
- `stop`: the safe-defaults fingerprint follows create's model step, never a change to a key the owner set (#62).
- `setup --with-github`: gh reads the owner's own sign-in (GH_CONFIG_DIR from the real home) (#63).
- Pins botport 0.3.3: [`grok restore` PASSes only with no debug-flagged Grok process, no DevToolsActivePort and no
  listener](https://github.com/hudsonwa/botport/issues/63), and [a credential-looking model answer no longer blocks
  the behaviour test's results file](https://github.com/hudsonwa/botport/issues/66)
  ([release](https://github.com/hudsonwa/botport/releases/tag/v0.3.3)).

### Added

- **`hermes twin from-hermes BOT` (and `--all`, `--bot`, `--only`), and the Hermes tool `twin_from_hermes`
  (zero-touch 04).** The default route (`from_hermes_route: export`) asks the bot, through the engine, for a
  `grok-bot-export/1` built only with its own cloud tools (instructions, memory, skills); a large one comes back
  as a file the bot sends, saved with `botport grok files fetch` (the bot is asked to delete it afterwards, also
  when the file was refused). History and routines are read by the engine (`botport grok read`, `botport grok
  routines`), never taken from the bot's words. The export goes through the one prompt's importer and proof, and
  the PASS line is checked again (one-prompt log, Grok's Execution setting unchanged, no approval card in the
  export turn). `--route shell` keeps the old route, where the bot runs `hermes twin from-grok` here (with
  `--wait` for a run left waiting on an approval in Grok). In a chat, `all: true` gives counts, not bot names,
  unless `share_names_with_model` is on, and skills other bots made are counted, not named. The tool and
  `twin_make` refuse a messaging chat (Telegram and the like) unless `setup_from_messaging` is on.
- **Bot exports are untrusted (zero-touch 05).** A strict schema (unknown fields, wrong types, size caps: FAIL), the
  bot's name must be the engine's, plain skill names only (no paths, newlines, escape codes), one JSON block and no
  PASS/FAIL-looking line in the reply, no text that looks like a password or key and none that drives this
  plugin's or botport's commands. Any of these is a FAIL with nothing written; the raw export is never kept.
- **Each twin gets the skills its bot made (zero-touch 06).** Grok's skills look account-wide, so a bot lists
  them all and marks its own. Only its own are imported. With `--all`, a skill that several bots mark as their own
  goes into each of those twins and is named. Skills it did not mark are named and not imported (`--shared-skills`
  imports them). Another bot's skill that fails the checks, or shares a name with one of the bot's own, is skipped
  and named; it never fails the export.
- **`hermes twin setup --auto` (zero-touch).** No question, no manual step, one PASS/FAIL line: downloads the
  pinned botport release itself (SHA-256 checked against the plugin's table first), makes `hermes twin` work from
  the terminal's sticky profile (links and enables the plugin there and says so; a twin's own profile and another
  copy of the plugin are refused), checks the Grok app's PATH, the engine and the port under the `fast` preset (set
  only when no Grok policy was saved in `~/.botport`), and FAILs if Grok's Execution setting changed.
  `--open-port`, `--install-line` (the pinned one-line install). `from-hermes` runs it once by itself when the
  engine is missing. Needs botport 0.3.0 or newer (pinned): with an older release chosen it FAILs at once and names that.
  `tools/pin_botport.py --tag vX.Y.Z` now pins a release in one step (download, attestation check, pin table and
  pinned tag).
- **Continuous chat sync (`chat_sync_mode`: `pull`, `routine` or `off`; `chat_sync_minutes`, default 360).**
  - `pull` (the default): this computer reads the bot's chat through the engine (`botport grok read`) on the
    plugin's background check, every 6 h by default, from where it left off. No Grok usage. Each due pull opens an
    idle-only port window (twin#52), `botport grok launch --for 10m --when-idle 10`: an open port is reused with no
    restart, the app restarts only when the Mac has been idle (`chat_sync_idle_minutes`), and "the Mac is in use"
    (exit 2) skips the pull and retries in 30 min. A window it opened is closed with `botport grok restore`.
    `chat_sync_window: port` pulls only when the port is already open. A failed pull also waits a full interval;
    a stopped twin leaves chat sync at once; and a pull never runs while a from-hermes run uses the port (one
    shared lock).
  - `routine` (opt-in, `--route shell` only): the bot makes a Grok routine, "Sync chats to Hermes", that sends its
    recent messages through `hermes twin chat-sync --bot NAME`. Offered only when Grok's Execution on Local
    Computer setting reads Always allow (read, never changed): a live test showed that under Ask every time an
    unattended routine never runs the command.
  - `hermes twin chat-sync --status` shows the mode and each twin's last run; `--pull [TWIN|--all]` pulls now.
- **`hermes twin telegram on|off|status`: twins through your existing Hermes Telegram bot.** No BotFather step, no
  new token (the token is referenced, never read or copied). `/twin to TWIN TEXT`, `/twin use TWIN` + `/twin say
  TEXT`; owner's numeric id only, DM only, and only on the gateway profile the route was turned on for; approvals
  in the twin's turn answered "deny". `telegram on` links and enables the plugin in the gateway profile when needed
  and says so. A stopped twin leaves the route.
- **`hermes twin safety`: safe twin-profile defaults by rule.** `strict` for bots that mention shell, ssh,
  servers, trading and similar; `standard` otherwise, which by default also turns off web, x_search, file and
  image_gen and every MCP server not in `twin_safe_mcp` (widen with `hermes twin safety TWIN standard --allow web`,
  and `x_search`, `file`, `image_gen`, `mcp`); `open` only by the owner. A non-local model FAILs the check until a
  model policy is recorded. Applied automatically (twin#54) whenever a twin's profile is made (`add`, the one
  prompt, `from-hermes`) and again on what an import wrote, before the behaviour test or anything else runs there;
  the owner's own choice is kept. If `add` cannot apply them, its line is a FAIL and the twin's routines and
  Telegram route stay off until `hermes twin safety TWIN --apply` passes. Stopping a twin (also keeping its
  Hermes bot) puts config.yaml back as it was when nothing changed it since, otherwise names the kept
  `.twin-pre-safety.yaml`; only the newest five dated copies are kept.
- **A fallback when the engine cannot be used.** botport missing, without the Grok engine, not verified, or the
  Grok app's local port closed: a FAIL that names the ways that work, saying the prompt in Grok or running
  `botport grok launch` (the fast preset).
- The behaviour test's PASS line says when a live case passed only on its one retry.

### Changed

- **No duplicate messages when the same chat is sent more than once.** A conversation's own `id`, when the bot or
  the engine has one, is now its key. A message is also skipped when the same role, second and text are already
  stored for that twin under any conversation, so a changed title or time format cannot add it twice. The check
  uses an HMAC with the archive's key; the text is never stored in the clear. An archive made before this change
  is checked the same way the first time.
- twin talks to the engine through one adapter (`twin/grok_engine.py`), aligned with botport's frozen engine
  interface (end of P1). The engine is found by asking `botport grok status`; the routine is confirmed by the bot's
  own word until the engine can list routines. Grok's local-command setting is read from the engine's `status`
  (`local_tool_permission`). An app version botport has not tested is a FAIL that names `botport grok canary`.
- The Grok skill (`hermes twin skill-text`) has a "Chat sync" part: the routine and the one chat-sync command it
  may run, and only when the request asks for it. Give the bot the new skill text to use `from-hermes` with sync.

### Fixed

- `hermes twin setup --auto` on a computer that still has the botport of an earlier plugin version (0.2.1) takes
  the pinned release once and verifies it, instead of FAILing with "not the release Hermes expects".

## 0.4.1 (16 November 2026)

**What this means for you:** `hermes twin skill-text` prints the Grok skill (no more copying from GitHub),
the docs are rewritten to take you to a first twin, and the Twins page says "sync bot" where it said "the
Mirror". If Grok refuses the one-prompt command as too long, the bot tries once more without conversations.
A bot you already twinned on the Twins page now needs your own `hermes twin bot-driven` step before its first
one prompt, the owner-only switches want a `yes` typed in your own terminal, and coming back to Grok hands the bot
memory and skills only if you allowed Hermes → Grok for that twin.

### Changed

- **Coming back to Grok hands over memory and skills only under Hermes → Grok.** `hermes twin back-to-grok` used to
  give the Grok bot Hermes-side memory and skills to write into itself (UpdateMemory, UpdateSkill, which can replace
  a skill) whatever the twin's Hermes → Grok switch said. Now `bundle.memory` and `bundle.skills` are empty unless
  you allowed Hermes → Grok for that twin (`hermes twin to-grok TWIN allow`), and the PASS line says how many stay
  in Hermes. `routines_to_enable` is unchanged: only the bot's own routines it paused when it moved. The bot's
  skill (`grok/SKILL-twin.md`) shows you the facts and skill names and waits for your yes before writing them.
- **The owner-only switches ask at your own terminal.** `hermes twin to-grok TWIN allow`, `to-grok TWIN apply`,
  `secret share NAME --to-grok`, `secret share NAME --linked` and `requests on` used to check only that no chat's
  variables were set, so a model that removed them (`env -u ...`), or a Grok bot's own shell, got through. Each
  now asks at the controlling terminal itself (`/dev/tty`, `CONIN$` on Windows) and goes ahead only on a `yes`
  typed there; a command with no terminal is refused ("Only you can do this, typing yes in your own terminal; a
  command without one (a chat, a bot, a script) is refused."), and `--yes` no longer skips the question. One guard
  (`tasks.owner_confirms`) does it for all of them. The Twins page is unchanged.
- **One-prompt never converts an existing twin by itself.** `hermes twin from-grok` and `back-to-grok` no longer
  switch an existing twin from botport's twin pairing to being kept in step by the bot (`botport twin remove`) on
  their own: they FAIL on such a twin before anything is written and name the owner's step,
  `hermes twin bot-driven TWIN` (new; `--dry-run` shows it; the yes is typed at your own terminal, like the other
  owner-only switches, and `--yes` does not skip it). A twin `from-grok` makes is bot-driven from the start, as before.

### Docs and smaller fixes

- Docs: a shorter README that leads to a first twin, with a "You need" list and a choice between the one
  prompt and the Twins page; docs/ONE-PROMPT.md rewritten for users (setup, what the bot sends, an "If it says
  FAIL" table, what Always allow means); command tables in docs/TERMINAL.md; a glossary and troubleshooting
  table in docs/GUIDE.md; a user summary at the top of docs/SECRETS.md and docs/DISCLOSURE.md.
- `hermes twin skill-text` prints the Grok skill for the one-prompt flow, so it can be copied without a checkout;
  `--name`, `--description` and `--body` print one field each, for the Grok app's Add new skill.
- The docs give the Grok app's real menu paths (Settings → Bot → Execution on Local Computer; the bot's Skills
  tab → Add new skill), a PowerShell install line, and `--force` for updating over the catalog version. The two
  design documents moved to docs/design/.
- "sync bot" in the `to-grok` help and the docs (they said "Mirror bot"; the text the bot itself reads in Grok
  keeps botport's name for it). `hermes twin stop --help` says the name is always needed.
- The one-prompt conflict FAIL now says what to do (make the two the same, then try again); it pointed at
  `hermes twin sync`, which cannot settle it without the bot's state.
- Git history: a remote added after the first commits gets them at the next PASS, and a failed push is tried
  again at each PASS; `--all` with `--remote` is refused (one repository per twin).
- The one-prompt PASS line says "matches what the bot sent" (was "drift clean") and counts the conversations.
- The `twin_make` agent tool (one named bot, from a Hermes chat) is now listed in docs/TERMINAL.md.
- `hermes twin setup --check` no longer reports a twin as finished before the status cache has seen it; a setup
  run that makes twins saves the status.
- A memory fact that went Hermes → Grok and came back (the bot tags it "(from Hermes)") is no longer added to
  the twin's memory a second time; the owner-only question of `to-grok TWIN allow` says "sync bot" (found in the
  0.4.1 live test).
- The two example SSH git addresses in the code and tests carry `privacy:allow`, so the release privacy gate
  no longer flags them.

## 0.4.0 (15 November 2026)

**What this means for you:** one prompt in a Grok bot ("Clone yourself to Hermes") now makes a tested
twin with its instructions, skills, memory and routines, and can move the bot to Hermes and back
(docs/ONE-PROMPT.md). `hermes twin stop` now needs the twin's name.

### Breaking

- `hermes twin stop` now needs the twin named (`hermes twin stop "Acme Support"`), ends with `PASS:`/`FAIL:`, and
  keeps the twin's full transcripts and What syncs choices unless `--remove-data`. The Twins page's Stop twinning
  is unchanged (it deletes them, as before).

### Added

- One prompt in a Grok bot makes a tested Hermes twin, and moves it to Hermes and back:
  `hermes twin from-grok --bot NAME` and `hermes twin back-to-grok --bot NAME` (the bot's state as JSON on stdin),
  run by the bot through the Grok app's "Run a command on your local computer": one command, one approval click
  per prompt (none with Always allow, the owner's choice), and a Grok skill text (`grok/SKILL-twin.md`). See
  docs/ONE-PROMPT.md. `hermes twin mcp --bot NAME` serves the same two calls as a local MCP server; it is not the
  route today, because Grok Bot 1.0.1 runs custom Command connectors on the bot's cloud computer.
- The one prompt also carries the bot's memory into Hermes' own memory file, where the twin's `memory` tool reads
  it (botport keeps memory only as a skill the model rarely opens). A new twin gets the owner's model server
  (botport `twin create` copies the model's name, not its `base_url`). `hermes twin stop` works on a bot-driven
  twin. The written-file secret check looks only at files this call changed (Hermes' own bundled skills hold
  example keys). botport is told the Hermes folder in its environment too (`botport test` needs it).
- A twin becomes **bot-driven** the first time the one prompt (or `hermes twin sync --stdin`) is used on it, once: a copy of their
  botport parts is kept, then `botport twin remove` (the Hermes profile and its chats stay). Status shows them as
  "Kept in step by the bot · last synced …, PASS". Not yet: a bot-driven twin does not follow a rename or a new
  description in Grok between prompts (follow-up: apply them from the Grok bot list, read-only).
- **Secrets by reference.** A key the plugin's secret check finds in a bot's text is no longer just blanked: when this
  computer has an OS secret store (macOS Keychain, Linux Secret Service, Windows Credential Manager) the value is kept
  there under a NAME (service `grok-bot-twin`) and the text keeps a placeholder: `{{secret:NAME}}` towards Grok,
  `${NAME}` towards Hermes. The twin's Hermes bot gets the value the way Hermes keeps its own keys, as a line of the
  profile's own `.env` (0600), written only when the call PASSes. Done on `hermes twin sync`, `from-grok` and
  `back-to-grok`; the answer names the keys kept, never a value. `hermes twin secret list|set|forget|share`
  (`share NAME --to-grok` is the one way a value reaches the Grok bot, asked in your own terminal; `--linked` lets
  your other computers fetch it over `POST /v1/xs/secrets`, sealed like a twin's memory, off by default). No OS
  store: nothing is kept and the value is blanked as before; there is no file fallback. See docs/SECRETS.md.
- Optional git history per twin, off by default (no git needed unless it is on): `hermes twin git on "NAME"`
  (or `--all`) `[--remote URL] [--with-history]`, `hermes twin git off`, `hermes twin git status`. After every
  PASS of the one-prompt tools (twin, sync, move, back) the bot's instructions, skills, memory and routines are
  written as Markdown/JSON to `<plugin-data>/git/<twin>/` and committed ("PASS sync from Grok: 2 skills
  changed"); with a remote (a Forgejo URL, say) it pushes, and a failed push is a warning on the PASS line, never
  a FAIL. Secret-scrubbed first; keys, tokens and `.env`/auth files are never read; chat history only with
  `--with-history`. Snapshots stay at 3. See docs/ONE-PROMPT.md.
- The optional git history refuses a remote address that carries a password or token (it would have been kept in
  plain text); sign in with git's credential helper or an SSH key.
- `hermes twin quick "Acme Support" --model MODEL --yes`: one twin start to finish in one command. It runs `add`,
  prints the request to paste into the bot's chat in Grok, waits (15 minutes by default, `--wait MIN`) for the
  answer file in Downloads, then runs `import-exports`, `finish` and `compare`, and ends with one PASS/FAIL
  summary. Each step asks as it always does unless `--yes`. Run it again at any time: a step that is done is
  skipped. No model is called. `--from-file FILE` or `--stdin` takes the bot's setup export directly (no paste,
  no wait), so an agent can run it in one non-interactive command. The last line is always `PASS: ...` or
  `FAIL: ...`.
- `hermes twin quick --all --model MODEL --yes`: `quick` for every Grok bot in turn (never the sample's), one
  line per bot and one verdict, `PASS: quick setup of 2 of 2 bots` or `FAIL: ...`.
- `hermes twin test "Acme Support" --from-export FILE` (or `--battery FILE`): botport's behaviour test (`botport test`) of a
  twin, through the same verified botport copy and minimal environment. Each case is a real chat with the twin's
  model. `--from-export` makes the cases once (`botport battery init`) and keeps them for the next run. The last
  result (passed of total, the ids of the failed cases) shows on the twin's line in `hermes twin status`.
- `hermes twin link-computer [--wait MIN]`: one command to link one more computer. It turns sharing on, prints a
  link code and the line to run on the other computer, then waits (10 minutes at most, as long as the code lasts)
  until a computer has used it: `PASS: another computer is linked` or `FAIL: ...`.
- The same three are library functions (`twin/bulk.py`: `quick_all`, `link_computer`, `stop_twin`) for a Hermes
  model tool; `stop_twin` is a dry run unless confirmed and has no remove-data choice. No tool is registered.

### Changed

- botport errors no longer hide the plugin's own file names as `[secret]`: the command is named by its words
  only, and the plugin's folders are said in words.

### Design note: bot-driven twins (15 November 2026)
botport v0.2.1 refuses `apply`, `sync` and `drift --bundle` on any profile its twin pairing owns (the
`botport.mirror.json` file `twin create` writes), and has no call that applies a bot's own export to such a
profile: `twin sync --from-export` ignores the export, `twin adopt` skips a paired bot, and after a remove a
changed skill becomes a conflict. Memory is never part of botport's twin sync. So a twin the bot keeps in step
itself is converted once with `botport twin remove` (profile kept) and then goes through the spec path, as the
two-way sync already did. Considered and rejected: remove, adopt and resolve on every call (fragile, and it loses
the restore points each time). Long-term option: an "apply this export" call in botport for a paired profile, after
which no twin needs converting.

## 0.3.6 (15 November 2026)

Smaller again: two features that could never run are gone, and a few fixes from the review.

- A routine runs in one place: Hermes to Grok's runner and routines between computers now check each other first.
- `status()` answers from a fresh snapshot instead of waiting for a rebuild.
- Grok's export is not applied by itself when it only differs in whitespace or is much shorter than before.
- A coding agent no longer prints the owner's bot names or instructions into its chat.
- Stopping a twin deletes the files the removed session briefs and memory facts kept for it (its briefs, their
  bookkeeping, the memory-facts ledger, restore points and Grok stand-in). MEMORY.md and USER.md stay.

### Removed (no replacement)
Memory facts with Grok and session briefs needed a Grok side that does not exist, so they never synced anything.
These are gone; scripts that call them get an "unknown command" error or a 404:
- `hermes twin facts` and `hermes twin briefs`;
- the dashboard routes `GET/POST /briefs`, `POST /briefs/now` and `POST /briefs/forget`;
- `hermes twin transcripts to-grok-on` and `to-grok-off` (the archive stays on this computer; a saved "send to
  Grok" choice from 0.3.5 now reads as off).

## 0.3.5 (12 November 2026)

The fixes from the cycle-3 review: a possible hang, two ways a choice or a routine could slip through, and a much
shorter README and plugin description.

- Fixed a possible hang: the status read and a Hermes to Grok change could each wait for the lock the other held.
  Hermes to Grok now reads the Grok side from the last status, and the one lock order is checked in code.
- Reading the status no longer writes any file. The background round saves what the read learnt, and a status
  never shows "up to date" while a choice is still being worked out.
- An instructions or Hermes to Grok conflict is now the one "changed in both places" box on the Twins page, with
  buttons that settle it. Before, the row could show an empty box with nothing to press.
- A computer stays linked, with a plain sentence, while a routine it runs cannot be paused, so a routine never
  runs on two computers.
- One status sentence for every twin, worked out in one place: the Twins page, the terminal and `/twin` say the
  same words, and a twin's state follows its counts of changes and choices.
- The sample tour no longer sends you to the Grok app: after `demo secret` it names `demo grok-edit`, it ends with
  `send-to-grok`, and `finish --all` with only the sample says so instead of "No twins yet".
- The README says at the top that the Plugins button and the catalog name give the older 0.2.1, gives the one
  command for this version, and states the minimum Hermes (0.22.7) before any install line.
- The README is one screen (133 lines, was 1,289); the rest moved, once, to docs/GUIDE.md, docs/SHARING.md and
  docs/TERMINAL.md. The plugin description that `hermes plugins list` prints is 58 words (was 2,464) and points to
  docs/DISCLOSURE.md, now the one disclosure.

## 0.3.4 (12 November 2026)

Smaller and safer: the fixes from the cycle-2 review, mostly by removing code (about 1,300 fewer product lines).

- Removed "Let Hermes do the Grok part" (Hermes clicking in the Grok app). Its guard stopped protecting a chat once
  its 30 minutes ran out, and it was never run against the real Grok app. Bringing instructions over stays as it
  was: `hermes twin finish --all` prints the request you paste into each bot, and `import-exports` reads the answers.
- Removed the model tool `twin_ask_machine`: a chat can no longer start a request on another computer. You still can,
  with `/twin ask`, `hermes twin ask` or the Twins page. `hermes twin ask` refuses a command that a chat started.
- Removed the approval mode "Let my own linked computers approve". A stored choice now reads as "Ask on this
  computer". `/twin` and the request checks refuse a chat whose platform is missing or unknown.
- One password-and-key check for everything (memory, setup exports, instructions, Hermes to Grok). Short
  `NAME=value` passwords such as `DB_PASSWORD=hunter2` are now caught on the way to Grok. Ordinary instruction text
  ("Passwords must have at least 8 characters") is not held.
- A twin with an instructions or Hermes to Grok conflict no longer says "Up to date": it says it needs you and
  which item to choose, in the terminal, in `/twin` and on the Twins page.
- Stop twinning now also withdraws the twin's Hermes to Grok permission (the Mirror's allow list no longer names the
  bot) and switches off its memory layers.
- "Move routines to Hermes" refuses a routine that runs in Grok (or is being moved), so a routine never runs in
  both places.
- Fixed a rare hang when the Mirror's answer and a What syncs change arrived together. Moving a routine between
  Hermes and Grok no longer holds the plugin's lock while `hermes cron` runs.
- No background thread before you have a twin (or share or link a computer); the threads end when nothing is left.
  A round checks and syncs by default; the optional parts run only while they are on, and one failing part no
  longer holds up or slows the others.
- One place talks to Hermes' own code (`twin/config.py`). The checks "is this chat local?" and "is this skill safe?"
  refuse when Hermes cannot answer. A Hermes routines file (`cron/jobs.json`) in a shape the plugin does not know is
  left alone with a clear message, instead of being read as empty and written over.

## 0.3.3 (12 November 2026)

- Installs from GitHub again without `--force`: Hermes' install scan stopped the install because three source
  lines held invisible characters typed in raw form. Those characters are now written as escapes (`\u200b`), in
  the tests too, and a new test fails if any file of the plugin holds a raw invisible or text-direction character.
- README: names the minimum Hermes version (0.22.7) and the install line for the `next` branch, and no longer
  points to a catalog file that is not in this repository.

## 0.3.2 (12 November 2026)

- Hermes to Grok out of beta: there is no switch for the whole plugin any more. It is off for every twin until you
  allow that twin, and nothing is sent before you saw the preview and applied exactly that preview.
- The preview shows exactly what is sent: whole texts, the whole instructions diff, routine prompts in full, and
  the schedule in words when it is simple. The terminal shows a routine's schedule and prompt changes.
- A signed list of the bots you allow now (`to-grok/allowed.json`) sits next to the requests. The Mirror's box
  makes a change only for a bot in that list, never from an older list, and never twice.
- Stopping a twin takes its waiting requests back and names the exact Auto-Review rule to delete in Grok; allowing
  records that rule.
- Bot content cannot steer the Mirror: a bot name with quotes, commas or linking words is left out (the id is
  used), routine names sit between BEGIN and END lines like other texts, a schedule must be plain cron, and a text
  that holds the change's own id is not sent. The Mirror's read-back gives only a name and description.
- Undo and moving where a routine runs check again that the twin is allowed, the item's direction and the Mirror's
  permission. A routine set to run in Grok while its Hermes copy is on is held, so it never runs twice.

## 0.3.1 (12 November 2026)

- Full transcripts (off for every twin until you switch them on): the archive
  of whole conversations, from Hermes chats and from a Grok export you hand
  over, kept on this computer. The text is encrypted at rest with a key kept
  apart from the archive. The twin's own tool searches only that twin's
  conversations, and never inside a request from another computer. Sending
  to Grok is a second switch, off by default, needs the Mirror, offers only
  chats held on this computer, and masks passwords and keys first. Stop
  twinning or `hermes twin transcripts forget --yes` deletes what was kept.
  See docs/DISCLOSURE.md for exactly what is kept and what it does not
  protect against.

### Moved to a later release

- Hermes to Grok out of beta: in 0.3.2.

## 0.3.0 (12 November 2026)

More than skills now syncs between a twin and its Grok bot.

- Memory facts (off for every twin until you switch it on): the facts a Grok bot remembers and the notes in the twin's
  memory files are kept the same, both ways. Anything that looks like a
  secret or an instruction stays where it was written. This needs the
  Mirror; until it is set up, no fact moves.
- Session briefs: a finished conversation becomes a short brief (who took
  part, what was decided, open threads, next step) for the other side. Off
  for every twin until you switch it on; it needs the Mirror to reach Grok.
- Instructions: with skill sync set up, a twin's instructions follow its Grok
  bot's every 15 minutes, unless you switch that off. When it is unsure which
  to keep, you are asked.
- What syncs panel: one place per twin to choose what copies and in which
  direction.
- Skills from Grok to Hermes: an edit made in Grok to a skill Hermes sent now
  comes back (it was dropped silently before), and skills made in Grok come
  back when you choose them (`hermes twin skill-sync TWIN --take NAME`).
- Hermes to Grok (beta, off by default): name, description, instructions and
  routines go from Hermes to the Grok bot through the Mirror, after you look
  at a preview and apply it.

### Moved to a later release

- Full transcripts (the archive of whole conversations): in 0.3.1.
- Hermes to Grok out of beta: moves to 0.3.2.
