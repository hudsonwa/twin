# One prompt in Grok: twin, back up, move, come back

Tell a bot in the Grok desktop app "Clone yourself to Hermes" and it makes its own Hermes twin. It reads its own
instructions, skills, memory, routines and recent conversations, runs **one command** on your computer, and
answers with one line that starts with **PASS** or **FAIL**. The same works for keeping the twin up to date,
moving the bot to Hermes, and bringing it back.

| Say to the bot (any wording) | What happens | PASS means |
|---|---|---|
| "Clone yourself to Hermes" | The twin is made, or updated if it exists. | The twin matches what the bot sent and passed its behaviour test. |
| "Back yourself up to Hermes" | The same: the twin is brought up to date. | As above. |
| "Move yourself to Hermes" | The bot pauses its routines in Grok first, then the twin's routines are switched on in Hermes. | As above, and the routines now run in Hermes only. They run only while Hermes and its scheduler run (`hermes cron status`). |
| "Come back to Grok" | The bot switches its own routines it paused when it moved back on, and the twin's routines are paused in Hermes. Hermes gives the bot its current memory and skills only when you allowed Hermes → Grok for that twin (`hermes twin to-grok TWIN allow`); the bot then shows you every fact and skill name and saves them only after your yes in the chat. | Hermes paused its routines (and, if allowed, handed back memory and skills; otherwise the line says how many stay in Hermes). The bot reports FAIL if one of its own saves fails; check the bot's Skills tab. **Not sent back:** instructions, and routines you made or changed in Hermes: copy those into Grok yourself. |

**On this page:** [Before you start](#before-you-start) · [Set it up](#set-it-up-once-per-bot) ·
[What it copies](#what-it-copies) · [What the bot sends](#what-the-bot-sends) · [If it says FAIL](#if-it-says-fail) ·
[Undo or stop](#undo-or-stop) · [Safety](#safety) · [Git history](#optional-git-history) ·
[From Hermes, and chat sync](#from-hermes-and-chat-sync). Words such as
*bot-driven* and *behaviour test* are in [Words used](GUIDE.md#words-used).

## Before you start

**Needed**, on the Mac with the Grok desktop app:

1. **The plugin and botport.** Install with the line in the [README](../README.md#install), run
   `hermes twin setup`, download botport when it asks, then run `hermes twin setup` again and answer yes.
   `hermes twin setup --check` then shows botport with ✓; "No twins yet" is expected (the prompt makes the twin). botport
   confirms the bot is in your Grok app, makes the twin and runs its test.
2. **`hermes` findable by the Grok app.** In a terminal, `zsh -lc 'command -v hermes'` must print a path. If it
   prints nothing, link it into a standard folder, which works whatever shell the Grok app uses:
   `sudo mkdir -p /usr/local/bin && sudo ln -s "$(command -v hermes)" /usr/local/bin/hermes`. (Adding its folder,
   often `~/.local/bin`, to `PATH` in `~/.zprofile` also works for a zsh login shell.)
3. **A capable model in Hermes.** Each run asks the twin's model a handful of test questions made from the bot's
   instructions, and **every one must pass**. Use a capable model for the first run; you can change the twin's
   model later. With a cloud model, those questions go to that provider.
4. **A bot that fits in one command.** The Grok app refused a command of about 14 KB in a live test. Keep the
   bot's instructions, skills and memory together under about 6 KB (ask the bot "how many characters are your
   instructions, skills and memory together?"); recent conversations are trimmed to fit, or left out. Larger
   bots: use the [Twins page](GUIDE.md#connect-your-grok-bots).

**Good to know before you move or back up:**

- Hermes does not need to be open for the prompt: the command runs by itself.
- **Before you move routines:** Hermes runs them from its gateway, so they run only while it does.
  `hermes cron status` says "Gateway is running" when they will fire; `hermes gateway install` keeps it running in
  the background, also after a restart. Moving pauses the routines in Grok, so check this first.
- **Keys travel in the command.** API keys in the bot's skills or memory are part of the command the bot runs, so
  they show in that Grok chat. If that matters, remove them in Grok first ([SECRETS.md](SECRETS.md)).
- **A PASS cannot be undone without git history.** Switch it on before the first run
  (`hermes twin git on --all`): every PASS then becomes a commit you can [restore from](#undo-or-stop).

> **Bot-driven twins (the one place this is explained).** A twin the first one-prompt run makes is
> *bot-driven*: it follows the bot at each prompt, and no longer follows a new name or description in Grok
> by itself. If this bot already has a twin on the Twins page (one that follows it through botport), the prompt
> does not change it: it says FAIL, writes nothing, and names your own step. Run it once, in your own terminal:
>
>     hermes twin bot-driven "Acme Support"
>
> It asks, and goes ahead only on a `yes` you type there (`--yes` does not skip it; a chat, a bot or a script is
> refused); `--dry-run` shows what changes. Its Hermes bot and chats stay as they are. Then say the prompt again.
> There is no switch back: stop twinning it (`hermes twin stop "Acme Support"`) and twin it again on the Twins
> page. `hermes twin status` shows a bot-driven twin as "Kept in step by the bot".

## Set it up once per bot

Say these prompts **in the bot's chat in Grok**. In a Hermes chat, "twin my Acme Support bot" is a different
thing: it makes a Twins-page twin ([GUIDE](GUIDE.md#start-from-wherever-you-are)).

1. **Give the bot the skill.** In the Grok desktop app, open the bot, go to its **Skills** tab and press **Add
   new skill**. Fill the three fields from a terminal (on a Mac, `| pbcopy` puts each on the clipboard):
   - **Name:** `hermes twin skill-text --name` (it prints `twin-to-hermes`);
   - **Description:** `hermes twin skill-text --description`;
   - the large text box: `hermes twin skill-text --body | pbcopy`, then paste;
   - then **Save skill**.

   If the terminal says `invalid choice: 'skill-text'`, your plugin is older than 0.4.1: update it (the README's
   install line with `--force`), or copy the parts from
   [grok/SKILL-twin.md](https://github.com/hudsonwa/twin/blob/next/grok/SKILL-twin.md) (the `name:` and
   `description:` lines, then everything below the second `---`).

   Add it as a skill, not into the bot's instructions: the instructions are copied to the twin word for word.
   The skill teaches the bot to turn "twin", "clone", "copy", "back up", "move" and "come back" into the one
   command.
2. **Let the bot run commands on this computer.** In the Grok app: **Settings → Bot → Execution on Local
   Computer**. It has three choices: **Always allow**, **Ask every time** (the default) and **Never allow**. It is
   a setting of the Grok app on this computer, so it applies to every bot there. (The bot itself sees it as its
   "Run a command on your local computer" tool.)
   - **First prompt: keep Ask every time** and press **Allow once**. Check the command exactly: line 1 is
     `hermes twin from-grok --bot "<this bot's name>" <<'TWIN_JSON_EOF'` with nothing after the marker;
     `TWIN_JSON_EOF` appears exactly twice (end of line 1, and alone on the last line); everything between is
     one `{…}` JSON object. Anything else: do not allow it.
   - **Then, if you trust every bot in your Grok app with this computer: Always allow** (an optional convenience). Twin, back up, move and come back each become one prompt with no click. The cost: every bot
     in the app can run *any* command on this computer without asking ([Safety](#safety)). Otherwise stay on Ask
     every time; set it back when you stop using the one prompt.

Now say "Clone yourself to Hermes" in the bot's chat. A PASS looks like this:

    PASS: Acme Support twinned to Hermes (profile acme-support): 3 skills, 12 memories, 2 routines added switched off; matches what the bot sent; behaviour test 5/5.

The next time it says "synced with Hermes", or "already level with Hermes" when nothing changed.

A custom connector of type *Command* (Connect apps → Add a custom connector) does not work for this: the Grok
app runs those on the bot's cloud computer, not on yours.

## From Hermes, and chat sync

**Experimental, and it needs botport's Grok engine** (`botport grok`, which is not in a botport release yet; the
file route below also needs its `files fetch` and `routines` commands, on botport's P3 branch). Without it
`hermes twin from-hermes` says FAIL and names the ways that work. It reaches the bot through the Grok app on this
Mac, not through Grok's servers.

    hermes twin from-hermes "Acme Support"
    hermes twin from-hermes --all

or say "twin all my Grok bots" in a Hermes chat (the tool `twin_from_hermes`).

### The export route (the default)

No skill in the bot, no local command, no approval card, no Grok setting to check. Hermes:

1. reads Grok's Execution on Local Computer setting (read only), to compare at the end;
2. reads the bot's chat (`botport grok read`) and lists its routines (`botport grok routines`) **through the
   engine**: history and routines never come from the bot's own words;
3. asks the bot for a `grok-bot-export/1` (its instructions, memory and skills, nothing else) made with its own
   cloud tools only ("use no local-computer tools; do not store this in your memory"). Up to about 20 000
   characters the bot pastes it as one ```json block; above that it sends it as a file, `twin-export.json`, which
   Hermes saves with `botport grok files fetch` into a private temporary folder, reads, and removes at once
   (`--file` asks for the file in any case);
4. checks the export as untrusted data, in memory, before anything is written: a strict schema (no unknown fields,
   right types, size caps), the bot's name must be the one the engine reported, skill names must be plain
   (letters, digits, space, `. _ -`; no paths, newlines or escape codes), no text may look like a password or key,
   and no text may drive this plugin's or botport's own commands. Any of these is a FAIL with nothing written;
5. imports it with the same importer as the one prompt (botport `sync` into the twin's profile, the engine's
   routines added switched off, the chat from step 2 as Hermes chats), with the same proof: botport drift, the
   behaviour test, the secret check, and everything put back on a FAIL;
6. checks once more: the one-prompt log holds the importer's PASS, the Grok setting reads as in step 1, and the
   export turn held no approval card. When the bot sent a file, it is asked to delete it again.

```
PASS: Acme Support: twinned through the engine, no local command (the bot pasted its export): Acme Support twinned to Hermes (profile acme-support): 3 skills, 12 memories, 2 routines added switched off; matches what the bot sent; behaviour test 5/5. Skills imported: 3; made by other bots or shared, not imported: team-notes. History: 40 message(s) read by the engine; routines: 2 from the engine, all switched off. Chat sync: this computer reads the chat every 360 min from after the export. Checked: the one-prompt log has the PASS at 14:02:11; Grok's Execution on Local Computer setting reads Ask every time as before; no approval card in the export turn.
```

**Skills made by other bots.** Grok's skills look account-wide: a bot's export can list skills other bots made.
The bot marks each skill as its own or not; only its own come in. With `--all`, a skill that more than one bot
marks as its own goes into each of those twins and is named in the PASS line ("claimed as their own by several
bots, imported into each"). Skills a bot does not mark as its own are named in the PASS line and not imported;
`--shared-skills` imports them too. A skill another bot made that fails the export checks (or has the same name as
one of the bot's own) is skipped and named; it never fails the bot's export. In the `twin_from_hermes` tool's
answer to the Hermes model, skills other bots made are counted, not named.
A skill in which the bot wrote `[REDACTED]` for a key is held back and named; memories it redacted are left out.

**Without the engine.** This plugin version pins botport 0.3.3, which has the Grok engine. If an older release is
chosen with `botport_release_tag`, `from-hermes` with no engine FAILs with "needs botport 0.3.0 or newer (the Grok
engine); the botport_release_tag setting chooses 0.2.1" and setup is not run; say the prompt in Grok instead. Otherwise
when botport is missing, too old or not verified, `from-hermes` first runs `hermes twin setup --auto` once by itself (the pinned, SHA-256-checked botport release; no Grok setting changed; the port is
not opened), then carries on, so twinning stays one prompt. If setup FAILs, the line is the usual "engine not
available" FAIL with setup's reason. A closed port is not "missing": no setup runs, run `botport grok launch`.

**Safe profile defaults.** Every twin profile this makes or adopts gets the safe defaults by rule
(`hermes twin safety`: `parity`, the twin can do what its Grok bot can do: browser, web and X search, shell, files,
code, image generation and computer use, in the desktop app and Telegram alike; risky actions ask first in the chat
they came from, and agent scheduling and delegation stay off), applied on what the import wrote and before the
behaviour test or anything else runs in it. The PASS line lists the capabilities. A choice you made with
`hermes twin safety TWIN parity|strict|standard|open` is kept. `hermes twin add` and the
one prompt from Grok do the same when they make a profile. If `add` cannot apply them, its line is a FAIL and the
twin's routines and Telegram route stay off until `hermes twin safety TWIN --apply` passes.

**Only from this computer.** A messaging chat (Telegram and the like) cannot start twinning or setup: the
`twin_from_hermes` and `twin_make` tools refuse when Hermes says the chat is a messaging one, unless the setting
`setup_from_messaging` is on. A from-hermes run and chat sync's background pull share one lock, so a pull never
closes the Grok port during an export.

**Command-like text in an export (N6).** Text that drives this plugin's or botport's own commands (`hermes twin
...`, `hermes -p X twin ...`, `botport grok|sync|apply|twin|drift|export|test|setup ...`) anywhere in the
instructions, skills or memories is a FAIL with nothing written. Any other command-like text ("run `ls -la`",
"deploy with make") is imported as plain data: it is written only into the twin's own profile and nothing runs
it. Issue #49's "commands" means the first kind only.

Not yet, said plainly: the engine cannot open a new chat, so the export turn happens in the bot's usual chat (chat
sync starts after it, so it never lands in Hermes chats); the engine cannot list files a bot sent, so the clean-up
of a sent file is the bot's own word (the line says whether it answered DONE); the file route is tested against
the engine's fake transport and a stub, not yet live.

| What you see | What to do |
|---|---|
| the Grok engine is not available | botport is missing, has no Grok engine yet, or the Grok app's local port is closed. Run `botport grok launch` (the fast preset; it restarts the Grok app with its local port open) and try again. |
| the export was refused: … | The bot's answer broke a rule in step 4. Nothing was written. Try again; if the bot keeps doing it, its instructions or skills hold what the line names. |
| the bot is waiting for an approval in Grok … the card is left for you | The export asks for no local command, so the bot did this by itself. Hermes never clicks it. Answer or deny it in Grok. |
| the setting read … before and … after | Grok's Execution on Local Computer setting changed during the run; nothing was written. |
| botport's policy refused it / run botport grok canary | botport's own settings, or an untested Grok version. |

### The shell route (`--route shell`, kept as an option)

After the setup above (skill added, local commands allowed), `--route shell` (or the setting
`from_hermes_route: shell`) sends the bot "Clone yourself to Hermes" through the engine and the bot runs
`hermes twin from-grok` on this computer, as when you say the prompt in Grok. It waits while the bot works (up to
15 minutes per bot, `--timeout`), then checks two things: the bot's own PASS line, **and** a PASS for that bot in
this computer's one-prompt log since the ask.

| What you see | What to do |
|---|---|
| the bot is waiting for an approval in Grok | Usually the local-command box (Ask every time). Check the command as in step 2 above and answer it **in Grok**; Hermes never answers it. Then `hermes twin from-hermes "Acme Support" --route shell --wait`: it waits for the same run and asks nothing again. |
| chat sync by routine needs … Always allow | Use `chat_sync_mode` `pull` (the default), or set Always allow in Grok yourself ([Safety](#safety): any bot may then run any command) and run it again. |
| the bot is still working after … s | `hermes twin from-hermes "Acme Support" --route shell --wait` later. |
| the bot reported PASS, but this computer's one-prompt log has no PASS | The bot did not run the command here (on its cloud computer, say). See the table under [If it says FAIL](#if-it-says-fail). |

**Chat sync** keeps the twin's Hermes chats up with the bot's new messages. The setting `chat_sync_mode` in the
plugin's settings chooses how, and `chat_sync_minutes` how often (360, every 6 h, by default; 15 to 1440):

| `chat_sync_mode` | How | Costs |
|---|---|---|
| `pull` (default) | This computer reads the bot's chat through the engine on the plugin's background check, from where it left off (it keeps that place itself), in a short port window opened only while the Mac is idle (below). The first read is part of the PASS. | No Grok usage. Needs the engine, Hermes running, and the Grok app open. |
| `routine` (opt-in, `--route shell` only) | The prompt also asks the bot to make a Grok routine, **Sync chats to Hermes**, that sends its recent messages with one local command, `hermes twin chat-sync --bot "NAME"`, and to run it once right away. The PASS line confirms the routine (the bot's word, until botport can list routines) and that this first sync landed. | One Grok turn per run, and the Grok app must be open. **Only when Grok's Settings → Bot → Execution on Local Computer is Always allow.** Hermes reads that setting and never changes it; otherwise it says FAIL and why. |
| `off` | No chat sync; the prompt copies recent conversations as before. | – |

**Idle-only windows (default, twin#52).** The engine reads the chat through the Grok app's local port, and opening
the port restarts the app. So each due pull asks botport for a short window, `botport grok launch --for 10m
--when-idle 10`: a port already open long enough is reused with no restart; otherwise the app restarts only when
the Mac has had no keyboard or mouse input for `chat_sync_idle_minutes` (10 by default). If the Mac is in use
(exit 2) the pull is skipped and tried again 30 minutes later: nobody is interrupted and no turn is cut off. A
window the pull opened is closed again with `botport grok restore` (botport's TTL guard closes it in any case).
`chat_sync_window: port` never launches: it pulls only when the port is already open. Needs botport 0.3.0 or newer
(this plugin version pins 0.3.3). A pull that fails waits a full `chat_sync_minutes` before the
next try, and a stopped twin leaves chat sync (and the Telegram route) at once, so neither opens a window again.
`hermes twin chat-sync --status` shows the last skipped window and why.

Why `routine` needs Always allow: in a live test (Grok Bot 1.1.0) a routine running on its own under **Ask every
time** never ran the command. Each run stopped at an approval card, which expired after about 10 minutes, so
nothing was sent. With the Grok app quit, the run failed. A routine also does not know what it sent last time, so
the routine always sends the whole recent window and this computer keeps track of which messages are new.

Either way a message lands once: messages Hermes already has are skipped, even when a conversation comes back with
another title. `hermes twin chat-sync --status` shows each twin's last run; `hermes twin chat-sync --pull "Acme
Support"` pulls now. To stop a routine, pause or delete it in Grok.

The routine needs the skill text of this version (`hermes twin skill-text`): its "Chat sync" part lets the bot
run the chat-sync command, and only when the request asks for it.

## What it copies

| What | One prompt |
|---|---|
| Instructions, skills | Copied in full at each prompt; the twin's become the bot's. |
| Memory | Added to the twin's Hermes memory (as much as fits); never removed. |
| Routines | Copied switched off; "Move yourself to Hermes" switches them on and pauses Grok's. |
| Recent conversations | The last few, trimmed, as Hermes chats "From Grok: …". |
| Name and description | At each prompt, not by themselves in between. |
| Back to Grok ("Come back") | The bot's own paused routines switched back on. Memory and skills only if you allowed Hermes → Grok for the twin, and only after your yes in the chat; instructions and routines changed in Hermes you copy yourself. |
| Between your computers | As for any twin ([SHARING.md](SHARING.md)). |
| Logins, passwords, cookies | Never. |

## What the bot sends

The bot runs this one command on your computer, with its own state as JSON (the skill builds it):

    hermes twin from-grok --bot "Acme Support" <<'TWIN_JSON_EOF'
    {"bot_name": "Acme Support", "instructions": "...", "skills": [...], "memory": [...], "routines_meta": [...],
     "history": [...]}
    TWIN_JSON_EOF

- **Instructions and skills:** in full (the twin skill itself is left out).
- **Memory:** everything the bot remembers, except what you told it to keep private. Unlike the Twins page,
  this route does copy memory: into the twin's own Hermes memory, as much as Hermes allows; the PASS line says
  how many did not fit.
- **Routines:** copied switched off. Only "Move yourself to Hermes" switches them on.
- **Recent conversations:** in practice only your last few, trimmed: the skill keeps them under 8,000 characters,
  newest first, so the command stays short enough for the Grok app. If the PASS line has no "Conversations:"
  part, none were copied. Each becomes a Hermes chat named "From Grok: …";
  sending one again adds only its new messages. For a full archive, use
  [whole conversations](GUIDE.md#a-twins-whole-conversations-archive-and-search) instead.
- **API keys** in a skill or memory: the bot passes them as they are, so they appear in the command in that Grok
  chat (and in the approval box, if you see one). On your computer they are then kept in your OS secret store,
  and the twin gets a placeholder ([SECRETS.md](SECRETS.md)).

"Come back to Grok" runs `hermes twin back-to-grok` the same way.

## What a run does

1. Finds the bot's twin by name, or makes one (as `hermes twin add` does) and makes it bot-driven. The Grok bot
   must be in the Grok app on this computer. A twin that still follows the bot through botport is left as it is:
   FAIL, nothing written ([bot-driven twins](#before-you-start)).
2. Takes a snapshot of the twin's Hermes files first (the last 3 are kept).
3. Writes the bot's instructions, skills and memory into the twin, and adds its routines switched off.
4. Checks the result: the twin must match what the bot sent, the **behaviour test** must pass, and no written
   file may look like it holds a password or key. The behaviour test is botport's: a handful of short chats with
   the twin's model, made from the bot's instructions. Each is a real model call, so it costs what your model
   costs and takes some seconds.
5. On any FAIL, puts the snapshot back (see [If it says FAIL](#if-it-says-fail) for the exceptions).

One run per bot at a time. Every run is logged (when, which bot, PASS or FAIL, counts; never the texts).

## If it says FAIL

The snapshot is put back, and saying the same prompt again is safe. Three exceptions:

- **A first run** leaves the twin it made itself: an empty, bot-driven Hermes bot. `hermes twin stop "NAME"` removes it if you do not want it.
- "could NOT be put back by itself" in the line: run `hermes twin doctor`.
- A move FAIL that lists Grok routines still paused: the bot switches them back on; if it did not, do it in Grok.

**Most common**

| What you see | What to do |
|---|---|
| `hermes` not found, or `twin from-grok` not found | `hermes`: it is not on the login shell's PATH, see [Before you start](#before-you-start). `twin from-grok`: the plugin is missing, off or older than 0.4 ([README](../README.md#install)). |
| The bot ran nothing, says it has no such tool, or Grok says the command is too long | Check step 2 of [setup](#set-it-up-once-per-bot). A too-long command means the bot's skills and memory are very large: shorten them in Grok, or use the [Twins page](GUIDE.md#connect-your-grok-bots). |
| behaviour test 3/5 | Every test case must pass; one miss is a FAIL. The twin's model answered some test questions differently from what the bot's instructions expect. `hermes twin test "NAME"` shows which case and why; a more capable model helps, or clearer, shorter instructions in Grok (a one-prompt run makes its test questions from the bot itself). Check the twin has a working model (`hermes twin status`), then say the prompt again. |
| no Grok bot of that name is in the Grok app on this computer | The Mac's Grok app does not list this bot: check its name was not just changed, that the botport line of `hermes twin setup --check` is ✓, and, with several Grok accounts, the `grok_account` setting ([GUIDE](GUIDE.md#settings)). |
| conflict(s): edited in both Hermes and Grok | A skill or the instructions changed in both places since the last run. Make the two the same (undo the Hermes edit, or make it in Grok too), then say the prompt again. |
| The command ran on "Grok Bot's computer" | It must run on yours: the bot used its cloud computer. Say "on my local computer" in the prompt, and check the skill is added. |

**Others**

| What you see | What to do |
|---|---|
| the input is not one JSON object (or it is too large) | The bot built the command wrong. Say the prompt again; if it repeats, check the skill was added whole (all three fields). |
| the bot's name in the JSON is not the one after --bot | The bot wrote its name two ways. Say the prompt again; if it repeats, check the bot's name in Grok has no unusual characters. |
| bot_name must be the bot's own name | The same: the name was empty or held characters the plugin does not take. |
| each skill needs a name and its text | One of the bot's skills is empty in Grok: give it a text, or delete it. |
| the call is larger than … characters | The bot's text is far too large for one command; use the Twins page. |
| this bot has no Hermes twin to come back from | Nothing was moved yet: say "Clone yourself to Hermes" first. |
| this twin has no Hermes bot of its own | Its Hermes bot was deleted. Stop twinning it (`hermes twin stop "NAME"`) and clone it again. |
| this twin's memory file cannot be read safely | Run `hermes twin doctor`; the memory file in the twin's Hermes folder needs a look. |
| Hermes refused to turn on routine(s) / could not pause routine(s) | Check `hermes cron status`, then say the prompt again. Nothing moved. |
| more than one Grok bot (or twin) has that name | Rename one in Grok, or see `hermes twin status`. |
| does not match what the Grok bot sent (botport drift) | The twin's files did not end up as the bot sent them. Say the prompt again; if it repeats, run `hermes twin doctor`. |
| written file(s) look like they hold a password or key | A text the bot sent holds something the check takes for a password. Remove it in Grok, then try again. |
| routine(s) could not be added | A routine's schedule or prompt was not accepted by Hermes. Check the routine in Grok. |
| Hermes is writing this twin's memory right now | Try again in a moment. |
| move needs every Grok routine paused first | The bot did not pause all its routines. Say "Move yourself to Hermes" again. |
| Hermes could not make the twin | Run `hermes twin doctor`. |
| this twin is the sample | The sample cannot be used here; twin a real bot. |
| a twin run for this bot is already going | Wait for it to finish, then try again. |
| these routines could not be paused in Grok, so nothing moved | Grok would not let the bot pause them. Nothing moved; the bot switched back on the ones it paused. |
| this twin follows its Grok bot through botport, so nothing was changed | A twin made on the Twins page. Run `hermes twin bot-driven "NAME"` in your own terminal and type yes ([Before you start](#before-you-start)), then say the prompt again. |
| botport still keeps this twin's Hermes bot to itself | The one-time switch to a bot-driven twin did not finish. Run `hermes twin doctor` and follow what it says. |
| the answer looked like it held a password or key | Remove the password from the bot's instructions or memory in Grok, then try again. |

`hermes twin status` shows each twin's last result ("Kept in step by the bot · last synced …, PASS").

## Undo or stop

- **A PASS you do not like:** fix the bot in Grok and say the prompt again; the twin follows. The plugin's
  snapshots (the last 3) are only for its own rollback on FAIL. With [git history](#optional-git-history) on,
  get an earlier text back like this, then paste it into the bot in Grok and say the prompt again:

      git -C ~/.hermes/plugin-data/grok-bot-twin/git/<folder> log --oneline
      git -C ~/.hermes/plugin-data/grok-bot-twin/git/<folder> show <commit>:instructions.md > old-instructions.md

- **What a PASS changes:** the twin's instructions and skills become the bot's; memory and routines are only
  added to, never removed. An edit you made only in Hermes may be replaced by the bot's version at the next
  prompt: to keep it, make the same change in the bot in Grok first.
- **Stop twinning a bot:** `hermes twin stop "Acme Support" --dry-run` shows what would happen; run it without
  `--dry-run` to do it. Its Hermes bot and chats stay. The git history folder and keys in your secret store stay
  too (`hermes twin git off "Acme Support"`, `hermes twin secret forget NAME`). In Grok, delete the bot's
  `twin-to-hermes` skill so a later prompt does not make the twin again, and set Execution on Local Computer
  back to Ask every time if you no longer need it.
- **Moved and want to go back:** say "Come back to Grok".

## Safety

**What Always allow means.** It is a Grok app setting, not part of this plugin. With Always allow, every bot in
the app can run **any** command on your computer, as you, without asking, not only `hermes twin from-grok`. A bot's model
could be steered by text it reads (a web page, a file). Choose Always allow only if you trust every bot in the
app with your computer; otherwise keep Ask every time and press Allow once for each command.

What the plugin itself does to limit a run:

- It takes two calls only (`from-grok`, `back-to-grok`). There are no delete, stop or path arguments; anything
  not in the expected JSON is refused.
- It writes only to that bot's own twin, never to your `default` Hermes profile.
- `--bot NAME` is written by the bot itself in this route, so it does not stop one bot from naming another.
  What it does is refuse JSON that names a different bot than `--bot`.
- Every text goes through the plugin's password and key check first.
- Size limits on every part; one run per bot at a time; a snapshot first and a rollback on any FAIL.

## Optional git history

Off by default; nobody needs git. Switch it on to get a history of a twin you can browse, or push to your own
git server (Forgejo, Gitea, GitHub, …). The Twins page has the same switch and remote field in a twin's
details; in a terminal:

    hermes twin git on "Acme Support"                       # or --all (without --remote)
    hermes twin git on "Acme Support" --remote git@forgejo.example:me/acme-support.git
    hermes twin git status                                  # which twins are on, and their folders
    hermes twin git off "Acme Support"

- `--all` also covers twins you make later. `--remote` is per twin (one repository each), so it is refused with
  `--all`. **With a remote from the start:** `hermes twin git on --all`, then the first "Clone yourself to
  Hermes", then `hermes twin git on "Acme Support" --remote URL`; the commits so far are pushed at the next PASS, even when nothing changed. A failed push is tried again at each PASS. Give `--with-history` again with `--remote` if you want chat history: a twin's own setting replaces the `--all` one.
- Only one-prompt runs commit. The switch on the Twins page does nothing for a twin that is not bot-driven.
- After every PASS of a **one-prompt** run, the bot's instructions (`instructions.md`), skills, memory and
  routines are written to one repository per twin in your Hermes folder (usually `~/.hermes`), under
  `plugin-data/grok-bot-twin/git/`, one folder per twin named by its short name (`acme-support`). They are committed, with a message such as `PASS sync from Grok: 2 skills changed`. Nothing changed means no commit.
  Changes made on the Twins page are not committed, so a twin that is not bot-driven gets no history. Each
  repository holds `instructions.md`, `skills/`, `memory/`, `routines/` and, with `--with-history`, `history/`.
- **Pushing, first time:**
  1. Create an empty repository on your server.
  2. Sign in once by hand, because the plugin's push never asks. An address with a password or token in it is
     refused.
     - SSH address: run `ssh -T git@forgejo.example` once and accept the host key. The key must load without a
       prompt, also after a restart: on a Mac, run `ssh-add --apple-use-keychain ~/.ssh/id_ed25519` once and put
       `Host *`, `  AddKeysToAgent yes`, `  UseKeychain yes` in `~/.ssh/config`. A server on another port:
       `ssh://git@forgejo.example:2222/me/acme-support.git`.
     - HTTPS address: make an access token on your server (not your password). On a Mac, run
       `git config --global credential.helper osxkeychain`, then `git ls-remote https://forgejo.example/me/acme-support.git`
       once and give your user name and the token; git keeps them.
  3. The plugin then pushes to `main` after each commit. A failed push is a `Warning:` on the PASS line, never a
     FAIL; the git section of the twin's details on the Twins page shows the last commit and push.
- Everything goes through the plugin's secret check first; a file that still looks like a key is left out.
  Chat history is left out unless you add `--with-history`; with a remote, that sends your chats to that server.
- **With `--remote`, the twin's memory (what the bot knows about you) is pushed too.** Use a private repository
  on a server you control.
- No git installed: the PASS line says so; the sync itself still passes.
- Commits are authored as "Grok Bot Twin <twin@localhost>".
- To look at the history: `ls ~/.hermes/plugin-data/grok-bot-twin/git/`, then
  `git -C ~/.hermes/plugin-data/grok-bot-twin/git/<folder> log --stat`.

## For developers

`hermes twin mcp --bot NAME` serves the same two calls as a local MCP server (JSON-RPC on stdin/stdout). The
Grok app does not run connectors on your computer today, so it is not used yet. On that route the owner writes
the command line, so `--bot` (with `GROK_BOT_TWIN_CALLER` when several bots share one server) does bind the
connector to one bot. Internals of the bot-driven conversion are in [DISCLOSURE.md](DISCLOSURE.md).
