"""A tool-level stop for two things a twin must never do, whatever its model decides (twin#: field audit 24 Nov 2026).

Live on a local model, a twin with an always-on written rule "never solve a CAPTCHA" ticked a reCAPTCHA and started
the image challenge, and earlier tried to remote-debug the owner's own Chrome (each attempt put an "Allow remote
debugging?" dialog on the owner's screen). Written rules are advice to the model; this hook is a veto the model cannot
talk past. It runs only in a twin's own profile (the folder botport keeps there), never in the owner's other bots.

Blocked, with a message that becomes the tool's result:
- browser, computer-use and shell calls aimed at a CAPTCHA or "are you human" check: the owner does those;
- attaching to another program's DevTools / remote-debugging port (the owner's browser or apps).
Pure functions; `hook` is what Hermes calls (``pre_tool_call``)."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Optional

_GUARDED = re.compile(r"^(browser|computer|terminal|shell|code|execute|process)", re.I)
_CAPTCHA = re.compile(r"(?i)\b(?:re|h)?captcha\b|recaptcha|hcaptcha|turnstile|not a robot|verify (?:that )?you(?:'| a)re (?:a )?human|"
                      r"select all (?:images|squares)|i'?m not a robot")
_REMOTE_DEBUG = re.compile(r"(?i)remote[-_ ]debugging|devtoolsactiveport|websocketdebuggerurl|"
                           r"chrome-remote-interface|connect_over_cdp|connectovercdp|\bcdp_attach|\b9222\b|/json/version")

CAPTCHA_STOP = ("BLOCKED by the twin's safety guard: this step acts on a CAPTCHA or 'are you human' check. Twins never "
                "do those. Stop here and ask the owner to complete it, then continue.")
DEBUG_STOP = ("BLOCKED by the twin's safety guard: this step attaches to another program's remote-debugging port (the "
              "owner's browser or apps). Use only your own browser tool.")


def _text(args: Any) -> str:
    try:
        return json.dumps(args, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(args)


def check(tool_name: str, args: Any) -> Optional[str]:
    """The block message for this tool call, or None to let it run."""
    if not _GUARDED.match(tool_name or ""):
        return None
    text = _text(args)
    if _CAPTCHA.search(text):
        return CAPTCHA_STOP
    if _REMOTE_DEBUG.search(text):
        return DEBUG_STOP
    return None


def in_twin_profile(home: Optional[str] = None) -> bool:
    """True in a twin's own Hermes profile: botport keeps its folder there."""
    root = Path(home or os.environ.get("HERMES_HOME") or "")
    return bool(str(root)) and (root / "botport").is_dir() and root.parent.name == "profiles"


def hook(tool_name: str = "", args: Any = None, **_kw: Any) -> Optional[dict]:
    if not in_twin_profile():
        return None
    why = check(tool_name, args)
    return {"action": "block", "message": why} if why else None
