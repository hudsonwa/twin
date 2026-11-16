"""A Grok bot's own export (`grok-bot-export/1`), read as untrusted data (zero-touch issues 04-06).

`hermes twin from-hermes` asks a Grok bot, through botport's Grok engine, for the three things the engine cannot
read itself: its instructions, its memory and its skills (REQUEST). History and routines are never taken from the
bot's text: they come from the engine (`botport grok read`, `botport grok routines`).

The answer is a bot's writing, and the bot's chat can hold web pages it read, other people's words and other bots'
skills. So everything here is deterministic code, and nothing of the answer reaches the Hermes agent that called
from-hermes except a fixed PASS/FAIL line built from counts and names that passed `SAFE_NAME`:

- `from_reply(messages)`: the bot's text after the request must hold exactly ONE fenced ```json block and no line
  that starts with PASS:/FAIL: (a reply that pretends to be our own proof line). A bot that also sent a file, two
  blocks, no block, or a truncated block -> Bad.
- `validate(doc, bot_name)`: a strict schema. Unknown fields at any level, a wrong type, a missing field, more
  entries or longer texts than the caps below -> Bad. `bot_name` must be the name the ENGINE reported for the bot
  (the twin is keyed by the engine's bot, never by what the bot wrote about itself), so `../../default` or `default`
  never names a profile. A skill name must be plain ASCII (`SAFE_NAME`: letters, digits, space, `._-`, 1-64, no
  leading dot) and unique: names become files in the twin's folder, so control characters, ANSI escapes, newlines,
  slashes and `..` are refused, never cleaned up.
- Secrets: every text is checked in memory before anything is written. A text that looks like it holds a password
  or key -> Bad (nothing written, the line names where, never the value). A skill whose body holds the bot's own
  redaction mark ("[REDACTED ...]") is held back (not imported) and named in the PASS line: its key is not there to
  be filled, and a skill without it would not work.
- A text that tells Hermes to run this plugin's or botport's own commands (`hermes twin ...`, `botport ...`) is
  refused (Bad): a Grok bot's genuine instructions or skills have no reason to drive the twin machinery. Any other
  text ("run this command ...") is data: it is only ever written into the twin's own profile, nothing runs it.
- Skills made by other bots (06): Grok's skills look account-wide, so a bot's export lists skills other bots made.
  The request asks the bot to mark each skill `"mine": true` only when it made it; `split_skills` keeps only those
  by default. A skill several bots claim as theirs goes into each claimant's twin and is named in the PASS line
  (nobody is asked to arbitrate). The rest are named as "shared, not imported" and come in only with
  --shared-skills. A skill that fails the checks above and is NOT marked mine is skipped and named (one odd
  account-wide skill must not block every bot's export); the bot's own still makes the export Bad.

Nothing here writes a file, logs a text or keeps the raw answer: callers get the validated dict and drop the rest.
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional

from . import secrets as _secrets

FORMAT = "grok-bot-export/1"
EXPORT_FILE = "twin-export.json"   # the name the request asks the bot to give a file it sends
INLINE_MAX = 20_000                # characters: above this the request asks the bot for the file route
MAX_BYTES = 1_500_000              # a whole export (reply text or fetched file), bytes
INSTRUCTIONS_MAX = 200_000         # characters
DESCRIPTION_MAX = 1_000
SKILLS_MAX, SKILL_MAX = 100, 64_000
MEMORY_MAX, MEMORY_ITEM_MAX = 500, 4_000
NAME_MAX = 100

TOP = {"format": str, "bot_name": str, "instructions": str, "skills": list, "memory": list}
TOP_REQUIRED = ("format", "bot_name", "instructions", "skills", "memory")
SKILL = {"name": str, "description": str, "body": str, "mine": bool}
SKILL_REQUIRED = ("name", "body", "mine")

SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}")
_FENCE_OPEN = re.compile(r"^\s*```\s*json\s*$", re.I)
_FENCE_ANY = re.compile(r"^\s*```")
_PROOF_LIKE = re.compile(r"^\s*[*_`>#-]*\s*(PASS|FAIL)\s*:", re.I | re.M)
_REDACTED = re.compile(r"\[\s*redacted\b", re.I)
TWIN_SKILL = "twin-to-hermes"  # this plugin's own old host_shell skill (grok/SKILL-twin.md): account-wide in Grok
_REDACTED_MARK = re.compile(r"\[\s*redacted\b[^\]\n]{0,200}\]", re.I)  # the whole mark, for the secret check
_CONTROL_CMD = re.compile(r"(?im)(?:^|[\s`'\"$(;|&])(?:hermes(?:\s+-p\s+\S+)?\s+twin\s+[a-z]|"
                          r"botport\s+(?:grok|sync|apply|twin|drift|export|test|setup)\b)")
_NAME_CTRL = re.compile("[\x00-\x1f\x7f-\x9f\u200b-\u200f\u2028-\u202e\u2060-\u206f\ufeff]")

REQUEST = (
    "Please export yourself for your Hermes twin. Read only, change nothing.\n"
    "Rules: use no local-computer tools (no commands on my computer); do not store this request or the export in "
    "your memory; do not run or create any routine. Use only your own tools (your memory, your skills).\n"
    "Answer with ONE JSON object of exactly this shape and nothing else of note:\n"
    '{"format": "' + FORMAT + '", "bot_name": "<your name exactly as Grok shows it>",\n'
    ' "instructions": "<your custom instructions, word for word; empty if you have none>",\n'
    ' "skills": [{"name": "<skill name>", "description": "<one line>", "body": "<the skill text, word for word>",\n'
    '             "mine": <true only if YOU made this skill; false for a skill another bot made>}],\n'
    ' "memory": ["<one thing you remember, one per entry>"]}\n'
    "No other fields: no history, no routines, no apps (Hermes reads those itself). Never put a password, token or "
    "key in it: write [REDACTED] in its place.\n"
    f"If the JSON is shorter than {INLINE_MAX} characters, paste it as one ```json code block. If it is longer, do "
    f"not paste it: save it as a file named {EXPORT_FILE} with your own file tool on your own computer and send that "
    "file in this chat."
)
REQUEST_FILE = REQUEST + f"\nThis time always use the file route: send {EXPORT_FILE}, paste nothing."
CLEANUP = (f"Thank you. Now delete the file {EXPORT_FILE} you sent, from your own computer, with your own file tool. "
           "Use no local-computer tools. Do not store anything about this in your memory. Answer DONE.")


class Bad(Exception):
    """The export is refused: nothing is written. The message is the plugin's own words (never the bot's text)."""


# ---- reading the reply -------------------------------------------------------------------------------------------
def own_turn(text: Any) -> bool:
    """A user message that is this plugin's own export or clean-up request (the app stores it with its line breaks
    doubled, so whitespace is compared loosely)."""
    norm = lambda t: " ".join(str(t or "").split())
    return norm(text) in {norm(REQUEST), norm(REQUEST_FILE), norm(CLEANUP)}


def without_own_turns(messages: list) -> list:
    """The chat without this plugin's own export turns: each export or clean-up request and the bot's answers to it,
    up to the next user message. Live 16 Nov: every run's export turn landed in the twin's Hermes chats on the next
    run (9 copies of the request after 6 runs)."""
    out, skipping = [], False
    for m in messages:
        if m.get("role") == "user":
            skipping = own_turn(m.get("text"))
        if not skipping:
            out.append(m)
    return out


def bot_texts(messages: list) -> list:
    return [m.get("text") or "" for m in messages if isinstance(m, dict) and m.get("role") in ("bot", "assistant")]


def sent_files(messages: list) -> list:
    """The files the bot sent in these messages (engine `Message.file`, P3: {"name", "path"})."""
    out = []
    for m in messages:
        f = m.get("file") if isinstance(m, dict) and m.get("role") in ("bot", "assistant") else None
        if isinstance(f, dict) and isinstance(f.get("name"), str):
            out.append({"key": str(m.get("key") or "")[:80], "name": f["name"][:200]})
    return out


def from_reply(messages: list) -> str:
    """The JSON text of the one fenced ```json block in the bot's reply. Raises Bad."""
    texts = bot_texts(messages)
    joined = "\n".join(texts)
    if len(joined.encode("utf-8", "replace")) > MAX_BYTES:
        raise Bad(f"the reply is larger than {MAX_BYTES} bytes")
    if _PROOF_LIKE.search(_outside_blocks(joined)):
        raise Bad("the reply holds a line that looks like a PASS or FAIL line; Hermes writes those itself")
    blocks = []
    for text in texts:
        lines = text.split("\n")
        i = 0
        while i < len(lines):
            if _FENCE_OPEN.match(lines[i]):
                end = next((j for j in range(len(lines) - 1, i, -1) if lines[j].strip() == "```"), None)
                if end is None:
                    raise Bad("the reply's JSON block is not closed (cut off?)")
                blocks.append("\n".join(lines[i + 1:end]))
                if any(_FENCE_OPEN.match(x) for x in lines[i + 1:end]):
                    raise Bad("the reply holds more than one JSON block")
                i = end + 1
                continue
            i += 1
    if not blocks:
        raise Bad("the reply holds no ```json block")
    if len(blocks) > 1:
        raise Bad("the reply holds more than one JSON block")
    return blocks[0]


def from_reply_has_block(messages: list) -> bool:
    return any(_FENCE_OPEN.match(line) for t in bot_texts(messages) for line in t.split("\n"))


def _outside_blocks(text: str) -> str:
    """The text with every fenced block taken out (a PASS-like line inside the JSON is the JSON's own business)."""
    out, inside = [], False
    for line in text.split("\n"):
        if _FENCE_ANY.match(line):
            inside = not inside
            continue
        if not inside:
            out.append(line)
    return "\n".join(out)


def loads(text: Any) -> dict:
    """Strict JSON (no repair, no guessing) of one object. Raises Bad."""
    if isinstance(text, bytes):
        if len(text) > MAX_BYTES:
            raise Bad(f"the export is larger than {MAX_BYTES} bytes")
        try:
            text = text.decode("utf-8")
        except UnicodeDecodeError:
            raise Bad("the export is not UTF-8 text") from None
    if not isinstance(text, str) or not text.strip():
        raise Bad("the export is empty")
    if len(text.encode("utf-8", "replace")) > MAX_BYTES:
        raise Bad(f"the export is larger than {MAX_BYTES} bytes")
    try:
        doc = json.loads(text, parse_constant=_no_constant)
    except (ValueError, RecursionError):
        raise Bad("the export is not valid JSON (cut off or malformed)") from None
    if not isinstance(doc, dict):
        raise Bad("the export is not one JSON object")
    return doc


def _no_constant(name: str) -> Any:
    raise ValueError(name)  # NaN / Infinity are not JSON


# ---- the schema ----------------------------------------------------------------------------------------------------
def _fields(obj: dict, spec: dict, required: tuple, where: str) -> None:
    extra = sorted(k for k in obj if k not in spec)
    if extra:
        raise Bad(f"{where} has fields the format does not have ({len(extra)})")
    for k in required:
        if k not in obj:
            raise Bad(f"{where} has no \"{k}\"")
    for k, typ in spec.items():
        if k in obj and not (isinstance(obj[k], typ) and not (typ is not bool and isinstance(obj[k], bool))):
            raise Bad(f"{where}: \"{k}\" has the wrong type")


def _cap(text: str, cap: int, where: str) -> str:
    if len(text) > cap:
        raise Bad(f"{where} is longer than {cap} characters")
    if "\x00" in text:
        raise Bad(f"{where} holds a NUL character")
    return text


def same_name(a: str, b: str) -> bool:
    return " ".join(a.split()).casefold() == " ".join(b.split()).casefold()


def validate(doc: dict, bot_name: str) -> dict:
    """The export checked against the schema, the caps, the name rules and the secret check. -> a clean dict:
    {"bot_name", "instructions", "skills": [{"name","description","body","mine"}], "memory": [str],
     "held_back": [skill names], "memory_redacted": int}. Raises Bad; nothing is written either way."""
    if not isinstance(doc, dict):
        raise Bad("the export is not one JSON object")
    _fields(doc, TOP, TOP_REQUIRED, "the export")
    if doc["format"] != FORMAT:
        raise Bad(f"the export's format is not {FORMAT}")
    name = doc["bot_name"]
    if len(name) > NAME_MAX or _NAME_CTRL.search(name) or "/" in name or "\\" in name or ".." in name:
        raise Bad("the export's bot_name is not a plain name")
    if not same_name(name, bot_name):
        raise Bad("the export's bot_name is not the bot Hermes asked (the twin is keyed by the engine's bot)")
    ins = _cap(doc["instructions"], INSTRUCTIONS_MAX, "the instructions")
    if len(doc["skills"]) > SKILLS_MAX:
        raise Bad(f"the export lists more than {SKILLS_MAX} skills")
    if len(doc["memory"]) > MEMORY_MAX:
        raise Bad(f"the export lists more than {MEMORY_MAX} memories")
    skills, seen, mine_seen, skipped, why = [], set(), set(), [], {}
    for i, s in enumerate(doc["skills"], 1):
        theirs = isinstance(s, dict) and s.get("mine") is False
        try:
            # names must be unique among the bot's own skills; another bot's skill is checked against every name
            sk = _skill(s, i, seen if theirs else mine_seen)
        except Bad:
            # Grok's skills are account-wide: one odd skill another bot made must not block this bot's export
            # (a live test: one bot's `../../zt-evil` failed every bot's). The bot's own (or unmarked) still FAILs.
            if theirs:
                skipped.append(_label(s, i))
                why[skipped[-1]] = _skip_reason(s)
                continue
            raise
        seen.add(sk["name"].casefold())
        if not theirs:
            mine_seen.add(sk["name"].casefold())
        skills.append(sk)
    # another bot's skill listed before one of this bot's own with the same name: the bot's own wins
    clash = [sk for sk in skills if not sk["mine"] and sk["name"].casefold() in mine_seen]
    skipped += [sk["name"] for sk in clash]
    why.update({sk["name"]: "same name as one of this bot's own" for sk in clash})
    skills = [sk for sk in skills if sk not in clash]
    memory = []
    for i, m in enumerate(doc["memory"], 1):
        if not isinstance(m, str):
            raise Bad(f"memory {i} is not text")
        memory.append(_cap(m, MEMORY_ITEM_MAX, f"memory {i}"))
    _no_secrets_or_commands(ins, [s for s in skills if s["mine"]], memory)
    others = []
    for s in skills:  # another bot's skill that fails the secret or command check: skipped and named, not a FAIL
        if s["mine"]:
            others.append(s)
            continue
        try:
            _no_secrets_or_commands(None, [s], [])
            others.append(s)
        except Bad as exc:
            skipped.append(s["name"])
            why[s["name"]] = ("runs the plugin's own commands" if "own commands" in str(exc)
                              else "looks like it holds a password or key")
    skills = others
    held = [s["name"] for s in skills if _REDACTED.search(s["body"]) or _REDACTED.search(s["description"])]
    kept_mem = [m for m in memory if m.strip() and not _REDACTED.search(m)]
    return {"bot_name": name, "instructions": ins, "skills": [s for s in skills if s["name"] not in held],
            "memory": kept_mem, "held_back": held, "memory_redacted": sum(1 for m in memory if _REDACTED.search(m)),
            "skipped": skipped, "skipped_why": why}


def _skill(s: Any, i: int, seen: set) -> dict:
    """One skill entry checked (schema, plain unique name, caps). Raises Bad."""
    if not isinstance(s, dict):
        raise Bad(f"skill {i} is not an object")
    _fields(s, SKILL, SKILL_REQUIRED, f"skill {i}")
    sname = s["name"]
    if not SAFE_NAME.fullmatch(sname) or sname != sname.strip() or ".." in sname:
        raise Bad(f"skill {i}'s name is not a plain name (letters, digits, space, . _ -; at most 64)")
    if sname.casefold() in seen:
        raise Bad(f"two skills are named {sname}")
    body = _cap(s["body"], SKILL_MAX, f"skill {sname}")
    if not body.strip():
        raise Bad(f"skill {sname} has no text")
    return {"name": sname, "description": _cap(s.get("description", ""), DESCRIPTION_MAX,
                                               f"skill {sname}'s description"),
            "body": body, "mine": s["mine"]}


def _label(s: dict, i: int) -> str:
    """How a skipped skill is named in the PASS line: its name when that is a plain name, else its place."""
    n = s.get("name")
    return n if isinstance(n, str) and SAFE_NAME.fullmatch(n) and ".." not in n else f"skill {i}"


def _skip_reason(s: Any) -> str:
    """Why another bot's skill entry was not taken, in words (never its text)."""
    if not isinstance(s, dict):
        return "not a skill entry"
    n = s.get("name")
    if not (isinstance(n, str) and SAFE_NAME.fullmatch(n) and ".." not in n):
        return "no plain name"
    if not isinstance(s.get("body"), str) or not s["body"].strip():
        return "no text"
    return "not a valid skill entry"


def skipped_words(names: list, why: Optional[dict] = None, limit: int = 8) -> str:
    """"odd-one (no text), skill 8 (no plain name)": each skipped entry by name or place, with its reason."""
    why = why or {}
    names = [n for n in names if isinstance(n, str) and SAFE_NAME.fullmatch(n)]
    shown = [f"{n} ({why[n]})" if why.get(n) else n for n in names[:limit]]
    more = len(names) - limit
    return ", ".join(shown) + (f" and {more} more" if more > 0 else "")


def _no_secrets_or_commands(ins: Optional[str], skills: list, memory: list) -> None:
    parts = [("the instructions", ins)] if ins is not None else []
    # This plugin's own twin skill, listed by a bot that did not make it, is never imported (split_skills), so its
    # text (it names `hermes twin from-grok`, and an install path) is not checked: in a live test it failed every
    # export on an account that once had it.
    parts += [(f"skill {s['name']}", s["description"] + "\n" + s["body"]) for s in skills if not _twin_skill(s)]
    parts += [(f"memory {i}", m) for i, m in enumerate(memory, 1)]
    for where, text in parts:
        # The bot's own redaction mark is not a secret ("KEY=[REDACTED]" was a FAIL live, 16 Nov): such a text is
        # held back by validate(); anything else that still looks like a key fails.
        checked = _REDACTED_MARK.sub("${REDACTED}", text)  # (a reference, never a value)
        if _secrets.has_secret(checked):
            # kind and line only, never the value (audit 2026-11-16: "memory 2 looks like ..." gave the owner no
            # way to tell a link from a key without reading the text)
            found = _secrets.detect_secrets(checked)
            what = "; ".join(f"line {f['line']}: {f['what']}" for f in found[:3])
            raise Bad(f"{where} looks like it holds a password or key ({what}; not shown); nothing was written")
        if _CONTROL_CMD.search(text):
            raise Bad(f"{where} tells Hermes to run Grok Bot Twin's or botport's own commands; refused as an "
                      "export (nothing was run or written)")


def _twin_skill(s: dict) -> bool:
    return s["name"].casefold() == TWIN_SKILL and s["mine"] is not True


def parse(text_or_bytes: Any, bot_name: str) -> dict:
    return validate(loads(text_or_bytes), bot_name)


# ---- skills made by other bots (06) ------------------------------------------------------------------------------
def split_skills(clean: dict, take_shared: bool = False) -> tuple:
    """(skills to import, names of skills not imported). Grok's skills are account-wide, so every bot lists them
    all: a skill comes in only when this bot marked it mine (or with take_shared). A skill several bots claim
    goes into each claimant's twin (claimed_by_many names them; nobody is asked to arbitrate)."""
    own, shared = [], []
    for s in clean["skills"]:
        if not _twin_skill(s) and (take_shared or s["mine"]):
            own.append(s)
        else:
            shared.append(s["name"])
    return own, shared


def claimed_by_many(cleans: list) -> set:
    """Skill names (casefolded) that more than one export marks `mine`."""
    count: dict = {}
    for c in cleans:
        for n in {s["name"].casefold() for s in c["skills"] if s["mine"]}:
            count[n] = count.get(n, 0) + 1
    return {n for n, k in count.items() if k > 1}


def shown_names(names: list, limit: int = 8) -> str:
    """Names for the PASS line: they already passed SAFE_NAME; capped in number."""
    names = [n for n in names if SAFE_NAME.fullmatch(n)]
    more = len(names) - limit
    return ", ".join(names[:limit]) + (f" and {more} more" if more > 0 else "")


def to_import_args(clean: dict, skills: list) -> dict:
    """The arguments of one_prompt.twin_from_grok (the existing importer) for this export."""
    return {"instructions": clean["instructions"],
            "skills": [{"name": s["name"], "description": s["description"], "instructions": s["body"]}
                       for s in skills],
            "memory": list(clean["memory"])}


def routines_meta(routines: list) -> list:
    """Engine Routine objects (`botport grok routines <bot>`) -> the importer's routines_meta (all arrive paused)."""
    out = []
    for r in routines if isinstance(routines, list) else []:
        if not isinstance(r, dict) or not isinstance(r.get("name"), str):
            continue
        out.append({k: v for k, v in (("id", r.get("id")), ("name", r["name"]), ("instruction", r.get("prompt")),
                                     ("trigger", "schedule"), ("schedule_cron", r.get("schedule")),
                                     ("timezone", r.get("tz"))) if isinstance(v, str)})
    return out
