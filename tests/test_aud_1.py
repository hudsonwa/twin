"""AUD-1: an example SSH git address (a user, an at sign, a host under .example, a colon and a path) reads as
an email to the release gate's privacy scan, which also keeps a patch's unchanged context lines. Every Python
line that holds one carries a trailing `privacy:allow` marker, so a change near it does not fail the gate."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SSH_EXAMPLE = re.compile(r"[\w.-]+@[\w.-]+\.example:")
MARK = "privacy" + ":allow"


def test_aud_1_example_ssh_git_addresses_carry_privacy_allow():
    found, unmarked = [], []
    for path in ROOT.rglob("*.py"):
        if any(part.startswith(".") for part in path.relative_to(ROOT).parts):
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if SSH_EXAMPLE.search(line):
                found.append(f"{path.relative_to(ROOT)}:{n}")
                if MARK not in line:
                    unmarked.append(f"{path.relative_to(ROOT)}:{n}")
    assert found, "the clean_remote example addresses are expected to exist"
    assert unmarked == []


def test_aud_1_clean_remote_message_is_unchanged():
    import pytest
    from hermes_plugins.grok_bot_twin.twin import engine as E, git_mirror
    with pytest.raises(E.EngineError) as exc:
        git_mirror.clean_remote("https://me:" + "s3cret" + "@" + "forgejo.example/me/bot.git")
    assert str(exc.value) == (
        "That address carries a password or token. Give it without one (for example "
        "https://forgejo.example/me/bot.git or git@forgejo.example:me/bot.git) and let git's "  # privacy:allow
        "credential helper or your SSH key sign in.")
