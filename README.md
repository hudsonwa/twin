# Grok Bot Twin

**Try Hermes without leaving Grok. Move over when your twin is ready.**

A plugin for [Hermes Agent](https://github.com/NousResearch/hermes-agent) by Nous Research, an open-source agent
that runs on your own computer with the model you choose. It gives each bot
you built in the Grok desktop app a **twin**: a Hermes bot that follows it. Your Grok bot keeps working as
before. When you are happy with the twin, move the bot's scheduled prompts (its *routines*) to Hermes. Change
your mind, and bring it back. New words: [Words used](docs/GUIDE.md#words-used).

**Who it is for:** people with bots in the Grok desktop app who want to try Hermes without giving them up.
Just moving once? Hermes' own `hermes migrate grok-bot` does a one-time import. Unofficial; not affiliated with xAI.

![The Twins page: one line per twin, and one button only when something needs you](docs/screenshots/twins-page.png)

## You need

- **Hermes 0.22.7 or newer**, with a model that works. Hermes Desktop is optional: everything also works in a terminal.
  Check with `hermes --version`; `hermes update` brings it up to date.
- **A Mac with the Grok desktop app** (called Grok Bot, 1.0.1 or newer), signed in. Your other computers (Mac, Linux, Windows) can hold copies of
  the twins, but only the Mac reads Grok.
- **git**, for the install line.
- **[botport](https://github.com/hudsonwa/botport)** (free, same author): the engine that does the copying. Setup
  downloads a ready-made, checked copy for you; **no Rust needed**. How they fit: [docs/BOTPORT.md](docs/BOTPORT.md).
- **Costs:** each one prompt is one Grok turn (your Grok plan's usage) plus a few short test chats on your Hermes
  model; skill sync uses Grok on every run. **Time:** about 10 minutes ([Quickstart](docs/QUICKSTART.md)).

## Install

**Do not use the Plugins button yet.** It, and the catalog name `grok-bot-twin`, give the older catalog version
of the plugin (plugin 0.2.1). For this version, paste this line in a terminal (it installs the newest release,
from the `next` branch):

```sh
hermes plugins install hudsonwa/twin --ref "$(git ls-remote https://github.com/hudsonwa/twin refs/heads/next | cut -f1)" --enable
```
In Windows PowerShell:
```powershell
hermes plugins install hudsonwa/twin --ref ((git ls-remote https://github.com/hudsonwa/twin refs/heads/next) -split '\s+')[0] --enable
```

- Hermes warns "custom (unreviewed) source". That is expected: it is not the catalog. `--ref` needs a full
  40-character commit; the `git ls-remote` part looks up the newest one.
- **Already have plugin 0.2.1, or updating later:** run the same line with `--force` added. If Hermes refuses,
  run `hermes plugins remove grok-bot-twin` first (your twins and data stay), then the line again.
- Hermes Desktop: **Capabilities → Plugins** → turn **Grok Bot Twin** on (and its Twins-page switch, if shown).
- **On your other computers:** the same line; they need no Grok app and no botport ([SHARING.md](docs/SHARING.md)).
- **Check it worked:** `hermes twin setup --check`; its first lines say the plugin is on. An error such as
  `'twin' is not a` means it is off ([Troubleshooting](docs/GUIDE.md#troubleshooting)).

## Your first twin

**1. Try the sample (2 minutes, nothing of yours touched).** Open **Twins** in the Hermes Desktop sidebar and
press **See a sample first**, then **Change the bot in Grok** and watch the twin follow. In a terminal:
`hermes twin demo`, `hermes twin demo grok-edit`, then `hermes twin check`. **End sample** removes it.

**2. Twin a real bot.** Our recommendation: **one prompt in Grok** if you want everything (memory and skills
included) or plan to move the bot; **the Twins page** if you only want a twin that follows the bot while it stays
in Grok. Both are below; the table says how they differ.

| | **One prompt in Grok** | **The Twins page** |
|---|---|---|
| What comes over | Instructions, skills, memory, routines (off), recent conversations | Name, description; instructions and routines from a setup export |
| Keeps in step | Each time you say the prompt | Name and description in seconds, by itself |
| Bot size | Up to about 6 KB of instructions, skills and memory (a long command is refused by Grok) | Any |
| Grok usage | Each prompt is a Grok turn. From Hermes (`from-hermes`), an unchanged bot is skipped at 0 turns. Chat sync by pull (default) costs none; by routine one turn per run, at most hourly (about 168 a week) | None, unless you set up optional skill sync, whose sync bot spends Grok credit |
| State | Experimental (new) | Ready ([what that means](docs/GUIDE.md#ready-or-experimental)) |

> **Pick one per bot.** The first one-prompt run makes that bot's twin *bot-driven* for good
> ([what that means](docs/ONE-PROMPT.md#before-you-start)). A bot you already twinned on the Twins page needs
> one step of yours first, in your own terminal: `hermes twin bot-driven "Acme Support"`, then type yes.
> Coming back to Grok, the bot gets Hermes-side memory and skills only when you allowed Hermes → Grok for that twin.

**One prompt** (full steps: [ONE-PROMPT.md](docs/ONE-PROMPT.md#set-it-up-once-per-bot)):

1. Terminal: `hermes twin setup`, download botport when it asks, then run `hermes twin setup` again and answer yes.
   `hermes twin setup --check` then shows botport with ✓; "No twins yet" is expected (the prompt makes the twin).
2. Grok app: open the bot, **Skills** tab → **Add new skill**. Run `hermes twin skill-text --name` (add `| pbcopy`
   to copy it) and paste into Name; the same with `--description` into Description, `--body` into the large box.
   **Save skill**. Also check `zsh -lc 'command -v hermes'` prints a path ([if not](docs/ONE-PROMPT.md#before-you-start)).
3. Grok app: **Settings → Bot → Execution on Local Computer**. For the first prompt keep **Ask every time** and
   press **Allow once** only if the command is the bot's own `from-grok` line and its JSON, nothing else
   ([exactly what to check](docs/ONE-PROMPT.md#set-it-up-once-per-bot)).
   If you trust every bot in your Grok app with this computer, then switch to **Always allow**: no click per
   prompt, but any bot may run any command ([Safety](docs/ONE-PROMPT.md#safety)).
4. In the bot's chat: "Clone yourself to Hermes". It answers with a line such as
   `PASS: Acme Support twinned to Hermes (profile acme-support): 3 skills, 12 memories, ...`. Or from Hermes, experimental: `hermes twin from-hermes "Acme Support"` (or `--all`, or "twin all my Grok bots" in a Hermes chat) asks the bot for its own export through botport's Grok engine, with no skill, no local command and no approval (steps 2 and 3 are then not needed), checks it, imports it and sets up [chat sync](docs/ONE-PROMPT.md#from-hermes-and-chat-sync); it needs botport 0.3.0 or newer (the Grok engine), which this plugin version pins (Grok Bot Twin 0.5.5 ↔ botport 0.3.5; see [docs/BOTPORT.md](docs/BOTPORT.md#which-versions-go-together)).

**The Twins page** (full steps: [GUIDE.md](docs/GUIDE.md#connect-your-grok-bots)):

1. Hermes Desktop → **Twins** → **Connect my Grok bots**; download botport when it asks.
2. Choose your bots → **Twin this bot**.
3. Paste each bot's instructions (or drop its setup export) and choose a model. (Steps 1 and 2 can also be
   one line in a Hermes chat, "twin my Acme Support bot"; the instructions still come from step 3.)

**3. Check it.** `hermes twin` prints your twins and the one next step. **Open in Hermes** on the Twins page
starts a chat with the twin. Something wrong? [Troubleshooting](docs/GUIDE.md#troubleshooting).

## What copies over, honestly

This table is for the Twins page. The one prompt copies more: memory and recent conversations
([what it sends](docs/ONE-PROMPT.md#what-the-bot-sends)). The same table is in **Details…** and `hermes twin copies`.

<details>
<summary>The whole table, for twins kept by the Twins page</summary>

<!-- what-copies:begin (written by twin/copies.py: change the table there) -->

| What | How |
|---|---|
| **From Grok to Hermes** | |
| Name and description | By itself, in seconds, while Hermes is open. |
| Instructions, routines and connections | With Import setup export: the bot writes a file about itself when you ask it in Grok. Instructions are filled in, routines arrive switched off, and connections arrive as a list of names. Logins are never copied. With skill sync set up, instructions also follow Grok's every 15 minutes by themselves, unless you switch that off. When it is unsure which to keep, you are asked. |
| Skills | With skill sync, which is optional: a sync bot in your own Grok account carries them. Without it you copy them yourself. |
| Conversations | Off until you switch full transcripts on for a twin. Then conversations from a Grok export can become Hermes chats of the twin; full transcripts are set up in the terminal. |
| Grok memory | Does not copy: memory is the most private thing a bot holds, so none is taken unless you ask the bot itself with the one prompt. |
| Grok model setting | Does not copy: nothing Hermes reads from Grok names the bot's model, so the twin uses the model you choose in Hermes. |
| **From Hermes back to Grok** | |
| Name, description and instructions | Off for every twin until you allow it. Then, with skill sync set up, you see a preview of each change and apply it. A bot in your own Grok account makes it there, and you can undo it. Otherwise you make the same change in Grok yourself. |
| Skills | With skill sync, after you press Send to Grok: a skill Grok does not have yet is installed there. A skill Grok already has under that name is not replaced; paste the change into Grok yourself. Without skill sync you paste them all yourself. |
| Routines and connections | Routines go like the name, once you allow them for a twin. Each routine runs in one place that you choose, never in both. Connections you change in Grok yourself. |
| **Between your own computers** | |
| Name and description | By itself, in seconds, once the other computer is linked and Hermes is open on both. |
| Skills | Off until you switch it on. Then the text of each twin's skills follows the Mac with the Grok app. A skill changed on both computers asks you which one to keep. |
| Routines | Off until you switch it on. Then each twin's routines copy to every linked computer, and each routine runs on one computer that you choose, never on two. |
| Memory | Off until you switch it on for a twin. Then it travels encrypted, between your linked computers only. |
| Settings | By itself, item by item: tools, preferences and instructions follow the Mac with the Grok app. Each computer keeps its own model unless you switch that on. |
| Instructions | By itself, as one of the twin's settings. You can switch that off on each computer. |
| Chats, files and logins | Not copied. A request you send to another computer and its answer are the only chat text that travels, and only with requests switched on. |

<!-- what-copies:end -->

</details>

## More

[Quickstart](docs/QUICKSTART.md) · [One prompt](docs/ONE-PROMPT.md) · [Guide](docs/GUIDE.md) (Twins page, settings, troubleshooting, uninstall, words
used) · [Other computers](docs/SHARING.md) · [Every command](docs/TERMINAL.md) · [API keys](docs/SECRETS.md) · [Roadmap](docs/ROADMAP.md) · [Changelog](CHANGELOG.md) · [For coding agents](AGENTS.md)

## Disclosure

Everything the plugin reads, writes, runs or sends is in [docs/DISCLOSURE.md](docs/DISCLOSURE.md).

## Credits

[botport](https://github.com/hudsonwa/botport) (MIT), the sync engine this plugin runs.

## License

MIT, see [LICENSE](LICENSE).
