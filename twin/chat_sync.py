"""Continuous chat sync, Grok -> Hermes: a twin's Hermes chats keep up with the Grok bot's new messages.

Two ways, one setting (`chat_sync_mode`, plugin settings):
- "pull" (b, the default): this computer reads the bot's chat through botport's Grok engine (`botport grok read`)
  on the plugin's background check, every `chat_sync_minutes` (default 6 h), from the cursor it keeps here. No Grok
  usage. The read needs the app's port, which needs an app restart, so by default (`chat_sync_window` "idle",
  twin#52) each due pull opens a short window with `botport grok launch --for DUR --when-idle MIN`: an open port is
  reused with no restart; otherwise the app restarts only when the Mac has had no input for
  `chat_sync_idle_minutes`. Exit 2 (the Mac is in use) skips the pull and tries again after RETRY_MIN, never
  interrupting anyone; a window this pull opened is closed again with `botport grok restore`. "port" only pulls
  when the port is already open (no launch).
- "routine" (a, opt-in): the one prompt Hermes sends the bot (twin/from_hermes.py) also asks it to set up a Grok
  routine, ROUTINE_NAME, that sends its recent messages through the same kind of local command as the one prompt:
      hermes twin chat-sync --bot "NAME" <<'TWIN_JSON_EOF'
      {"bot_name": "NAME", "history": [...]}
      TWIN_JSON_EOF
  Offered only when Grok's own "Execution on Local Computer" setting reads Always allow (read through the engine,
  never changed): a live test found that with "Ask every time" an
  unattended routine never runs the command (its approval card expires after about 10 minutes), and that with the
  app quit it only fails. It costs Grok usage on every run.
- "off": neither.

Which messages are new is tracked on this computer, never by the bot: the live test showed a routine run does not
know what it sent last time (it sent an empty history). The routine sends a fixed recent window every time; the pull
keeps its cursor in chat-sync.json; and the merge below drops what Hermes already has.

Both end in history.import_history, whose de-duplication (entry ids per conversation, a conversation's own id, and
the per-twin `seen` digests) means a message sent twice, or read twice, lands once. Each run is logged in the
one-prompt call log (tool TOOL; counts only, never texts) so the one prompt's PASS can be checked from there.
"""
from __future__ import annotations

import contextlib
import json
import time
from typing import Any, Optional

from . import config, history, one_prompt, safe, store
from .model import now_iso, parse_iso

TOOL = "twin_chat_sync"
MODES = ("routine", "pull", "off")
DEFAULT_MODE = "pull"  # a live test: a routine cannot run the command under "Ask every time"
DEFAULT_MINUTES = 6 * 60  # twin#52: one idle-only window every 6 h by default
WINDOWS = ("idle", "port")
DEFAULT_WINDOW = "idle"
DEFAULT_IDLE_MIN = 10
WINDOW_S = 10 * 60       # how long a window may stay open (botport's TTL guard closes it at the latest)
RETRY_MIN = 30           # after "the Mac is in use" (exit 2) or a window that could not open
MIN_MINUTES, MAX_MINUTES = 15, 24 * 60
ROUTINE_NAME = "Sync chats to Hermes"
OVERLAP_MIN = 15  # each routine run sends a little more than its interval; the overlap is de-duplicated
ARGS = ("bot_name", "history")
READ_LIMIT = 200
STATE = "chat-sync.json"


def mode() -> str:
    m = config.get("chat_sync_mode")
    return m if m in MODES else DEFAULT_MODE


def minutes() -> int:
    try:
        return min(MAX_MINUTES, max(MIN_MINUTES, int(config.get("chat_sync_minutes") or DEFAULT_MINUTES)))
    except (TypeError, ValueError):
        return DEFAULT_MINUTES


def window() -> str:
    w = config.get("chat_sync_window")
    return w if w in WINDOWS else DEFAULT_WINDOW


def idle_minutes() -> int:
    try:
        return min(240, max(1, int(config.get("chat_sync_idle_minutes") or DEFAULT_IDLE_MIN)))
    except (TypeError, ValueError):
        return DEFAULT_IDLE_MIN


def command_for(name: str) -> str:
    return f'hermes twin chat-sync --bot "{name}"'


def routine_prompt(name: str, every: Optional[int] = None) -> str:
    """The prompt the Grok routine runs each time (mode "routine")."""
    every = every or minutes()
    return (f"Send your new chat messages to your Hermes twin with ONE command on the user's local computer (your "
            f"\"Run a command on your local computer\" tool, never your own cloud computer), in exactly this form:\n"
            f"{command_for(name)} <<'TWIN_JSON_EOF'\n"
            f"{{\"bot_name\": \"{name}\", \"history\": [...]}}\n"
            "TWIN_JSON_EOF\n"
            f"In history put ALL the messages of the last {every + OVERLAP_MIN} minutes (never only the ones you think are new: "
            "Hermes keeps track of what it already has), from your own "
            "conversations: for each conversation its `id` when you have one, its `title`, `started` (when the "
            "conversation itself started, not its first message you send), and those messages as {role, text, "
            "time} with role \"user\" or \"assistant\". Only what was said: no tool output, no hidden reasoning, "
            "nothing the user asked you to keep private, no sign-in password, cookie or login. Keep history under "
            "8,000 characters, newest first. Messages Hermes already has are skipped. "
            "If that window holds no message at all, run nothing and answer \"SYNC: nothing new\". Run no other command, and "
            "never run this for another bot. Answer with the command's first line.")


# ---- state: which twins are enrolled, the pull cursor, the last run ------------------------------------------------
def _path():
    return one_prompt._folder() / STATE


def _state() -> dict:
    st = store.read_json(_path(), {}) if _path().is_file() else {}
    return st if isinstance(st, dict) and isinstance(st.get("twins"), dict) else {"twins": {}}


def _save(st: dict) -> None:
    store.atomic_write_json(_path(), st)


def enrol(pid: str, how: str, bot_id: Optional[str] = None) -> None:
    st = _state()
    rec = st["twins"].setdefault(pid, {})
    rec.update({"mode": how, "since": rec.get("since") or now_iso()})
    if bot_id:
        rec["bot_id"] = str(bot_id)[:80]
    _save(st)


def drop(pid: str) -> bool:
    """A removed twin leaves chat sync: its enrolment, cursor and last run go. -> whether it was enrolled."""
    st = _state()
    if st["twins"].pop(pid, None) is None:
        return False
    _save(st)
    return True


def status() -> dict:
    st = _state()
    return {"mode": mode(), "minutes": minutes(), "window": window(), "idle_minutes": idle_minutes(),
            "window_skipped": st.get("window_skipped"), "twins": st["twins"]}


def _note(pid: str, fields: dict) -> None:
    with contextlib.suppress(OSError):
        st = _state()
        st["twins"].setdefault(pid, {}).update(fields)
        _save(st)


# ---- (a) the bot sends its new messages ------------------------------------------------------------------------
def _find(svc: Any, name: str) -> tuple:
    hits = [pid for pid, e in svc._registry().items() if one_prompt._same((e.get("grok") or {}).get("name"), name)]
    if not hits:
        raise one_prompt.Refused("this bot has no Hermes twin yet; say \"Clone yourself to Hermes\" first")
    if len(hits) > 1:
        raise one_prompt.Refused("more than one twin has that bot's name; run hermes twin status to see them")
    pid = hits[0]
    prof = ((svc._registry().get(pid) or {}).get("hermes") or {}).get("profile")
    if not isinstance(prof, str) or prof == "default" or svc._profile_home(prof) is None:
        raise one_prompt.Refused("this twin has no Hermes bot of its own")
    return pid, prof


def _line(name: str, res: dict) -> str:
    if not res.get("ok"):
        return f"FAIL: {name} chat sync: {res.get('why') or 'nothing imported'}."
    h = res.get("history") or {}
    return (f"PASS: {name} chat sync: {h.get('new_messages', 0)} new message(s) in Hermes chats \"From Grok: …\" "
            f"({h.get('conversations', 0)} conversation(s) sent; messages Hermes had were skipped).")


def _log(name: str, res: dict, started: float, how: str) -> None:
    h = res.get("history") or {}
    one_prompt.log_call({"at": now_iso(), "tool": TOOL, "how": how, "bot": safe.clean_name(name, one_prompt.NAME_MAX),
                         "result": "PASS" if res.get("ok") else "FAIL", "pair_id": res.get("pair_id"),
                         "counts": {"conversations": h.get("conversations", 0),
                                    "new_messages": h.get("new_messages", 0)},
                         "ms": int((time.monotonic() - started) * 1000)})


def _import(svc: Any, name: str, pid: str, prof: str, convs: list) -> dict:
    got = history.import_history(name, convs, pid=pid, profile=prof)
    if got.get("failed"):
        raise one_prompt.Refused(f"{got['failed']} conversation part(s) could not be imported into Hermes; the next "
                                 "run tries them again")
    return got


def _why(res: dict, exc: Exception) -> None:
    if isinstance(exc, history.HistoryError):
        res["why"] = str(exc)
    else:
        one_prompt._why(res, exc)


def from_bot(svc: Any, allowed: list, bot_name: Any, history_arg: Any = None) -> dict:
    """`hermes twin chat-sync --bot NAME` with {"bot_name", "history"} on stdin. Never raises."""
    started = time.monotonic()
    res: dict = {"ok": False}
    shown = "this bot"
    try:
        name = one_prompt.check_name(bot_name, allowed)
        shown = name
        if not isinstance(history_arg, list):
            raise one_prompt.Refused("history must be a list of conversations")
        with one_prompt.bot_lock(name):
            pid, prof = _find(svc, name)
            res.update(pair_id=pid, profile=prof)
            res["history"] = _import(svc, name, pid, prof, history_arg)
            _note(pid, {"last": {"at": now_iso(), "how": "routine",
                                 "new_messages": res["history"].get("new_messages", 0)}})
            res["ok"] = True
    except Exception as exc:  # noqa: BLE001  (the routine always gets one line)
        _why(res, exc)
    res["line"] = _line(shown, res)
    if one_prompt._secrets.has_secret(res["line"]):
        res["line"] = "FAIL: the answer looked like it held a password or key, so it is not shown."
    _log(shown, res, started, "routine")
    return res


# ---- (b) this computer pulls through the engine ----------------------------------------------------------------
def _as_history(bot_id: str, msgs: list) -> list:
    """Engine Message objects -> one conversation in the history shape (the bot's own chat, keyed by its id)."""
    from .bot_export import without_own_turns
    out = []
    for m in without_own_turns(msgs):
        role = {"user": "user", "bot": "assistant", "assistant": "assistant"}.get(m.get("role"))
        if role and m.get("kind", "text") in ("text", "question") and m.get("text", "").strip():
            out.append({"role": role, "text": m["text"], "time": m.get("at")})
    return [{"id": f"grok-chat:{bot_id}", "title": "Chat in Grok", "messages": out}] if out else []


def pull_one(svc: Any, eng: Any, pid: str) -> dict:
    """Read the bot's new messages through the engine and import them. Never raises; -> {"ok", "line", ...}."""
    from . import grok_engine as ge
    started = time.monotonic()
    entry = svc._registry().get(pid) or {}
    name = safe.clean_name((entry.get("grok") or {}).get("name") or pid, one_prompt.NAME_MAX)
    prof = (entry.get("hermes") or {}).get("profile")
    rec = _state()["twins"].get(pid) or {}
    bot_id = rec.get("bot_id") or (entry.get("grok") or {}).get("id") or name
    res: dict = {"ok": False, "pair_id": pid}
    try:
        if not isinstance(prof, str) or prof == "default":
            raise one_prompt.Refused("this twin has no Hermes bot of its own")
        got = eng.read(bot_id, rec.get("cursor"))
        if got.exit == ge.OTHER and rec.get("cursor"):  # (a cursor the engine no longer knows: read again in full)
            got = eng.read(bot_id, None)
        if got.exit == ge.REFUSED:
            raise one_prompt.Refused(ge.refused_why(got))
        if got.exit != ge.DONE:
            raise one_prompt.Refused(f"the engine could not read the chat ({ge.EXIT_WORDS.get(got.exit)}"
                                     + (f": {got.proof}" if got.proof else "") + ")")
        msgs = ge.messages_of(got)
        with one_prompt.bot_lock(name):
            res["history"] = _import(svc, name, pid, prof, _as_history(str(bot_id), msgs)) if msgs else \
                {"conversations": 0, "new_messages": 0}
        fields = {"last": {"at": now_iso(), "how": "pull", "new_messages": res["history"].get("new_messages", 0)}}
        if msgs and msgs[-1].get("key"):
            fields["cursor"] = msgs[-1]["key"]
        _note(pid, fields)
        res["ok"] = True
    except Exception as exc:  # noqa: BLE001
        _why(res, exc)
        # a failed pull waits a full interval too, so a failing twin cannot open a window on every tick
        _note(pid, {"last": {"at": now_iso(), "how": "pull", "failed": True, "new_messages": 0}})
    res["line"] = _line(name, res)
    _log(name, res, started, "pull")
    return res


def pull_tick(svc: Any, now: Optional[float] = None) -> int:
    """The background check's part (service.tick): in mode "pull", each enrolled twin whose last pull is older than
    `chat_sync_minutes`. -> twins pulled. Without the engine nothing runs (and nothing is said: the one prompt's
    FAIL line already named the way out)."""
    if mode() != "pull":
        return 0
    reg = svc._registry()
    twins = {p: r for p, r in _state()["twins"].items() if isinstance(r, dict) and r.get("mode") == "pull"
             and _pullable(reg.get(p))}  # a removed or profile-less twin never opens a window
    if not twins:
        return 0
    now = time.time() if now is None else now
    st = _state()
    retry = parse_iso(st.get("window_retry"))
    if retry is not None and now < retry.timestamp():
        return 0
    due = []
    for pid, rec in twins.items():
        last = parse_iso(((rec.get("last") or {}).get("at")) if isinstance(rec.get("last"), dict) else None)
        if last is None or now - last.timestamp() >= minutes() * 60:
            due.append(pid)
    if not due:
        return 0
    try:
        with one_prompt.engine_lock(wait=False):  # never while from-hermes uses the same port
            return _pull_due(svc, due, now)
    except one_prompt.Refused:
        return 0


def _pullable(entry: Any) -> bool:
    prof = ((entry or {}).get("hermes") or {}).get("profile") if isinstance(entry, dict) else None
    return isinstance(prof, str) and prof != "default"


def _pull_due(svc: Any, due: list, now: float) -> int:
    from . import grok_engine as ge
    try:
        eng = ge.from_service(svc)
    except ge.Unavailable:
        return 0
    opened = False
    if window() == "idle":
        got = eng.window(WINDOW_S, idle_minutes())
        if got.exit != ge.DONE:  # 2: the Mac is in use; else the window could not open. Skip, try later.
            _window_note(now, "in use" if got.exit == ge.STILL_WORKING else
                         safe.clean_summary(got.proof or ge.EXIT_WORDS.get(got.exit, "failed"), 200))
            return 0
        opened = not (isinstance(got.data, dict) and got.data.get("reused"))
    _window_note(None, None)
    try:
        for pid in due:
            pull_one(svc, eng, pid)
    finally:
        if opened:  # only a window this pull opened; a reused one belongs to whoever opened it
            with contextlib.suppress(Exception):
                eng.restore()
    return len(due)


def _window_note(now: Optional[float], why: Optional[str]) -> None:
    """A skipped window: when to try again and why (status shows it); None clears it."""
    st = _state()
    if now is None:
        st.pop("window_retry", None)
        st.pop("window_skipped", None)
    else:
        st["window_retry"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now + RETRY_MIN * 60))
        st["window_skipped"] = {"at": now_iso(), "why": why}
    _save(st)


# ---- the command line -------------------------------------------------------------------------------------------
def cmd(a: Any) -> int:
    """`hermes twin chat-sync`: --bot NAME (stdin JSON, run by the bot's routine), --pull [TWIN|--all], --status."""
    import os
    import sys

    from . import mcp_server
    from .service import get_service
    if getattr(a, "status", False):
        st = status()
        print(f"Chat sync: {st['mode']} (every {st['minutes']} min, window {st['window']}"
              + (f", idle {st['idle_minutes']} min" if st["window"] == "idle" else "")
              + f"); {len(st['twins'])} twin(s) enrolled.")
        sk = st.get("window_skipped")
        if isinstance(sk, dict):
            print(f"Last window skipped at {safe.clean_name(sk.get('at'), 40)}: {safe.clean_summary(sk.get('why'), 200)}"
                  " (tried again later).")
        if st["mode"] == "routine":
            print(f"  Each enrolled bot runs its Grok routine \"{ROUTINE_NAME}\".")
        for pid, rec in sorted(st["twins"].items()):
            last = rec.get("last") or {}
            print(f"  {pid}: {rec.get('mode')}; last run {last.get('at') or 'never'}"
                  + (f", {last.get('new_messages', 0)} new" if last else ""))
        return 0
    svc = get_service()
    if getattr(a, "pull", False):
        from . import grok_engine as ge
        try:
            eng = ge.from_service(svc)
        except ge.Unavailable as exc:
            print(f"FAIL: chat sync: the Grok engine is not available ({exc}). Instead, {ge.FALLBACK}.")
            return 1
        twins = list(_state()["twins"]) if a.all else []
        if not a.all:
            from . import cli
            twins = [cli._one(svc, a.pair)]
        rc = 0
        for pid in twins:
            got = pull_one(svc, eng, pid)
            print(got["line"])
            rc = rc or (0 if got["ok"] else 1)
        if not twins:
            print("No twin is enrolled for chat sync yet: hermes twin from-hermes NAME sets it up.")
        return rc
    if not a.bot:
        print("✗ Name the Grok bot: hermes twin chat-sync --bot \"NAME\" < history.json (or --pull, --status)",
              file=sys.stderr)
        return 2
    raw = sys.stdin.read(mcp_server.LINE_CAP + 1)
    try:
        args = json.loads(raw) if len(raw) <= mcp_server.LINE_CAP else None
    except (ValueError, RecursionError):
        args = None
    if not isinstance(args, dict):
        print("FAIL: the input is not one JSON object (or it is too large); nothing was changed.")
        return 1
    extra = sorted(k for k in args if k not in ARGS)
    if extra:
        print("FAIL: chat-sync takes only " + ", ".join(ARGS) + "; nothing was changed.")
        return 1
    args.setdefault("bot_name", a.bot[0] if len(a.bot) == 1 else None)
    allowed = mcp_server.bound(list(a.bot), os.environ.get(mcp_server.CALLER_ENV))
    res = from_bot(svc, allowed, args.get("bot_name"), args.get("history"))
    details = {k: v for k, v in res.items() if k != "line"}
    print(res["line"] + "\n" + json.dumps(details, ensure_ascii=False, default=str))
    return 0 if res["ok"] else 1


def setup(subs: Any) -> None:
    from .mcp_server import _twin_name
    q = subs.add_parser("chat-sync", help="Keep a twin's Hermes chats up with its Grok bot's new messages "
                                          "(docs/ONE-PROMPT.md#continuous-chat-sync)")
    q.add_argument("pair", nargs="?", type=_twin_name, metavar="TWIN", help="With --pull: the twin (not needed with one)")
    q.add_argument("--bot", action="append", default=[], metavar="NAME",
                   help="Run by the bot's routine: its new messages as JSON on stdin; any other name is refused")
    q.add_argument("--pull", action="store_true", help="Read the bot's new messages through botport's Grok engine now")
    q.add_argument("--all", action="store_true", help="With --pull: every enrolled twin")
    q.add_argument("--status", action="store_true", help="The mode, the interval and each enrolled twin's last run")


HANDLERS = {"chat-sync": cmd}
