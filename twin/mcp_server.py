"""The one-prompt route's two entry points over one library call each (one_prompt.py):

    hermes twin from-grok --bot NAME        < STATE.json   twin, clone, back up or move this bot to Hermes
    hermes twin back-to-grok --bot NAME     < STATE.json   bring a moved bot back to Grok
    hermes twin mcp --bot NAME                             the same two calls as a local stdio MCP server

The supported route is the first two: Grok Bot 1.0.1 runs a custom "Command" connector on the bot's own cloud
computer, never on this one, so a Grok bot reaches this computer only through its "Run a command on your local
computer" tool (host_shell). The bot runs ONE such command per prompt, passing its own state as one JSON object
on stdin (the tool's arguments: bot_name, instructions, skills, memory, routines_meta, move, grok_paused,
history). The answer is the tool's PASS/FAIL line, then its details as JSON. `hermes twin mcp` speaks MCP's
JSON-RPC (initialize, ping, tools/list, tools/call) for a local connector a later Grok app may run on this computer.

`--bot NAME` is the allowlist, and it binds the command to one bot: a call that names any other bot, or carries an
argument not in the schema (a path, a profile), is refused before anything is read or written. A bot's name in
`bot_name` is only a claim the calling bot makes, so with several `--bot` names every call is refused unless the
environment names the caller (GROK_BOT_TWIN_CALLER=NAME, one of the --bot names), and then only that bot's calls
are taken. One `--bot` per command (from-grok, back-to-grok) or per connector is the setup the docs give.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any, Callable, Optional, TextIO

from . import one_prompt

PROTOCOL = "2025-06-18"
LINE_CAP = 4_000_000  # bytes of one request line (one_prompt.TOTAL_MAX characters, JSON-escaped, fit)
ARGS = ("bot_name", "instructions", "skills", "memory", "routines_meta", "move", "grok_paused", "history")

TOOL_SPEC = {
    "name": one_prompt.TOOL,
    "description": (
        "Twin this Grok bot to Hermes (also: clone, copy, duplicate, back up yourself to Hermes). Pass your own "
        "name, your instructions word for word, your skills (read each with the Skill tool), your memory (from "
        "RecallMemory) and your routines. Call it ONCE with everything. It makes or syncs your Hermes twin, tests "
        "it, and answers with one line that starts PASS or FAIL: report that line to the user. Never put a "
        "password, key or token in any argument."),
    "inputSchema": {
        "type": "object", "additionalProperties": False, "required": ["bot_name"],
        "properties": {
            "bot_name": {"type": "string", "description": "Your own name, exactly as Grok shows it."},
            "instructions": {"type": "string", "description": "Your instructions, in full, word for word."},
            "skills": {"type": "array", "description": "Each of your skills.", "items": {
                "type": "object", "required": ["name", "instructions"], "properties": {
                    "name": {"type": "string"}, "description": {"type": "string"},
                    "instructions": {"type": "string", "description": "The skill's full text."}}}},
            "memory": {"type": "array", "items": {"type": "string"},
                       "description": "What you remember, one item per entry (from RecallMemory)."},
            "routines_meta": {"type": "array", "description": "Your routines; they are added switched off.",
                              "items": {"type": "object", "properties": {
                                  "name": {"type": "string"}, "instruction": {"type": "string"},
                                  "trigger": {"type": "string"}, "schedule_cron": {"type": "string"},
                                  "schedule_text": {"type": "string"}, "timezone": {"type": "string"}}}},
            "grok_paused": {"type": "array", "items": {"type": "string"}, "description": (
                "With move only: the id (else the name) of each of your routines you have ALREADY paused in Grok "
                "with UpdateRoutine. Every routine you sent must be in it, or nothing is turned on in Hermes.")},
            "move": {"type": "boolean", "description": (
                "true only when the user asks you to MOVE to Hermes. Pause each of your routines in Grok with "
                "UpdateRoutine FIRST and list them in grok_paused; Hermes then turns them on. Otherwise leave it out.")},
            "history": {"type": "array", "description": (
                "Your own recent conversations, read from your chat history, so your twin has them as Hermes "
                "chats. Re-sending one already sent adds only its new messages."), "items": {
                "type": "object", "properties": {
                    "title": {"type": "string"}, "started": {"type": "string"},
                    "messages": {"type": "array", "items": {"type": "object", "properties": {
                        "role": {"type": "string", "enum": ["user", "assistant"]}, "text": {"type": "string"},
                        "time": {"type": "string"}}}}}}},
        }},
}


BACK_ARGS = ("bot_name", "instructions", "skills", "memory")
BACK_SPEC = {
    "name": one_prompt.BACK_TOOL,
    "description": (
        "Bring this bot back from Hermes to Grok (also: come back to Grok, move back, return yourself). Pass your "
        "own name and your current instructions, skills and memory. Call it ONCE. It syncs both ways, pauses your "
        "routines in Hermes, and answers with one PASS or FAIL line plus a JSON bundle: write its memory with "
        "UpdateMemory, its skills with UpdateSkill, and re-enable its routines_to_enable with UpdateRoutine."),
    "inputSchema": {
        "type": "object", "additionalProperties": False, "required": ["bot_name"],
        "properties": {k: TOOL_SPEC["inputSchema"]["properties"][k] for k in BACK_ARGS}},
}
TOOLS = {one_prompt.TOOL: (TOOL_SPEC, ARGS), one_prompt.BACK_TOOL: (BACK_SPEC, BACK_ARGS)}


def _reply(mid: Any, result: Optional[dict] = None, error: Optional[dict] = None) -> dict:
    msg: dict = {"jsonrpc": "2.0", "id": mid}
    if error is not None:
        msg["error"] = error
    else:
        msg["result"] = result
    return msg


def _runner(run: Any, tool: str) -> Optional[Callable[..., dict]]:
    """`run` is {tool name: callable}, or one callable for twin_from_grok alone."""
    return run.get(tool) if isinstance(run, dict) else (run if tool == one_prompt.TOOL else None)


def _call(params: Any, run: Any) -> dict:
    tool = params.get("name") if isinstance(params, dict) else None
    fn = _runner(run, tool) if tool in TOOLS else None
    if fn is None:
        return {"content": [{"type": "text", "text": "FAIL: there is no such tool."}], "isError": True}
    allowed = TOOLS[tool][1]
    args = params.get("arguments")
    args = {} if args is None else args
    extra = sorted(k for k in args if k not in allowed) if isinstance(args, dict) else ["(not an object)"]
    if extra:  # a path, a profile, anything not in the schema: refused whole, nothing is read
        text = f"FAIL: {tool} takes only " + ", ".join(allowed) + "; nothing was changed."
        return {"content": [{"type": "text", "text": text}], "isError": True}
    res = fn(**args)
    details = {k: v for k, v in res.items() if k != "line"}
    return {"content": [{"type": "text", "text": res["line"] + "\n" + json.dumps(details, ensure_ascii=False)}],
            "isError": not res.get("ok")}


def handle(msg: Any, run: Any) -> Optional[dict]:
    """One JSON-RPC message -> its reply (None for a notification)."""
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or not isinstance(msg.get("method"), str):
        return _reply(msg.get("id") if isinstance(msg, dict) else None,
                      error={"code": -32600, "message": "invalid request"})
    method, mid = msg["method"], msg.get("id")
    if "id" not in msg:
        return None  # notifications (initialized, cancelled): nothing to answer
    if method == "initialize":
        asked = (msg.get("params") or {}).get("protocolVersion")
        return _reply(mid, {"protocolVersion": asked if isinstance(asked, str) and asked else PROTOCOL,
                            "capabilities": {"tools": {"listChanged": False}},
                            "serverInfo": {"name": "grok-bot-twin", "version": _version()}})
    if method == "ping":
        return _reply(mid, {})
    if method == "tools/list":
        return _reply(mid, {"tools": [TOOL_SPEC, BACK_SPEC] if isinstance(run, dict) else [TOOL_SPEC]})
    if method == "tools/call":
        return _reply(mid, _call(msg.get("params"), run))
    return _reply(mid, error={"code": -32601, "message": "method not found"})


def _version() -> str:
    try:
        from pathlib import Path

        import yaml
        return str(yaml.safe_load((Path(__file__).resolve().parent.parent / "plugin.yaml").read_text())["version"])
    except Exception:  # noqa: BLE001
        return "0"


CALLER_ENV = "GROK_BOT_TWIN_CALLER"


def _norm(name: Any) -> str:
    return " ".join(str(name).split()).casefold()


def bound(allowed: list, caller: Optional[str] = None) -> list:
    """The one bot name this server takes calls for: its only --bot, or with several, the caller the connector's
    environment names (when it is one of them). [] means every call is refused."""
    names = [a for a in allowed or [] if isinstance(a, str) and a.strip()]
    if caller is not None and caller.strip():
        return [a for a in names if _norm(a) == _norm(caller)][:1]
    return names if len(names) == 1 else []


def serve(allowed: list, svc_factory: Callable[[], Any], stdin: TextIO = sys.stdin,
          stdout: TextIO = sys.stdout, caller: Optional[str] = None) -> int:
    caller = os.environ.get(CALLER_ENV) if caller is None else caller
    allowed = bound(allowed, caller)
    run = {one_prompt.TOOL: lambda **kw: one_prompt.twin_from_grok(svc_factory(), allowed, **kw),
           one_prompt.BACK_TOOL: lambda **kw: one_prompt.twin_back_to_grok(svc_factory(), allowed, **kw)}

    for raw in stdin:
        if len(raw) > LINE_CAP:
            out = _reply(None, error={"code": -32600, "message": "request too large"})
        else:
            try:
                out = handle(json.loads(raw), run) if raw.strip() else None
            except (ValueError, RecursionError):
                out = _reply(None, error={"code": -32700, "message": "parse error"})
        if out is not None:
            stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
            stdout.flush()
    return 0


def cmd_mcp(a: Any) -> int:
    from .service import get_service
    if not a.bot:
        print("✗ Name the Grok bot this connector may twin: hermes twin mcp --bot \"NAME\"", file=sys.stderr)
        return 2
    if len(a.bot) > 1 and not bound(list(a.bot), os.environ.get(CALLER_ENV)):
        print(f"! Several --bot names and no {CALLER_ENV} naming one of them: every call will be refused. "
              "Give each bot its own connector with one --bot.", file=sys.stderr)
    return serve(list(a.bot), get_service)


def cmd_one(a: Any) -> int:
    """`from-grok` / `back-to-grok`: one JSON object on stdin -> the tool's line and details on stdout."""
    from .service import get_service
    if not a.bot:
        print(f"✗ Name the Grok bot: hermes twin {a.twin_cmd} --bot \"NAME\" < state.json", file=sys.stderr)
        return 2
    raw = sys.stdin.read(LINE_CAP + 1)
    try:
        args = json.loads(raw) if len(raw) <= LINE_CAP else None
    except (ValueError, RecursionError):
        args = None
    if not isinstance(args, dict):
        print("FAIL: the input is not one JSON object (or it is too large); nothing was changed.")
        return 1
    args.setdefault("bot_name", a.bot[0] if len(a.bot) == 1 else None)
    tool = one_prompt.TOOL if a.twin_cmd == "from-grok" else one_prompt.BACK_TOOL
    fn = one_prompt.twin_from_grok if tool == one_prompt.TOOL else one_prompt.twin_back_to_grok
    allowed = bound(list(a.bot), os.environ.get(CALLER_ENV))  # (several --bot: only with the caller named)
    out = _call({"name": tool, "arguments": args}, {tool: lambda **kw: fn(get_service(), allowed, **kw)})
    print(out["content"][0]["text"])
    return 1 if out["isError"] else 0


def setup(subs: Any) -> None:
    for cmd, what in (("from-grok", "Twin, back up or move a Grok bot to Hermes from its own state on stdin "
                                    "(JSON; the bot runs this through host_shell; docs/ONE-PROMPT.md)"),
                      ("back-to-grok", "Bring a moved Grok bot back from Hermes; its state on stdin (JSON)")):
        q = subs.add_parser(cmd, help=what)
        q.add_argument("--bot", action="append", default=[], metavar="NAME",
                       help="The Grok bot this may write for (repeat for more); any other name is refused")
        q.set_defaults(twin_cmd=cmd)
    p = subs.add_parser("mcp", help="The same two calls as a local stdio MCP server, for a future local connector (docs/ONE-PROMPT.md)")
    p.add_argument("--bot", action="append", default=[], metavar="NAME",
                   help="The Grok bot this connector is for; any other name is refused. Repeated, every call is "
                        f"refused unless {CALLER_ENV} names the calling bot")


HANDLERS = {"mcp": cmd_mcp, "from-grok": cmd_one, "back-to-grok": cmd_one}
