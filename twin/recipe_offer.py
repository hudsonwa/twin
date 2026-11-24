"""Last setup step: offer the reliability recipe (and its operating pack) to twins on a local or weaker model.

Opt-in. Nothing is installed without the owner's yes typed at the prompt, or --with-recipe. The recipe comes
from one pinned release (tag + commit); a clone that is not exactly that commit is refused. The recipe's own
installer does the work (it never restarts a gateway: --no-restart is its default). Its SOUL blocks go at the
end of SOUL.md, after the botport and twin blocks."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any, Callable, Optional

RECIPE_REPO = "https://github.com/hudsonwa/hermes-reliability-recipe.git"
RECIPE_TAG = "v0.3.0"
RECIPE_COMMIT = ""  # filled at release: the full commit id of RECIPE_TAG. Empty = not released, offer says so.
RECIPE_MARKERS = ("<!-- hrr:begin operating-pack", "# Reliability (hermes-reliability-recipe)")
_SIZE = re.compile(r"(?<![\d.])(\d{1,3}(?:\.\d+)?)\s*b\b", re.I)
SMALL_B = 40  # a model name that says it has fewer billion parameters than this counts as weaker


def _model(home: Path) -> dict:
    from . import hermes_side as hs
    try:
        text = hs._read_below_root(home / "config.yaml", hs.CONFIG_CAP)
        doc = hs._yaml_load(text) if text else None
    except Exception:
        doc = None
    m = doc.get("model") if isinstance(doc, dict) else None
    return m if isinstance(m, dict) else {}


def weaker(model: dict) -> bool:
    """A local endpoint, or a model name that states a small size (e.g. `qwen3-30b`)."""
    from .endpoints import is_local
    url = model.get("base_url")
    if isinstance(url, str) and is_local(url):
        return True
    name = str(model.get("default") or model.get("model") or "")
    sizes = [float(s) for s in _SIZE.findall(name)]
    return bool(sizes) and max(sizes) < SMALL_B


def installed(home: Path) -> bool:
    return (home / "state" / "reliability-recipe-root.txt").is_file()


def candidates(svc: Any) -> list[tuple[str, Path]]:
    """(profile, home) for each real twin on a weaker model that does not have the recipe yet."""
    out = []
    try:
        used = svc.profiles_in_use()
        demo = set(svc.demo.profiles())
    except Exception:
        return out
    for prof in sorted(used):
        if prof in demo:
            continue
        home = svc._profile_home(prof)
        if home and (home / "config.yaml").is_file() and not installed(home) and weaker(_model(home)):
            out.append((prof, home))
    return out


def cache_dir() -> Path:
    from .store import hermes_root
    return hermes_root() / "cache" / f"hermes-reliability-recipe-{RECIPE_TAG}"


def fetch(run: Callable = subprocess.run) -> Path:
    """The pinned release in Hermes's cache, checked to be exactly RECIPE_COMMIT."""
    if not RECIPE_COMMIT:
        raise RuntimeError(f"recipe {RECIPE_TAG} is not released yet")
    d = cache_dir()
    if not d.exists():
        run(["git", "clone", "--quiet", "--depth", "1", "--branch", RECIPE_TAG, RECIPE_REPO, str(d)], check=True)
    head = run(["git", "-C", str(d), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
    if head != RECIPE_COMMIT:
        raise RuntimeError(f"recipe copy at {d} is {head[:12]}, not the pinned {RECIPE_TAG} ({RECIPE_COMMIT[:12]})")
    return d


def install_cmd(recipe: Path, prof: str, owner: str, workdir: str, captcha: str) -> list[str]:
    return ["bash", str(recipe / "scripts" / "install.sh"), "--profile", prof, "--pack", "operating",
            "--owner", owner, "--workdir", workdir, "--captcha", captcha]


def offer(svc: Any, a: Any, out: Callable[[str], None], confirm: Callable[[str], bool],
          run: Callable = subprocess.run) -> int:
    """The final setup step. Returns 0 unless an install the owner asked for failed."""
    if getattr(a, "no_recipe", False):
        return 0
    todo = candidates(svc)
    if not todo:
        return 0
    names = ", ".join(p for p, _ in todo)
    out("")
    out(f"Optional: {names} run on a local or smaller model. The reliability recipe ({RECIPE_TAG}) adds a claim")
    out("checker, test receipts and short working habits that help such models finish honestly.")
    out("It changes SOUL.md (a marked block at the end), config.yaml (hooks) and adds skills; backups are kept.")
    if not RECIPE_COMMIT:
        out(f"The recipe {RECIPE_TAG} is not released yet; nothing was installed. Run setup again after its release.")
        return 0
    want = bool(getattr(a, "with_recipe", False)) or confirm(f"Install the reliability recipe into {names}?")
    if not want:
        out("Skipped. Later: hermes twin setup --with-recipe")
        return 0
    try:
        recipe = fetch(run)
    except Exception as e:  # noqa: BLE001
        out(f"Recipe not installed: {e}")
        return 1
    owner = getattr(a, "recipe_owner", None) or "the owner"
    captcha = getattr(a, "recipe_captcha", None) or "handoff"
    rc = 0
    for prof, home in todo:
        workdir = getattr(a, "recipe_workdir", None) or str(home)
        r = run(install_cmd(recipe, prof, owner, workdir, captcha))
        if getattr(r, "returncode", 1) == 0:
            out(f"Recipe installed into {prof}. It takes effect after that bot's gateway restarts.")
        else:
            out(f"Recipe install failed for {prof} (exit {getattr(r, 'returncode', '?')}); its backups are in place.")
            rc = 1
    return rc
