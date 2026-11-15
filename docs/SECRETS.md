# Secrets by reference

A twin has to keep working when a bot's skills, instructions or memory need an API key. The key itself must never
travel: not in an export, a bundle, a git commit, a log, a chat or an answer of a tool, and never to Grok's cloud
unless the owner says so for that one key.

## The idea

The plugin's one secret check (`twin/secrets.py`) already finds things that look like keys. Before, a found value
was blanked (the line was hidden, or the fact left out) and the twin lost it. Now, when this computer has an OS
secret store, the value is **kept by reference**:

1. The value goes into the OS secret store on this computer, under a NAME, as service `grok-bot-twin`.
2. The text keeps a stable placeholder in its place: `{{secret:NAME}}`.
3. A list of names (`plugin-data/grok-bot-twin/secrets.json`) says where each name is used and which switches are on.
   It never holds a value.

The NAME comes from the text when it names the value (`OPENAI_API_KEY=…` → `OPENAI_API_KEY`, `api_key: "…"` →
`API_KEY`), else from what the check found (`GITHUB_TOKEN`, `AWS_KEY`, `PRIVATE_KEY`…). The same value always gets
the same name; a different value under a name that is taken gets `NAME_2`, `NAME_3`…

What the check finds but cannot cut out cleanly (a password said in words, a card or account number, a signed
link) is still hidden as before. Those are not keys a skill needs.

## The OS secret store

| System | Store | How the plugin talks to it |
|---|---|---|
| macOS | Keychain (login keychain) | `/usr/bin/security -i`, the command on **stdin** (value hex-encoded with `-X`), never in argv |
| Linux | Secret Service (GNOME Keyring, KWallet) | `secret-tool store`, the value on **stdin**; `secret-tool lookup` / `clear` |
| Windows | Credential Manager | `CredWriteW` / `CredReadW` / `CredDeleteW` from `advapi32` through `ctypes`, no subprocess at all |

Hermes has `keyring` only as an optional extra (`hermes-agent[keychain]`), so the plugin does not depend on it.
Every call is a list of arguments (no shell) with a minimal environment and a time limit; a value is never on a
command line, where other users of the computer could see it with `ps`.

**No store, no keeping.** When none of the three is there (a Linux server without a Secret Service, a locked
keyring, a sandbox), the plugin refuses to keep the value and says so: the text is blanked exactly as before and
the answer says `kept by reference: 0 (no OS secret store on this computer: …)`. There is no fallback to a file.

## Grok → Hermes

When text from the Grok bot holds a key, the key goes to the store and the Hermes bot gets it the way Hermes
keeps every provider and connector key: as a line in the **profile's own `.env`**
(`~/.hermes/profiles/<twin>/.env`, mode 0600, same `KEY=value` form Hermes' `save_env_value` writes). The text the
Hermes bot reads (SOUL.md, skills, memory) says `${NAME}`: the name of the environment variable Hermes loads from
that `.env`. A value is never written in plain text into SOUL.md, a skill or memory.

It is done on `hermes twin sync` (`sync_both.py`, both ways) and on the one-prompt route (`hermes twin from-grok`
and `back-to-grok`, `one_prompt.py`). On the one-prompt route the bot's words are screened with the twin's
references once the twin is known; the profile's `.env` gets the values only when the call PASSes (a FAIL leaves
them in the OS store only, and no snapshot ever holds one). The answer names the keys it kept ("1 key(s) kept by
reference (OPENAI_API_KEY)"), never a value; `back-to-grok` passes `secrets_needed` on to the bot. The bot's skill (`grok/SKILL-twin.md`) tells it to
pass an API key or token a skill needs as it is (it only travels to the owner's own computer, in the one command
the owner approves) and to leave out sign-in passwords, cookies and logins. The other paths
(the Mirror bot's `to-grok`, finish) keep the older policy, hold back or blank, until they are moved over.

## Hermes → Grok

What goes to the Grok bot (`for-grok.json`, the CLI output, the Mirror bot's bundle) carries only placeholders and
names. A Grok connector signs in with Grok's own auth, so the bundle tells the bot which NAME to set up there:
`"secrets_needed": ["OPENAI_API_KEY"]` with the sentence "Set these up in Grok's own connector or secret settings;
this bundle holds only their names."

**The one way a value reaches the bot:** the owner runs, in their own terminal,

    hermes twin secret share NAME --to-grok

which warns that the value will then live on xAI's service, asks once (`--yes` for scripts), and marks that one
name. Only then does the next bundle carry that value in place of its placeholder. `--off` turns it back.
A command a chat started (the MCP tools, the slash command) cannot turn it on.

## The owner's other computers

Off by default, per secret: `hermes twin secret share NAME --linked` on the computer that shares. A linked
computer fetches the values marked so with `hermes twin secret pull`, over the link it already has, on a route of
its own (`POST /v1/xs/secrets`), signed and counted like every call, inside the same sealed box as a twin's memory
(`xs_memory.seal`), with a key of its own made from the link's key. It keeps each value in its own OS store and
refuses when it has none. Nothing of a value is logged.

## Commands

| Command | What it does |
|---|---|
| `hermes twin secret list` | Names, where each is used, which switches are on. Never a value. |
| `hermes twin secret set NAME` | Asks for the value without echo (or reads one line from stdin with `--stdin`) and keeps it in the store. |
| `hermes twin secret forget NAME` | Takes it out of the store, the list and every twin's `.env`. |
| `hermes twin secret share NAME --to-grok [--off] [--yes]` | The per-secret opt-in described above. |
| `hermes twin secret share NAME --linked [--off]` | Lets linked computers fetch it. |
| `hermes twin secret pull` | On a linked computer: fetch what the sharing computer allows. |

## Threat model

- **Prompt injection asking for a value.** No tool, MCP call, slash command or API route returns a value. `list`
  prints names; the resolve step writes only into a profile's `.env`. A model that is told "print the key" has
  nothing to print it with. The opt-ins refuse a command a chat started.
- **Logs.** Values pass only through the store calls; their errors are reported by code ("store said no"), never
  with the subprocess' text, which could echo input. Events count names, not values.
- **Git mirror.** The mirror commits scrubbed text; placeholders are plain names, and the mirror's own scrub still
  runs after them. The `.env` is never a mirrored file.
- **Crash dumps and tracebacks.** A value lives in a local variable for the length of one call and is never put
  in an exception's message. The `.env` is the same file Hermes already keeps keys in.
- **A hostile bot on a shared connector.** A Grok bot can put `{{secret:NAME}}` into its own text hoping the
  Hermes side fills it in. It cannot: placeholders are resolved only into `.env` lines (never back into text),
  and only for names that this computer's list ties to that twin. A placeholder for any other name stays text.
  Hermes → Grok never resolves a placeholder except for names the owner shared `--to-grok` themselves.
- **Other users of the computer.** Values never appear in argv; the `.env` is 0600; the store is the owner's.
- **What this does not cover.** A value the check does not recognise is not a secret to it (the check can miss
  things). A value the owner shared to Grok lives on xAI's service under their terms. The OS store is as safe as
  the owner's login.
