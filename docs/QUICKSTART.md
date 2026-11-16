# Quickstart: from nothing to a first twin

Five steps in a terminal. Steps 1 to 3 work on any Mac or Linux computer and need no Grok app, no model key and
no account: on a fresh Linux computer they took about 2½ minutes, nearly all of it the Hermes install. Steps 4
and 5 make a twin of one of your own bots and need two things this page cannot give you:

- **the Grok desktop app** (Grok Bot), signed in, on this Mac, with at least one bot;
- **a model for Hermes**: an API key or account with a provider (step 4 sets it up). The twin chats with it.

Windows, the Twins page and every other route: the [README](../README.md#your-first-twin).

## 1. Install Hermes (about 2 minutes)

Skip this if `hermes --version` prints 0.22.7 or newer. Otherwise:

```sh
curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash
```

It ends with `Hermes Agent install complete`. If it prints nothing at all, the download was refused (the site
limits how often one computer fetches it): wait a minute and run it again.
Then **open a new terminal** (the installer added `hermes` to your PATH there) and check: `hermes --version`.
The installer may walk you through choosing a model; you can skip that until step 4.

## 2. Install the plugin (10 seconds)

```sh
hermes plugins install hudsonwa/twin --ref "$(git ls-remote https://github.com/hudsonwa/twin refs/heads/next | cut -f1)" --enable
```

Hermes warns "custom (unreviewed) source": expected, this is not its catalog. Check: `hermes twin setup --check`.
Its second line is `✓ Grok Bot Twin is installed and switched on in Hermes.` (The lines after it say what this
computer still needs; on a computer without the Grok app it suggests a link, which you do not need now.)

## 3. Try the sample (10 seconds, nothing of yours touched)

```sh
hermes twin demo             # "Sample twin ready." Acme Support, an invented bot
hermes twin demo grok-edit   # changes the sample bot in "Grok"
hermes twin check            # "Acme Support: updated description": the twin followed
hermes twin demo remove      # "Sample removed. Nothing of yours was changed."
```

That is the whole idea: the bot stays in Grok, the twin in Hermes follows it. More of the tour:
[TERMINAL.md](TERMINAL.md#the-sample-tour).

## 4. Choose a model (needs your key)

```sh
hermes model
```

Pick a provider and paste its key or sign in. Your twins use this model unless you choose another per twin.

## 5. Twin a real bot (needs the Grok app on this Mac)

```sh
hermes twin setup                     # says where to download botport (the free copying engine) in your browser
hermes twin setup --file ~/Downloads/botport-aarch64-apple-darwin.tar.gz   # the file you downloaded; answer yes
hermes twin from-hermes "Acme Support"  # your bot's name as Grok shows it (experimental)
hermes twin                           # your twins and the one next step
```

`from-hermes` asks the bot in Grok for its own export (one Grok turn of your plan's usage), checks it and makes
the twin. It ends with one line: `PASS: Acme Support twinned to Hermes (profile acme-support): ...`. Chat with the
twin: `hermes -p acme-support`.

Do step 4 before this step. A `from-hermes` run before a model is chosen leaves the twin on Hermes' template
model (a placeholder from Hermes' example config, not yours), and running `from-hermes` again does not change it.
If that happened, give the twin your model: `hermes twin finish acme-support --model MODEL --endpoint HOST:PORT --yes`
(`--endpoint` only for your own model server), then `hermes twin check-model acme-support`.

A FAIL line says what to do instead; usually it is the one prompt in the bot's own chat, "Clone yourself to
Hermes", set up once per bot as in [ONE-PROMPT.md](ONE-PROMPT.md#set-it-up-once-per-bot). On a computer
without the Grok app, `from-hermes` stops at once and downloads nothing.

## Where this was checked

Steps 1 to 3 were followed literally, twice, on a fresh Linux computer with an empty home folder (Hermes
0.23.1): Hermes install 123 and 144 s, plugin 6 and 11 s, sample 3 to 5 s; 2 min 38 s in all.
Steps 4 and 5 were checked only up to the point where a model key or the Grok app is needed (there was
neither): `hermes model` is there, and `from-hermes` without the Grok app gives the FAIL above.
Something else went wrong? [Troubleshooting](GUIDE.md#troubleshooting).
