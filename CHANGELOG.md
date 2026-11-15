# Changelog

## 0.4.0 (15 November 2026)

- **Secrets by reference.** A key the plugin's secret check finds in a bot's text is no longer just blanked: when this
  computer has an OS secret store (macOS Keychain, Linux Secret Service, Windows Credential Manager) the value is kept
  there under a NAME (service `grok-bot-twin`) and the text keeps a placeholder: `{{secret:NAME}}` towards Grok,
  `${NAME}` towards Hermes. The twin's Hermes bot gets the value the way Hermes keeps its own keys, as a line of the
  profile's own `.env` (0600), written only when the call PASSes. Done on `hermes twin sync`, `from-grok` and
  `back-to-grok`; the answer names the keys kept, never a value. `hermes twin secret list|set|forget|share`
  (`share NAME --to-grok` is the one way a value reaches the Grok bot, asked in your own terminal; `--linked` lets
  your other computers fetch it over `POST /v1/xs/secrets`, sealed like a twin's memory, off by default). No OS
  store: nothing is kept and the value is blanked as before; there is no file fallback. See docs/SECRETS.md.
- The optional git history refuses a remote address that carries a password or token (it would have been kept in
  plain text); sign in with git's credential helper or an SSH key.
- Optional git history per twin, off by default (no git needed unless it is on): `hermes twin git on "NAME"`
  (or `--all`) `[--remote URL] [--with-history]`, `hermes twin git off`, `hermes twin git status`. After every
  PASS of the one-prompt tools (twin, sync, move, back) the bot's instructions, skills, memory and routines are
  written as Markdown/JSON to `<plugin-data>/git/<twin>/` and committed ("PASS sync from Grok: 2 skills
  changed"); with a remote (a Forgejo URL, say) it pushes, and a failed push is a warning on the PASS line, never
  a FAIL. Secret-scrubbed first; keys, tokens and `.env`/auth files are never read; chat history only with
  `--with-history`. Snapshots stay at 3. See docs/ONE-PROMPT.md.

- `hermes twin quick "Acme Support" --model MODEL --yes`: one twin start to finish in one command. It runs `add`,
  prints the request to paste into the bot's chat in Grok, waits (15 minutes by default, `--wait MIN`) for the
  answer file in Downloads, then runs `import-exports`, `finish` and `compare`, and ends with one PASS/FAIL
  summary. Each step asks as it always does unless `--yes`. Run it again at any time: a step that is done is
  skipped. No model is called. `--from-file FILE` or `--stdin` takes the bot's setup export directly (no paste,
  no wait), so an agent can run it in one non-interactive command. The last line is always `PASS: ...` or
  `FAIL: ...`.
- `hermes twin test "Acme Support" --from-export FILE` (or `--battery FILE`): botport's behaviour test (`botport test`) of a
  twin, through the same verified botport copy and minimal environment. Each case is a real chat with the twin's
  model. `--from-export` makes the cases once (`botport battery init`) and keeps them for the next run. The last
  result (passed of total, the ids of the failed cases) shows on the twin's line in `hermes twin status`.
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
- Twins the one-prompt flow (or `hermes twin sync --stdin`) is used for become **bot-driven**, once: a copy of their
  botport parts is kept, then `botport twin remove` (the Hermes profile and its chats stay). Status shows them as
  "Kept in step by the bot · last synced …, PASS". Not yet: a bot-driven twin does not follow a rename or a new
  description in Grok between prompts (follow-up: apply them from the Grok bot list, read-only).
- botport errors no longer hide the plugin's own file names as `[secret]`: the command is named by its words
  only, and the plugin's folders are said in words.

### Decision: bot-driven twins (15 November 2026)
botport v0.2.1 refuses `apply`, `sync` and `drift --bundle` on any profile its twin pairing owns (the
`botport.mirror.json` file `twin create` writes), and has no call that applies a bot's own export to such a
profile: `twin sync --from-export` ignores the export, `twin adopt` skips a paired bot, and after a remove a
changed skill becomes a conflict. Memory is never part of botport's twin sync. So a twin the bot keeps in step
itself is converted once with `botport twin remove` (profile kept) and then goes through the spec path, as the
two-way sync already did. Considered and rejected: remove, adopt and resolve on every call (fragile, and it loses
the restore points each time). Long-term option: an "apply this export" call in botport for a paired profile, after
which no twin needs converting.
- `hermes twin quick --all --model MODEL --yes`: `quick` for every Grok bot in turn (never the sample's), one
  line per bot and one verdict, `PASS: quick setup of 2 of 2 bots` or `FAIL: ...`.
- `hermes twin link-computer [--wait MIN]`: one command to link one more computer. It turns sharing on, prints a
  link code and the line to run on the other computer, then waits (10 minutes at most, as long as the code lasts)
  until a computer has used it: `PASS: another computer is linked` or `FAIL: ...`.
- `hermes twin stop` now needs the twin named (`hermes twin stop "Acme Support"`), ends with `PASS:`/`FAIL:`, and
  keeps the twin's full transcripts and What syncs choices unless `--remove-data`. The Twins page's Stop twinning
  is unchanged (it deletes them, as before).
- The same three are library functions (`twin/bulk.py`: `quick_all`, `link_computer`, `stop_twin`) for a Hermes
  model tool; `stop_twin` is a dry run unless confirmed and has no remove-data choice. No tool is registered.

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
