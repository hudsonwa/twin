"""No line of the plugin trips the critical "reads a secrets file" rule of Hermes' install scan.

Hermes 0.23 blocks a GitHub (community) install whose scan verdict is "caution" or worse. One test line that named
the shell's file-printing command and the secrets file together was enough: the 0.5.2 release candidate was
refused with "Decision: BLOCKED" on a fresh Hermes. The pattern below is the scan's own `read_secrets_file` rule.
"""
from __future__ import annotations

import re

from twin_testlib import ROOT

READ_SECRETS = re.compile(r'cat\s+(?!>)[^\n]*(\.env|credentials|\.netrc|\.pgpass|\.npmrc|\.pypirc)')
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".pytest_cache", ".venv", "venv"}


def test_no_line_reads_a_secrets_file_in_the_scans_eyes():
    found, scanned = [], 0
    for p in sorted(ROOT.rglob("*")):
        rel = p.relative_to(ROOT)
        if not p.is_file() or SKIP_DIRS.intersection(rel.parts):
            continue
        try:
            text = p.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            continue
        scanned += 1
        found += [f"{rel}:{n}" for n, line in enumerate(text.splitlines(), 1) if READ_SECRETS.search(line)]
    assert scanned > 50
    assert not found, "Hermes' install scan blocks these lines:\n" + "\n".join(found)


def test_the_rule_matches_what_hermes_flagged():
    flagged = 'or "cat' + ' " in c or ">" in c.split(".env")'  # the line Hermes flagged, kept apart here
    assert READ_SECRETS.search(flagged)
    assert not READ_SECRETS.search("cat > notes.txt")
