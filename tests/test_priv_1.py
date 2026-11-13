"""PRIV-1: a coding agent does not print the owner's bot names or instructions into its chat.

AGENTS.md hands `hermes twin finish` and `hermes twin import-exports` (they print every twin's name, and
`--show` every bot's instructions and routine prompts) to the owner's own terminal, names them among the
commands that print names, and the disclosure says what a coding agent's commands put before its model.
"""
import re
from pathlib import Path

from twin_testlib import cli

ROOT = Path(__file__).resolve().parents[1]
NAMING = ("finish", "import-exports")


def _flat(path):
    return " ".join((ROOT / path).read_text(encoding="utf-8").split())


def _step(flat, n):
    return flat.split(f"{n}. **", 1)[1].split(f"{n + 1}. **" if n < 8 else "### A second computer", 1)[0]


def test_PRIV_1_agents_md_step_8_hands_finish_and_import_exports_to_the_owner():
    step8 = _step(_flat("AGENTS.md"), 8)
    assert "two commands to run in their own terminal; do not run them yourself, because they print bot names " \
           "and instructions" in step8
    assert "you may help" not in step8
    for sentence in re.split(r"(?<=[.;:])\s", step8):
        for cmd in NAMING:
            if f"hermes twin {cmd}" in sentence:
                # every mention is of what the owner runs, never an instruction to the agent to run it
                assert not re.search(r"\b(you|agent) (run|runs|may run)\b", sentence), sentence
    assert "Never paste into Grok yourself." in step8


def test_PRIV_1_the_rule_against_listing_bots_names_finish_and_import_exports():
    flat = _flat("AGENTS.md")
    rule = flat.split("**Do not list your owner's bots.**", 1)[1].split("- **", 1)[0]
    for cmd in ("hermes twin list-grok", "hermes twin fleet", "hermes twin finish", "hermes twin import-exports DIR"):
        assert f"`{cmd}`" in rule, cmd
    assert "run them only when your owner asks you to" in rule


def test_PRIV_1_disclosure_says_what_a_coding_agents_commands_put_before_its_model():
    flat = _flat("docs/DISCLOSURE.md")
    part = flat.split("## What reaches the model", 1)[1].split(" ## ", 1)[0]
    bullet = part.split("- A coding agent", 1)[1].split(" - ", 1)[0]
    assert "`hermes twin setup`" in bullet and "prints no bot name it did not type" in bullet
    assert "reaches that agent's model provider" in bullet and "left to your own terminal" in bullet
    named = re.findall(r"`hermes twin ?([a-z-]*)`", bullet)
    assert set(NAMING) | {"list-grok", "fleet", "setup", ""} <= set(named)
    takes = cli.build_parser()._subparsers._group_actions[0].choices
    for sub in named:
        if sub:  # every command it names is one `hermes twin` takes
            assert sub in takes, sub
