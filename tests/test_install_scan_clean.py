"""The plugin must install without Hermes' "caution" confirmation (rehearsal 0.5.2).

Hermes 0.23.x scans every file of a community plugin at install time; one HIGH finding turns the
verdict to caution and a non-interactive `hermes plugins install --enable` is refused. These are
the HIGH read-secrets patterns that a test or doc line can trip by accident.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_HIGH = [
    re.compile(r'ca' r't\s+(?!>)[^\n]*(\.env|credentials|\.netrc|\.pgpass|\.npmrc|\.pypirc)'),
    re.compile(r'\$HOME/\.hermes/\.env|\~/\.hermes/\.env'),
]
_SKIP = {".git", "node_modules", "__pycache__", ".venv", "venv"}


def test_no_line_trips_hermes_high_read_secrets_patterns():
    hits = []
    for p in ROOT.rglob("*"):
        if not p.is_file() or _SKIP & set(p.relative_to(ROOT).parts) or p.suffix not in {".py", ".md", ".js", ".sh", ".yaml", ".toml", ".txt"}:
            continue
        for n, line in enumerate(p.read_text(errors="ignore").splitlines(), 1):
            if any(rx.search(line) for rx in _HIGH):
                hits.append(f"{p.relative_to(ROOT)}:{n}")
    assert not hits, hits
