#!/usr/bin/env python3
"""Write twin/BUILD (the build stamp: commit and tree hash of HEAD) into a plugin tree before it is released or
copied into Hermes' plugins folder. `hermes twin doctor` and `setup --check` compare it with Hermes' install
record and name a mismatch (twin#58).

Usage: tools/stamp_build.py [REPO] [--into TREE]   (TREE defaults to REPO; the stamp goes to TREE/twin/BUILD)
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def stamp(repo: Path, into: Path) -> dict:
    def git(*args: str) -> str:
        return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True,
                              timeout=30).stdout.strip()
    data = {"commit": git("rev-parse", "HEAD"), "tree": git("rev-parse", "HEAD^{tree}")}
    if git("status", "--porcelain", "--untracked-files=no"):
        data["dirty"] = True  # a copy with uncommitted changes: the commit alone does not say what it is
    (into / "twin" / "BUILD").write_bytes((json.dumps(data) + "\n").encode("utf-8"))  # (not write_text(newline=): 3.10+; twin#75)
    return data


def main(argv: list) -> int:
    args = list(argv)
    into = None
    if "--into" in args:
        i = args.index("--into")
        into = Path(args[i + 1])
        del args[i:i + 2]
    repo = Path(args[0]) if args else Path(__file__).resolve().parent.parent
    print(json.dumps(stamp(repo, into or repo)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
