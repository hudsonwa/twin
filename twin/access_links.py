"""Give a new twin the access its owner already set up on this computer, before asking for anything (field audit
24 Nov 2026: a twin's one prompt ended by asking the owner for a Google consent that already existed; every other
profile reached the owner's Gmail and Drive through sign-in files shared from the Hermes root).

Only links, never copies: a secret stays in one file the owner controls, and revoking it there revokes it here.
Never overwrites a file the profile already has. Pure file work; no network, no secret is read."""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional

# google-workspace skill sign-in files: the primary token, one per extra account (GOOGLE_ACCOUNT=<name>), the client
_SHARED = re.compile(r"^google_token(?:_[a-z0-9]{1,40})?\.json$|^google_client_secret\.json$")


def shared_files(root: Path) -> List[Path]:
    if not root.is_dir():
        return []
    return sorted(p for p in root.iterdir() if _SHARED.match(p.name) and p.is_file())


def link_existing(home: Path, root: Optional[Path] = None) -> List[str]:
    """Link the Hermes root's shared sign-in files into the profile at `home`; -> the names linked."""
    home = Path(home)
    root = Path(root) if root else home.parent.parent  # <root>/profiles/<name>
    if home.resolve() == root.resolve() or not home.is_dir():
        return []
    linked = []
    for src in shared_files(root):
        dst = home / src.name
        if dst.exists() or dst.is_symlink():
            continue
        os.symlink(src.resolve(), dst)
        linked.append(src.name)
    return linked


def note(names: List[str]) -> Optional[str]:
    if not names:
        return None
    accounts = sorted({n[len("google_token_"):-5] for n in names if n.startswith("google_token_")})
    extra = f" (accounts: primary, {', '.join(accounts)}; pick one with GOOGLE_ACCOUNT)" if accounts else ""
    return f"existing Google sign-in linked from this computer{extra}; nothing to set up"
