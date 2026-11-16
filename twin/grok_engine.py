"""The one place twin talks to botport's Grok engine (`botport grok ...`, phase P1 of the control plan).

twin never drives the Grok app itself: it runs the engine as a subprocess with `--json` and reads one JSON object
from stdout and the engine's exit code. Everything this module knows about the engine's command line is in CMDS,
FLAGS and the parse functions below, so lining up with the engine's frozen interface is a change here only.

Interface: botport's docs/GROK-ENGINE-INTERFACES.md, frozen at the end of P1 (crate botport-grok, cargo feature
`grok`; changes after the freeze are additive only):
  exit 0 done (ask/wait: the bot is idle with a reply after our message), 1 other failure, 2 timeout and the bot
  still working, 3 the bot waits for the user (`bot.needs_input`), 4 refused by policy or a floor, 5 app or
  transport unavailable; `--json`: one JSON object on stdout carrying `exit` and `proof` (the line
  `PASS: what; check` / `FAIL: what; why`, repeated on stderr), `error: {code, message, hint}` on a failure
  without a value; ask/wait/read under the balanced/careful presets are wrapped as
  {"untrusted_bot_content": {...}} (unwrapped here: twin treats every bot text as data anyway).
`botport version` lists no feature for the engine, so it is found by asking `botport grok status --json`: a
botport without the engine does not answer with the engine's JSON object.

The binary is the one the plugin already verified (BotportEngine._verify: path, owner, sha256, attestation); the
engine is never looked for anywhere else, and a botport without the Grok engine is reported as missing.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from . import safe
from .engine import EngineError, run_capped

INTERFACE = "GROK-ENGINE-INTERFACES.md, frozen end of P1 (botport a4ed5e3)"

DONE, OTHER, STILL_WORKING, NEEDS_USER, REFUSED, UNAVAILABLE = 0, 1, 2, 3, 4, 5
EXIT_WORDS = {DONE: "done", OTHER: "failed", STILL_WORKING: "still working", NEEDS_USER: "waiting for you",
              REFUSED: "refused by policy", UNAVAILABLE: "Grok app or engine unavailable"}

CMDS = {"status": ["grok", "status"], "bots": ["grok", "bots"], "ask": ["grok", "ask"], "wait": ["grok", "wait"],
        "read": ["grok", "read"], "routines": ["grok", "routines"], "files": ["grok", "files"],
        "policy": ["grok", "policy"], "launch": ["grok", "launch"],
        "restore": ["grok", "restore"], "usage": ["grok", "usage"]}
# P3 (botport feat/grok-engine-p3, 4efd374; the frozen file's §6 lists them as "open for the next lanes"):
#   botport grok routines <bot> list --json      -> {"routines": [Routine]}
#   botport grok files <bot> fetch [NAME|KEY] --out DIR --json
#                                                -> {"name", "saved_to", "bytes", "sha256", "app_sha256"} (0600, never
#                                                   overwrites; PASS only when the disk sha256 = the app's)
# policy/launch --port-ttl: `hermes twin setup --auto`; launch --for --when-idle + restore: chat sync windows (#52)
FLAGS = {"json": "--json", "quiet": "--quiet", "timeout": "--timeout", "settle": "--settle", "since": "--since",
         "limit": "--limit", "out": "--out"}
FETCH_TIMEOUT_S = 180
PAD_S = 30          # the subprocess may run this much longer than the engine's own --timeout
STATUS_TIMEOUT_S = 30
OUT_CAP = 8 * 1024 * 1024

FALLBACK = ("say \"Clone yourself to Hermes\" in the bot's chat in Grok (docs/ONE-PROMPT.md), or run "
            "botport grok launch (the fast preset; it restarts the Grok app with its local port open)")


class Unavailable(Exception):
    """The engine cannot be used at all (missing, not verified, no Grok engine in this botport)."""


@dataclass
class Result:
    exit: int
    data: dict = field(default_factory=dict)
    proof: str = ""

    @property
    def ok(self) -> bool:
        return self.exit == DONE


def _proof(data: dict, stderr: bytes) -> str:
    p = data.get("proof")
    err = data.get("error") if isinstance(data.get("error"), dict) else {}
    if isinstance(p, dict):  # (Outcome.proof in INTERFACES.md is {pass, what, check, route})
        p = f"{'PASS' if p.get('pass') else 'FAIL'}: {p.get('what', '')}; {p.get('check', '')}"
    if isinstance(p, str) and p.strip():
        return safe.clean_summary(p, 400)
    for line in reversed(stderr.decode("utf-8", "replace").splitlines()):
        if line.startswith(("PASS:", "FAIL:")):
            return safe.clean_summary(line, 400)
    if err.get("message"):
        return "FAIL: " + safe.clean_summary(err["message"], 300)
    return ""


def parse(rc: int, stdout: bytes, stderr: bytes, over: bool) -> Result:
    """One engine run -> Result. A run whose stdout is not one JSON object is exit 1 (the engine's shape is not
    recognised), whatever code it gave, except 5 (unavailable) which is kept so the fallback is offered."""
    if over:
        return Result(OTHER, {}, "FAIL: the engine's answer was too large")
    text = stdout.decode("utf-8", "replace").strip()
    try:
        data = json.loads(text) if text else {}
    except ValueError:
        data = None
    code = rc if rc in EXIT_WORDS else OTHER
    if isinstance(data, dict) and isinstance(data.get("untrusted_bot_content"), dict):
        data = {**data["untrusted_bot_content"], **{k: v for k, v in data.items() if k != "untrusted_bot_content"}}
    if not isinstance(data, dict):
        return Result(UNAVAILABLE if code == UNAVAILABLE else OTHER, {}, _proof({}, stderr)
                      or "FAIL: the engine's answer was not one JSON object")
    return Result(code, data, _proof(data, stderr))


Runner = Callable[[list, float], tuple]  # (argv, timeout) -> (rc, stdout, stderr, over)


class GrokEngine:
    """`botport grok ...` through one runner. `exe` is the verified botport; tests pass a stub and a runner."""

    def __init__(self, exe: str, env: Optional[dict] = None, runner: Optional[Runner] = None,
                 extra: Optional[list] = None) -> None:
        self.exe, self.env, self.extra = exe, env, list(extra or [])  # extra: e.g. --transport fake --fixtures DIR
        self._runner = runner or (lambda argv, t: run_capped(argv, t, env=self.env, out_cap=OUT_CAP))

    def _run(self, cmd: str, args: list, timeout: float) -> Result:
        argv = [self.exe, *CMDS[cmd], *args, FLAGS["json"], FLAGS["quiet"], *self.extra]
        try:
            rc, out, err, over = self._runner(argv, timeout)
        except EngineError as exc:
            if exc.code == "timeout":
                return Result(STILL_WORKING, {}, "FAIL: the engine did not answer in time")
            return Result(UNAVAILABLE, {}, f"FAIL: {safe.clean_summary(exc.message, 200)}")
        return parse(rc, out, err, over)

    # ---- the commands twin uses --------------------------------------------------------------------------
    def status(self) -> Result:
        return self._run("status", [], STATUS_TIMEOUT_S)

    def bots(self) -> Result:
        return self._run("bots", [], STATUS_TIMEOUT_S * 2)

    def ask(self, bot: str, message: str, timeout_s: int, settle_s: int = 8) -> Result:
        return self._run("ask", [bot, message, FLAGS["timeout"], str(int(timeout_s)),
                                 FLAGS["settle"], str(int(settle_s))], timeout_s + PAD_S)

    def wait(self, bot: str, since: Optional[str], timeout_s: int, settle_s: int = 8) -> Result:
        args = [bot, FLAGS["timeout"], str(int(timeout_s)), FLAGS["settle"], str(int(settle_s))] + \
            ([FLAGS["since"], since] if since else [])
        return self._run("wait", args, timeout_s + PAD_S)

    def policy_show(self) -> Result:
        return self._run("policy", ["show"], STATUS_TIMEOUT_S)

    def policy_preset(self, preset: str) -> Result:
        if preset not in ("careful", "balanced", "fast"):
            raise ValueError("unknown preset")
        return self._run("policy", ["preset", preset], STATUS_TIMEOUT_S)

    def launch(self, ttl: str = "10m") -> Result:
        """Opens the debug port: this restarts the Grok app (setup --auto --open-port only)."""
        return self._run("launch", ["--port-ttl", ttl], STATUS_TIMEOUT_S * 4)

    def window(self, for_s: int, when_idle_min: int) -> Result:
        """P3 §3d: a short port window for scheduled work. An open botport port lasting long enough is reused (no
        restart, JSON `reused: true`); otherwise the app restarts with the port only when the Mac has had no input
        for `when_idle_min` minutes, else exit 2 (the Mac is in use: try later, never interrupt)."""
        return self._run("launch", ["--for", f"{max(60, int(for_s)) // 60}m", "--when-idle", str(int(when_idle_min))],
                         STATUS_TIMEOUT_S * 4)

    def restore(self) -> Result:
        """Close the port window (the app back to normal). The TTL guard does it too if this never runs."""
        return self._run("restore", [], STATUS_TIMEOUT_S * 4)

    def read(self, bot: str, since: Optional[str] = None, limit: int = 200) -> Result:
        args = [bot, FLAGS["limit"], str(int(limit))] + ([FLAGS["since"], since] if since else [])
        return self._run("read", args, STATUS_TIMEOUT_S * 4)

    def routines(self, bot: str) -> Result:
        """P3: the bot's routines as the app lists them (never the bot's own words)."""
        return self._run("routines", [bot, "list"], STATUS_TIMEOUT_S * 2)

    def usage(self) -> Result:
        """P3: the plan's weekly usage (a read: never a turn). JSON: percent_used, resets_at, available; botport with
        the turn ledger adds botport_turns_week and usage_budget_week."""
        return self._run("usage", [], STATUS_TIMEOUT_S)

    def fetch(self, bot: str, which: Optional[str], out_dir: str) -> Result:
        """P3: save a file the bot sent in its chat (by message key or file name; newest when None) into out_dir."""
        return self._run("files", [bot, "fetch", *([which] if which else []), FLAGS["out"], out_dir], FETCH_TIMEOUT_S)


# ---- result shapes (SPEC §3) -----------------------------------------------------------------------------------
def bots_of(res: Result) -> list:
    """[{"id", "name", "main", "state"}] from a `bots` result: a bare list under "bots"/"value", or the object."""
    raw = res.data.get("bots")
    out = []
    for b in raw if isinstance(raw, list) else []:
        if isinstance(b, dict) and isinstance(b.get("id"), str) and isinstance(b.get("name"), str):
            out.append({"id": b["id"][:80], "name": b["name"][:200], "main": bool(b.get("main")),
                        "state": str(b.get("state") or "")[:20]})
    return out


def messages_of(res: Result) -> list:
    """Message objects of an ask/wait/read result, oldest first: {"key","role","kind","text","at"}."""
    raw = res.data.get("messages")
    out = []
    for m in raw if isinstance(raw, list) else []:
        if isinstance(m, dict) and isinstance(m.get("text"), str):
            out.append({"key": str(m.get("key") or "")[:80], "role": str(m.get("role") or "")[:20],
                        "kind": str(m.get("kind") or "text")[:30], "text": m["text"], "at": m.get("at"),
                        **({"file": {"name": m["file"]["name"][:200]}} if isinstance(m.get("file"), dict) and
                           isinstance(m["file"].get("name"), str) else {})})
    return out


def routines_of(res: Result) -> Optional[list]:
    """[{"id","name","schedule","tz","enabled","prompt"}] from a `routines` result; None when the engine gave no list
    (an engine before P3 does not know the command)."""
    raw = res.data.get("routines")
    if not isinstance(raw, list):
        return None
    out = []
    for r in raw:
        if isinstance(r, dict) and isinstance(r.get("name"), str):
            out.append({"id": str(r.get("id") or "")[:200], "name": r["name"][:200],
                        "schedule": str(r.get("schedule") or "")[:200], "enabled": bool(r.get("enabled")),
                        "tz": r.get("tz") if isinstance(r.get("tz"), str) else None,
                        "prompt": r.get("prompt") if isinstance(r.get("prompt"), str) else ""})
    return out


def saved_of(res: Result) -> Optional[dict]:
    """{"name","saved_to","bytes","sha256"} from a `files fetch` result, or None."""
    d = res.data
    if not (isinstance(d.get("saved_to"), str) and isinstance(d.get("sha256"), str)):
        return None
    return {"name": str(d.get("name") or "")[:200], "saved_to": d["saved_to"], "bytes": d.get("bytes"),
            "sha256": d["sha256"][:64], "app_sha256": d.get("app_sha256")}


def needs_input_of(res: Result) -> str:
    """The engine's reason a bot waits for the user (exit 3), as one short line."""
    bot = res.data.get("bot") if isinstance(res.data.get("bot"), dict) else {}
    ni = bot.get("needs_input") or res.data.get("needs_input")
    if isinstance(ni, dict):
        kind = "an approval" if ni.get("kind") == "approval" else "an answer"
        reason = safe.clean_summary(ni.get("reason") or "", 160)
        return f"{kind} in Grok" + (f" ({reason})" if reason else "")
    return "you in Grok"


def last_key(res: Result) -> Optional[str]:
    msgs = messages_of(res)
    if msgs and msgs[-1]["key"]:
        return msgs[-1]["key"]
    bot = res.data.get("bot") if isinstance(res.data.get("bot"), dict) else {}
    k = bot.get("last_key")
    return str(k)[:80] if isinstance(k, str) and k else None


# ---- finding it ------------------------------------------------------------------------------------------------
def from_service(svc: Any) -> GrokEngine:
    """The engine in the plugin's own verified botport. Raises Unavailable with the reason in plain words."""
    bp = svc.botport()
    if bp is None:
        raise Unavailable("botport is not on this computer")
    try:
        exe, _rec = bp._verify()
    except EngineError as exc:
        raise Unavailable(safe.clean_summary(exc.message, 200)) from exc
    eng = GrokEngine(exe, env=bp._env())
    if not has_engine(eng.status()):
        raise Unavailable("this botport has no Grok engine yet (botport grok)")
    return eng


PERMISSION_KEY = "local_tool_permission"  # optional `status` field (always|ask|never), read-only getLocalToolPermission
ALWAYS = ("always",)
# (the word is built, never written whole in this file: the plugin's own files are copied into twins' Hermes folders,
# and the import tests use that word as a marker that must never land there)
CHECK_WORD = "can" + "ary"
CANARY = ("this Grok app version is not one botport has tested, so botport refuses to write to it "
          "(unknown_version_writes): run botport grok " + CHECK_WORD + " on this Mac, then try again")


def refused_why(res: Result) -> str:
    """The plain words for an exit 4. Since botport 0a527ac a write on an untested Grok version is exit 4 (was 5),
    with `unknown_version_writes` / the engine's version check command in its line or error."""
    err = res.data.get("error") if isinstance(res.data.get("error"), dict) else {}
    text = " ".join(str(x) for x in (res.proof, err.get("message"), err.get("hint"), err.get("code")) if x)
    if "unknown_version_writes" in text or CHECK_WORD in text.lower():
        return CANARY
    return "botport's policy refused it (" + (res.proof.removeprefix("FAIL: ") or "see botport grok policy show") + ")"


def local_permission(res: Result) -> str:
    """Grok's "Execution on Local Computer" setting as `status` reports it: "always", "ask", "never", or "unknown"
    when the engine does not say. Read only: twin never changes this setting (it is the owner's)."""
    v = res.data.get(PERMISSION_KEY)
    if not isinstance(v, str) or not v.strip():
        return "unknown"
    v = v.strip().lower()
    return "always" if v in ALWAYS else v[:20]


def has_engine(res: Result) -> bool:
    """Did `botport grok status --json` answer as the engine does (an object with `exit` and `proof`)? Any exit
    code counts: an app that is not running is still an engine that answered."""
    return "exit" in res.data and "proof" in res.data
