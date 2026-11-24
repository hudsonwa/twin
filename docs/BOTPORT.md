# How Grok Bot Twin and botport fit together

```
 Grok desktop app (Mac)          your computer                         Hermes
 ┌──────────────┐   one prompt   ┌───────────────────────────────┐     ┌──────────────┐
 │ your Grok bot│ ─────────────▶ │ hermes twin (this plugin)     │ ──▶ │ the bot's    │
 └──────────────┘                │   └─ runs botport (the engine)│     │ Hermes twin  │
                                 └───────────────────────────────┘     └──────────────┘
```

- **Grok Bot Twin** (this repo) is the Hermes plugin: the Twins page, the `hermes twin` commands, the one prompt,
  Hermes tools, git history and secrets by reference. It is what you install.
- **[botport](https://github.com/hudsonwa/botport)** is the engine underneath: it reads what the Grok bot sent,
  writes it into the twin's Hermes profile, checks both sides match (`drift`), runs the behaviour test, and brings
  chat history across. It is a separate open-source program (MIT) so other tools can use it too.

## Do I need Rust?
No. `hermes twin setup` downloads a ready-made botport from its GitHub release and checks it against the
fingerprints this plugin version ships with before it ever runs it. Ready-made copies exist for Mac (Apple Silicon
and Intel) and Linux (ARM and x86). Rust is only needed if you want to build botport yourself.

## Which versions go together
Each plugin version accepts exactly the botport release it was tested with (listed in `twin/botport_pins.json`):

| Grok Bot Twin | botport |
|---|---|
| 0.5.7 (this version) | 0.3.5 |
| 0.5.6 | 0.3.5 |
| 0.5.5 | 0.3.5 |
| 0.5.4 | 0.3.5 |
| 0.5.3 | 0.3.5 |
| 0.5.2 | 0.3.4 |
| 0.5.0, 0.5.1 | 0.3.3 |
| 0.4.x | 0.2.1 |

The zero-touch parts, `hermes twin setup --auto`, `hermes twin from-hermes` and chat sync's pull, need
**botport 0.3.0 or newer** (the Grok engine, `botport grok`); this version pins 0.3.5. If you choose an older
release with `botport_release_tag`, `setup --auto` and `from-hermes` FAIL with "needs botport 0.3.0 or newer (the
Grok engine); the botport_release_tag setting chooses 0.2.1" (or the release you chose). (For maintainers: one
step pins a release: `python3 tools/pin_botport.py --tag vX.Y.Z`.)

`hermes twin setup --check` shows the botport it found and whether it is the right one. Updating the plugin tells
you when botport needs updating too; setup fetches it the same way.

## Other computers
Computers that only hold copies of your twins (Mac, Linux or Windows) need no botport and no Grok app.
