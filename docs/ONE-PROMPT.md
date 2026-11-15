# One prompt in Grok: twin, back up, move, come back

A Grok bot in the Grok desktop app does each of these jobs in one prompt. It reads its own instructions, skills,
memory and routines, runs ONE command on your computer, applies what comes back with its own tools, and reports
one line that starts with PASS or FAIL. Nothing else is done by hand. Issues #41 (twin), #43 (sync) and #44
(move and back).

| Prompt (any wording) | The bot runs (once) | The bot then does itself | PASS means |
|---|---|---|---|
| "Clone yourself to Hermes", "Back yourself up to Hermes" | `hermes twin from-grok` | nothing | twin made or synced; drift clean; behaviour test passed |
| "Move yourself to Hermes" | first pauses each of its routines with UpdateRoutine (Grok's tool), then `hermes twin from-grok` with `"move": true` and `"grok_paused"` | if a pause is refused: switches back on the ones it paused and reports FAIL, without running the command | as above, plus the twin's routines on in Hermes (`hermes twin switch`). The plugin checks that every routine the bot sent is in `grok_paused` before it turns anything on, else FAIL with nothing turned on; a FAIL after the pauses lists the routines to switch back on in Grok |
| "Come back to Grok" | `hermes twin back-to-grok` | writes `bundle.memory` (UpdateMemory) and `bundle.skills` (UpdateSkill); re-enables `bundle.routines_to_enable` (UpdateRoutine) | the plugin's PASS: drift clean both ways and Hermes routines paused (`hermes twin switch --undo`). The bot's own tool calls are checked by the bot, not the plugin: if one fails, the bot reports FAIL naming it (the skill says so) |

## How the bot reaches your computer

The Grok desktop app gives a bot two places to run a command: its own cloud computer ("Grok Bot's computer") and
yours ("Run a command on your local computer", the app's *Execution on Local Computer* permission). A custom
connector of type *Command* (Connect apps → Add a custom connector) runs on the **bot's cloud computer**, never on
yours (Grok Bot 1.0.1, checked live: see LIVE-TEST-41 in the project's notes). So the supported route is that
permission: per prompt, the bot runs exactly one command on your computer:

    hermes twin from-grok --bot "Acme Support" <<'TWIN_JSON_EOF'
    {"bot_name": "Acme Support", "instructions": "...", "skills": [...], "memory": [...], "routines_meta": [...],
     "history": [...]}
    TWIN_JSON_EOF

The JSON is the bot's own state: the same arguments as the `twin_from_grok` tool. What the command prints is the
answer: the PASS or FAIL line, then details as JSON. `hermes twin back-to-grok` is the same for coming back.

**One approval click per prompt.** The Grok app asks you once for each command ("Allow once"). That is the only
click. If you choose *Always allow* for Execution on Local Computer, the prompt needs no click at all. That is
your choice: it applies to every bot in the app, not only this one.

`hermes twin mcp --bot NAME` serves the same two calls as a local MCP server (JSON-RPC on stdin/stdout). It is
kept for a later Grok app that runs connectors on your computer; today it is not the route.

## Once per bot (setup, not part of the prompt)

You need: Hermes Agent with this plugin on, and botport set up (`hermes twin setup --check` shows it), on the
computer with the Grok desktop app, with `hermes` on the PATH of your login shell.

1. **Add the skill.** Give the bot the text of [grok/SKILL-twin.md](../grok/SKILL-twin.md) as a skill (or paste
   it at the end of its instructions). It maps "twin", "clone", "copy", "duplicate", "back up", "move" and "come
   back" to the one command.
2. **Optional: no click per prompt.** Set Execution on Local Computer to *Always allow* (see above).

`--bot` binds the command to that one bot: JSON that names any other bot, or carries anything that is not in the
schema (a path, a profile), is refused before anything is read. The name the JSON sends is only what the calling
bot says it is, so with `--bot` repeated every call is refused unless the environment sets `GROK_BOT_TWIN_CALLER`
to the calling bot's name (one of the `--bot` names); then only that bot's calls are taken. Bot A can never write
bot B's twin.

## What the command does

1. Finds this bot's twin (by the bot's name), or makes it the way `hermes twin add` does.
2. **Makes the twin bot-driven, once.** botport v0.2.1 refuses its apply/sync/drift on a profile its own twin
   pairing owns, and has no call that applies a bot's export to such a profile. So the first one-prompt call for
   a twin first copies the botport parts of its Hermes folder (`one-prompt/converted/PAIR/STAMP/`, never put back
   by itself), then runs `botport twin remove`: the profile, its chats and everything in it stay, as a normal
   profile. From then on the bot keeps its twin in step with each prompt (status says "Kept in step by the bot ·
   last synced …, PASS"). This touches only twins the one-prompt flow is used for, and is done once.
3. Takes a snapshot of what it may change in the twin's Hermes folder (`SOUL.md`, `skills`, `cron`, `memories`,
   `config.yaml`, botport's lock files), under the plugin's folder (`one-prompt/snapshots/`, the last 3 kept).
4. Writes the bot's words as one `grok-bot-export` file (`one-prompt/exports/PAIR.json`, owner-only) and runs
   `botport sync --adopt` with it into that twin's own profile (instructions, skills, memory); routines are added
   switched off through the plugin's own import. Turning them on is the move prompt.
5. Puts the bot's memory where the twin's own `memory` tool reads it (Hermes' `memories/MEMORY.md`, a union, as
   much as Hermes' limit allows; the line says how many did not fit).
6. Brings the bot's own conversations over (`history`, the last 50 at most, and under 8,000 characters: Grok shows
   the command for approval and refuses a long one (about 14 KB failed live), so the skill sends the newest first,
   trims, and leaves its own twin skill out of `skills`): each becomes a Hermes chat of the
   twin, "From Grok: …"; a conversation sent again adds only its new messages (twin/history.py). Never a FAIL by
   itself: what could not be imported is said in the line.
7. Proves it: `botport drift` must be clean, the behaviour test (`botport test`, as `hermes twin test`) must
   pass, and no written file may look like it holds a password or key. Compare-with-Grok is shown too.
8. On any FAIL, puts the snapshot back and says so in the line.

### What a bot-driven twin does not do (yet)

A twin botport pairs follows the bot's name and description from the Grok app's own list within seconds. A
bot-driven twin follows the bot at each prompt instead: between prompts, a renamed bot or a new description is
not carried over by itself. Planned follow-up: apply name and description changes read from the Grok bot list
(read-only) to bot-driven twins. The long-term fix is in botport (an "apply this export" call for a profile its
pairing owns), after which twins need not be converted.

## Safety

- Two calls only (`from-grok`, `back-to-grok`). No delete, stop or path arguments; anything not in the schema is
  refused. `move` turns on only this twin's own switched-off routines; coming back pauses only the ones moving
  turned on. Both take the same snapshot first and put it back on any FAIL.
- Writes only to the named bot's own twin profile, never `default`.
- Every text is screened by the plugin's password/key check first; such lines are left out and counted.
- Size limits on every argument; one run per bot at a time (a second is refused while the first runs).
- Every call is logged in `one-prompt/calls.jsonl` (when, which bot, PASS/FAIL, counts; never the texts).
- The bot's model runs in the cloud and could be steered by text it reads. The allowlist, the fixed schema, the
  snapshot and the log are there for that. If you are unsure, leave Execution on Local Computer on *Ask*: you
  then see each command before it runs.

## Optional git history (off by default)

The default does not change: the twin's Hermes files, the last 3 snapshots, and chat history in Hermes' own
database. Nobody needs git. If you want a history you can browse (or push to your own Forgejo), switch it on:

    hermes twin git on "Acme Support"                       # or --all
    hermes twin git on "Acme Support" --remote https://forgejo.example/me/acme-support.git
    hermes twin git status
    hermes twin git off "Acme Support"

After every PASS of twin, sync, move or back, the bot's instructions (`instructions.md`), skills (`skills/`),
memory (`memory/`) and routines (`routines/`, JSON with sorted keys) are written to
`<plugin-data>/git/<twin>/`, one repository per twin, and committed with a message such as
`PASS sync from Grok: 2 skills changed`. Nothing changed means no commit.

- With `--remote` it pushes `main` after the commit. A failed push is a `Warning:` on the PASS line, never a FAIL;
  the URL is kept in the plugin's settings (mode 600), not in the repository, and never printed.
- Everything goes through the plugin's secret scrub first; a file that still looks like a key is left out. Plugin
  keys, tokens and `.env`/auth files are never read.
- Chat history is left out unless `--with-history` (then one Markdown file per Hermes session under `history/`).
- No git on this computer: the PASS line says so and how to install it; the sync itself still passes.

## Check it yourself

`hermes twin status` shows the twin's line. `hermes twin test "Acme Support"` reruns the behaviour test, and
`botport drift --bundle=<the export file> --profile=<profile>` gives the drift proof by hand.
