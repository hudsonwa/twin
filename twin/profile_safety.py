"""Safe twin-profile defaults instead of mid-run questions (zero-touch issue 10).

A twin's Hermes profile gets one of four tool presets, chosen by rule, never by asking:

- ``parity`` (the default, twin#71): the twin can do what its Grok bot can do. Every Grok bot has a browser, web and
  X search, a shell and computer use (Grok's "Execution on Local Computer"), files, code execution and image
  generation (``GROK_CAPABILITIES``), so none of those toolsets is disabled, on any platform (the desktop app and
  Telegram alike). Safety stays where it is cheap, the hard floors of every preset: approvals manual (a risky
  action asks first, in the chat it came from: Telegram's buttons or /approve), and deny when nobody is there
  (cron, unattended, single query); no agent scheduling and no delegation (the twin's routines come from its Grok
  bot); no environment passed to a terminal. The owner narrows it with ``standard`` or ``strict``.
- ``strict``: for a risky bot. Only knowledge, memory, session_search and todo on every platform; every other
  toolset disabled; approvals manual (and deny when nobody is there: cron, unattended, single query); no agent
  scheduling; no environment passed to a terminal; MCP servers limited to the names in the plugin setting
  ``twin_safe_mcp`` (none by default); the twin profile's own Telegram off (twins are reached through the owner's
  existing Hermes bot, twin/tg_route.py).
- ``standard``: every other twin. No toolset that opens a shell or a socket (terminal, code execution, delegation,
  cron jobs, browser, computer use), and by default none that can send what the twin knows out without an approval:
  web, x_search, file, image_gen, and MCP servers other than those named in ``twin_safe_mcp``. Approvals manual,
  no agent scheduling, no environment passthrough; the rest of the profile's tools stay as they are. The owner
  widens one at a time: ``hermes twin safety TWIN standard --allow web`` (web, x_search, file, image_gen, mcp).
- ``open``: the owner widened it on purpose. Nothing is enforced; the choice is recorded.

The rule: every twin gets ``parity`` (fast by default, safety opt-in). The risky words its instructions, skills
or routines mention (shell, ssh, terminal, servers, trading, brokers, wallets or credentials: ``RISKY``) are
recorded and named, never silently acted on; ``choose`` still says which narrower preset they suggest (``strict``
for those words, else ``standard``). The plugin's own skill pack is not the bot's text and is never read for
them. Narrowing or widening is one command: ``hermes twin safety TWIN strict|standard`` (``--allow TOOLSET``),
``parity`` or ``open``. A twin whose preset the rule chose before 0.5.1 (standard or strict) is moved to parity
once by ``hermes twin setup --auto`` (``migrate_to_parity``), which says what changed; an owner's choice is kept. Every write keeps a dated copy of the
config next to it (the newest BACKUPS_KEPT), and the first one keeps ``.twin-pre-safety.yaml``, put back when
twinning stops if nothing changed config.yaml since.

Model: twins answer with a local model by default. A twin whose model is not local FAILs the check until a model
policy is recorded (``--model-policy any``), so the check never asks mid-run and never passes silently.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import re
import shutil
import time
from pathlib import Path
from typing import Any, Iterable, Optional

from . import safe, skill_pack, store

PRESETS = ("parity", "strict", "standard", "open")
DEFAULT_PRESET = "parity"
# twin#71: what every Grok bot can do, as Hermes toolsets, in the order the PASS line names them: (toolset, words,
# note). Grok gives each bot a browser, web and X search, code execution, files and image generation, and a shell
# and computer use through "Execution on Local Computer"; a risky action still asks first (approvals manual).
GROK_CAPABILITIES = (("browser", "browser", ""), ("web", "web", ""), ("x_search", "X search", ""),
                     ("terminal", "shell", "risky commands ask first"), ("file", "files", ""),
                     ("code_execution", "code", "risky code asks first"), ("image_gen", "image generation", ""),
                     ("computer_use", "computer use", "where this computer supports it; asks first"))
PARITY_ON = [t for t, _w, _n in GROK_CAPABILITIES]
# off in parity too (hard floors): the agent schedules nothing itself and starts no other agents; the twin's
# routines are its Grok bot's, imported switched off and run by twin
PARITY_OFF = ["cronjob", "delegation"]
PARITY_OFF_WHY = "agent scheduling and delegation (hard floor: the twin's routines come from its Grok bot)"
STRICT_ALLOWED = ["knowledge", "memory", "session_search", "todo"]
# toolsets that open a shell or a socket: off in every preset but "open"
SHELL_SOCKET = ["terminal", "code_execution", "delegation", "cronjob", "browser", "computer_use"]
# off in standard too, by default: tools that need no approval yet can send what the twin knows out (web, search,
# files, image generation) or reach anything (MCP servers). The owner widens one by one: `--allow web` ... `mcp`.
WIDENABLE = ["web", "x_search", "file", "image_gen", "mcp"]
STANDARD_DENIED = SHELL_SOCKET + [t for t in WIDENABLE if t != "mcp"]
STRICT_DISABLED = SHELL_SOCKET + [
    "file", "web", "x_search", "image_gen", "video", "video_gen", "vision", "kanban", "coding", "debugging",
    "project", "connections", "desktop_ui", "bot_room", "skills", "search", "catalog", "safe", "tts", "clarify",
    "context_engine", "onboarding", "discord", "discord_admin", "feishu_doc", "feishu_drive", "yuanbao"]
PLATFORMS = ["cli", "telegram", "cron", "api_server", "api-server", "acp", "webhook"]
REQUIRED_PLATFORMS = ("cli", "telegram", "cron", "api_server")

RISKY = ("shell", "ssh", "terminal", "bash", "zsh", "sudo", "command line", "command-line", "host_shell",
         "server", "deploy", "kubectl", "docker", "root access", "trading", "trade", "trader", "broker",
         "brokerage", "futures", "order entry", "place order", "portfolio", "wallet", "crypto", "exchange api",
         "password", "api key", "credential", "private key")
_RISKY_RE = re.compile(r"(?<![a-z])(" + "|".join(re.escape(w) for w in RISKY) + r")(?:s|es|ing|ed)?(?![a-z])",
                       re.IGNORECASE)
TEXT_CAP = 512 * 1024
STATE_FILE = "profile-safety.json"
BACKUP_NAME = ".twin-pre-safety.yaml"  # config.yaml as it was before the first safe defaults (put back on stop)
BACKUPS_KEPT = 5  # dated .pre-safety-* copies kept next to config.yaml (the newest)
LOCAL_PROVIDERS = {"ollama", "lmstudio", "lm-studio", "llamacpp", "llama.cpp", "vllm", "local", "mlx", "omlx"}


# ---- the rule --------------------------------------------------------------------------------------------------
def risky_words(texts: Iterable[Any]) -> list:
    """The risky words found in these texts, lower case, each once, in order of first sight."""
    seen: list = []
    for text in texts:
        if not isinstance(text, str):
            continue
        for m in _RISKY_RE.finditer(text[:TEXT_CAP]):
            w = m.group(1).lower()
            if w not in seen:
                seen.append(w)
    return seen


def choose(texts: Iterable[Any]) -> tuple:
    """(preset, words): "strict" with the words that chose it, else ("standard", [])."""
    words = risky_words(texts)
    return ("strict", words) if words else ("standard", [])


def _bundled_names(skills: Path) -> set:
    """Folder names Hermes lists in skills/.bundled_manifest ("name:hash" per line); empty when absent."""
    try:
        raw = (skills / ".bundled_manifest").read_text(encoding="utf-8", errors="replace")[:TEXT_CAP]
    except OSError:
        return set()
    return {ln.split(":", 1)[0].strip() for ln in raw.splitlines() if ln.strip() and not ln.startswith("#")}


def profile_texts(home: Path) -> list:
    """What the rule reads in a twin's profile: its instructions (SOUL.md), its skills, its routines' prompts and
    the Grok tools named in them. Hermes' own config.yaml is not read (its default toolsets would make every twin
    look risky). Capped; unreadable files are skipped."""
    out: list = []
    cands = [home / "SOUL.md", home / "cron" / "jobs.json"]
    skills = home / "skills"
    if skills.is_dir():
        bundled = _bundled_names(skills)
        for p in sorted(skills.rglob("SKILL.md"))[:200]:
            if skill_pack.is_pack_dir(p.relative_to(skills).parts[0]):
                continue  # twin#65: the plugin's own skill pack (twin-update names "terminal") is not the bot's
            if p.parent.name in bundled:
                continue  # Hermes' own bundled skills (listed in .bundled_manifest) are not the bot's either
            cands.append(p)
    total = 0
    for p in cands:
        try:
            if p.is_symlink() or not p.is_file():
                continue
            with open(p, "rb") as fh:
                raw = fh.read(TEXT_CAP)
        except OSError:
            continue
        total += len(raw)
        out.append(raw.decode("utf-8", "replace"))
        if total > 4 * TEXT_CAP:
            break
    return out


# ---- config ----------------------------------------------------------------------------------------------------
def _yaml():
    """Round-trip YAML (comments and order kept) when ruamel.yaml is there; else the plugin's own safe YAML."""
    try:
        from ruamel.yaml import YAML
        y = YAML()
        y.preserve_quotes = True
        y.width = 2 ** 31 - 1
        return "rt", y
    except Exception:
        from . import yamlio
        return "safe", yamlio.module()


def load_config(home: Path) -> dict:
    p = home / "config.yaml"
    if not p.is_file():
        return {}
    kind, y = _yaml()
    with open(p, encoding="utf-8") as fh:
        text = fh.read() if kind != "rt" else None
        if kind == "rt":
            fh.seek(0)
            data = y.load(fh)
        elif y is not None:
            data = y.safe_load(text)
        elif not text.strip():
            data = {}
        else:  # no YAML module (a test host; every Hermes ships one): only the plain block form write_config
            data = _read_block(text)  # writes then; anything else raises, so it is never overwritten with less
    return data if isinstance(data, dict) else {}


def _write_block(value: Any, indent: int = 0) -> str:
    pad = " " * indent
    if isinstance(value, dict):
        if not value:
            return pad + "{}\n" if indent else ""
        out = ""
        for k, v in value.items():
            key = json.dumps(str(k), ensure_ascii=False)
            out += (f"{pad}{key}:\n" + _write_block(v, indent + 2)) if isinstance(v, (dict, list)) and v else \
                f"{pad}{key}: {json.dumps(v, ensure_ascii=False)}\n"
        return out
    if isinstance(value, list):
        out = ""
        for v in value:
            if isinstance(v, (dict, list)) and v:
                raise RuntimeError("no YAML module in this Hermes to write a nested list")
            out += f"{pad}- {json.dumps(v, ensure_ascii=False)}\n"
        return out
    return pad + json.dumps(value, ensure_ascii=False) + "\n"


def _scalar(text: str) -> Any:
    text = text.strip()
    try:
        return json.loads(text)
    except ValueError:
        if text[:1] in "[{\"'&*!|>%@`":
            raise RuntimeError("no YAML module in this Hermes to read config.yaml")
        return text


def _read_block(text: str) -> dict:
    """The block form above (plus plain `key: value` / `- item` lines others append). Anything else raises."""
    root: dict = {}
    stack: list = [(-1, root)]  # (indent, container)
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    for i, ln in enumerate(lines):
        ind = len(ln) - len(ln.lstrip(" "))
        body = ln.strip()
        while stack and ind <= stack[-1][0] and len(stack) > 1:
            stack.pop()
        parent = stack[-1][1]
        if body.startswith("- ") or body == "-":
            if not isinstance(parent, list) or body == "-":
                raise RuntimeError("no YAML module in this Hermes to read config.yaml")
            parent.append(_scalar(body[2:]))
            continue
        key, sep, rest = body.partition(":")
        if not sep or not isinstance(parent, dict):
            raise RuntimeError("no YAML module in this Hermes to read config.yaml")
        key = _scalar(key) if key.startswith('"') else key.strip()
        if rest.strip():
            parent[str(key)] = _scalar(rest)
            continue
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        nind = len(nxt) - len(nxt.lstrip(" "))
        child: Any = [] if nxt.strip().startswith("-") and nind >= ind else {}
        parent[str(key)] = child
        stack.append((ind if isinstance(child, dict) or nind > ind else ind - 1, child))
    return root


def _prune_backups(home: Path, keep: int = BACKUPS_KEPT) -> None:
    """Only the newest `keep` dated copies stay (their names sort by time); the pre-twin copy is never one."""
    old = sorted(p for p in home.glob("config.yaml.pre-safety-*") if p.is_file() and not p.is_symlink())
    for p in old[:-keep] if keep > 0 else old:
        try:
            p.unlink()
        except OSError:
            pass


def write_config(home: Path, data: dict) -> Path:
    p = home / "config.yaml"
    if p.exists():
        shutil.copy2(p, str(p) + time.strftime(".pre-safety-%Y%m%d-%H%M%S"))
        _prune_backups(home)
    kind, y = _yaml()
    if kind == "rt":
        from io import StringIO
        buf = StringIO()
        y.dump(data, buf)
        text = buf.getvalue()
    else:
        # without a YAML module (a test host; every Hermes ships one): plain block YAML with JSON scalars, so
        # lines other tools append later keep it valid YAML
        text = (y.safe_dump(data, default_flow_style=False, sort_keys=False) if y is not None
                else _write_block(data))
    store.atomic_write_text(p, text)  # 0600, same bytes on every system
    return p


def _standard_denied(allow: Iterable[str]) -> list:
    allow = set(allow)
    return [t for t in STANDARD_DENIED if t not in allow]


def grok_capabilities(home: Optional[Path] = None) -> list:
    """The Hermes toolsets matching what the Grok bot can do (twin#71). Grok gives every bot the same tools, so
    this is GROK_CAPABILITIES for every bot; `home` is the twin's profile, for a later per-bot map."""
    return list(PARITY_ON)


def want(c: dict, preset: str, keep_mcp: Iterable[str] = (), allow: Iterable[str] = (),
         caps: Optional[Iterable[str]] = None) -> dict:
    """The config with the preset applied. Every key it does not name is kept (model, memory, display...).
    `allow`: in standard, the WIDENABLE toolsets the owner let the twin keep. `caps`: in parity, the toolsets
    the Grok bot has (grok_capabilities); none of them is disabled, on any platform."""
    if preset not in PRESETS:
        raise ValueError("unknown preset")
    if preset == "open":
        return c
    agent = c.setdefault("agent", {})
    a = c.setdefault("approvals", {})
    a.update(mode="manual", cron_mode="deny", unattended_mode="deny", single_query_mode="deny")
    c.setdefault("cron", {})["allow_agent_scheduling"] = False
    c.setdefault("terminal", {})["env_passthrough"] = []
    if preset == "parity":
        on = set(PARITY_ON if caps is None else caps)
        agent["disabled_toolsets"] = sorted((set(agent.get("disabled_toolsets") or []) - on) | set(PARITY_OFF))
        if isinstance(c.get("toolsets"), list):
            c["toolsets"] = [t for t in c["toolsets"] if t not in PARITY_OFF]
        pt = c.get("platform_toolsets")
        if isinstance(pt, dict):  # (Telegram's hermes-telegram and the CLI's keep everything but the floors)
            for k, v in list(pt.items()):
                if isinstance(v, list):
                    pt[k] = [t for t in v if t not in PARITY_OFF]
    elif preset == "strict":
        c["toolsets"] = list(STRICT_ALLOWED)
        c["platform_toolsets"] = {p: list(STRICT_ALLOWED) for p in PLATFORMS}
        agent["disabled_toolsets"] = sorted(set(STRICT_DISABLED) | set(agent.get("disabled_toolsets") or []))
        keep = set(keep_mcp)
        mcp = c.get("mcp_servers") or {}
        c["mcp_servers"] = {k: v for k, v in mcp.items() if k in keep}
        c.setdefault("platforms", {}).setdefault("telegram", {})["enabled"] = False
    else:
        deny = _standard_denied(allow)
        agent["disabled_toolsets"] = sorted((set(deny) | set(agent.get("disabled_toolsets") or []))
                                            - (set(allow) & set(WIDENABLE)))
        if isinstance(c.get("toolsets"), list):
            c["toolsets"] = [t for t in c["toolsets"] if t not in deny]
        pt = c.get("platform_toolsets")
        if isinstance(pt, dict):
            for k, v in list(pt.items()):
                if isinstance(v, list):
                    pt[k] = [t for t in v if t not in deny]
        if "mcp" not in set(allow) and isinstance(c.get("mcp_servers"), dict):
            keep = set(keep_mcp)
            c["mcp_servers"] = {k: v for k, v in c["mcp_servers"].items() if k in keep}
    return c


def _own_tg_bot(c: dict) -> bool:
    """twin#68: Telegram on in a strict twin is its own managed bot (token by the plugin's secrets.command, strict
    tools on Telegram, manual approvals), not the owner's."""
    cmd = str((c.get("secrets") or {}).get("command") or "") if isinstance(c.get("secrets"), dict) else ""
    return (cmd.startswith("hermes twin telegram token ")
            and sorted((c.get("platform_toolsets") or {}).get("telegram") or []) == sorted(STRICT_ALLOWED))


def problems(c: dict, preset: str, keep_mcp: Iterable[str] = (), allow: Iterable[str] = ()) -> list:
    """Why this config does not hold the preset ([] when it does). "open" always holds."""
    if preset == "open":
        return []
    bad: list = []
    agent = c.get("agent") or {}
    disabled = set(agent.get("disabled_toolsets") or [])
    if (c.get("approvals") or {}).get("mode") != "manual":
        bad.append("approvals.mode")
    if (c.get("cron") or {}).get("allow_agent_scheduling"):
        bad.append("cron.allow_agent_scheduling")
    if (c.get("terminal") or {}).get("env_passthrough"):
        bad.append("terminal.env_passthrough")
    if preset == "parity":
        if set(PARITY_OFF) - disabled:
            bad.append("disabled_toolsets")
        on = list(c.get("toolsets") or [])
        for v in (c.get("platform_toolsets") or {}).values():
            on += list(v or [])
        if set(on) & set(PARITY_OFF):
            bad.append("toolsets (scheduling or delegation)")
    elif preset == "strict":
        if list(c.get("toolsets") or []) != STRICT_ALLOWED:
            bad.append("toolsets")
        pt = c.get("platform_toolsets") or {}
        for k, v in pt.items():
            if sorted(v or []) != sorted(STRICT_ALLOWED):
                bad.append(f"platform_toolsets.{k}")
        for k in REQUIRED_PLATFORMS:
            if k not in pt:
                bad.append(f"platform_toolsets.{k} missing")
        if set(STRICT_DISABLED) - disabled:
            bad.append("disabled_toolsets")
        if set(c.get("mcp_servers") or {}) - set(keep_mcp):
            bad.append("mcp_servers")
        if ((c.get("platforms") or {}).get("telegram") or {}).get("enabled") and not _own_tg_bot(c):
            bad.append("platforms.telegram.enabled")
    else:
        deny = _standard_denied(allow)
        if set(deny) - disabled:
            bad.append("disabled_toolsets")
        on = list(c.get("toolsets") or [])
        for v in (c.get("platform_toolsets") or {}).values():
            on += list(v or [])
        if set(on) & set(SHELL_SOCKET):
            bad.append("toolsets (shell or socket)")
        elif set(on) & set(deny):
            bad.append("toolsets (web, search or files)")
        if "mcp" not in set(allow) and set(c.get("mcp_servers") or {}) - set(keep_mcp):
            bad.append("mcp_servers")
    return bad


# ---- model -----------------------------------------------------------------------------------------------------
_LOCAL_HOST = re.compile(r"^(localhost|127\.\d+\.\d+\.\d+|\[?::1\]?|10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|"
                         r"172\.(1[6-9]|2\d|3[01])\.\d+\.\d+|100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d+\.\d+|"
                         r"[a-z0-9.-]+\.(local|lan|internal|ts\.net))$", re.IGNORECASE)


def model_is_local(c: dict) -> Optional[bool]:
    """True when the profile's model is served on this computer or the owner's own network; False when it is a
    cloud provider; None when the config does not say."""
    m = c.get("model")
    if isinstance(m, str):
        return None
    if not isinstance(m, dict):
        return None
    url = str(m.get("base_url") or "")
    if url:
        host = re.sub(r"^[a-z]+://", "", url, flags=re.IGNORECASE).split("/")[0].rsplit(":", 1)[0] \
            if not url.startswith("[") else url
        return bool(_LOCAL_HOST.match(host))
    prov = str(m.get("provider") or "").lower()
    if not prov:
        return None
    return prov in LOCAL_PROVIDERS


# ---- per-twin record -------------------------------------------------------------------------------------------
def _state_path() -> Path:
    return store.central_dir() / STATE_FILE


def records() -> dict:
    data = store.read_json(_state_path(), {})
    return data if isinstance(data, dict) else {}


def record(profile: str, **fields: Any) -> dict:
    data = records()
    rec = dict(data.get(profile) or {})
    rec.update({k: v for k, v in fields.items() if v is not None})
    rec["at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    data[profile] = rec
    store.atomic_write_json(_state_path(), data)
    return rec


def _allow_of(rec: dict) -> list:
    return [a for a in (rec.get("allow") or []) if a in WIDENABLE] if isinstance(rec.get("allow"), list) else []


def mark_unsafe(profile: str, why: str) -> None:
    """The defaults could not be applied: fail closed. Its routines (approve) and the Telegram route stay off
    until `hermes twin safety` passes (clear_unsafe)."""
    record(profile, unsafe=safe.clean_name(why, 80) or "not applied")


def is_unsafe(profile: str) -> bool:
    return bool((records().get(profile) or {}).get("unsafe"))


def clear_unsafe(profile: str) -> None:
    data = records()
    if isinstance(data.get(profile), dict) and data[profile].pop("unsafe", None) is not None:
        store.atomic_write_json(_state_path(), data)


def keep_mcp() -> list:
    from . import config
    v = config.get("twin_safe_mcp")
    return [str(x) for x in v if isinstance(x, str)] if isinstance(v, list) else []


# ---- the verbs -------------------------------------------------------------------------------------------------
def apply_default(profile: str, home: Optional[Path] = None) -> dict:
    """Give a twin profile its default preset by rule (strict for a risky bot), unless the owner already chose one.
    Returns {"preset", "words", "chosen_by": "rule"|"owner", "path"}. Meant for the twin job (no question)."""
    home = home or store.profile_home(profile)
    rec = records().get(profile) or {}
    allow: list = []
    if rec.get("chosen_by") == "owner" and rec.get("preset") in PRESETS:
        preset, words, by = rec["preset"], list(rec.get("words") or []), "owner"
        allow = _allow_of(rec)
    else:
        if rec.get("preset") in ("strict", "standard"):  # chosen by the rule before 0.5.1: parity now (twin#71)
            _migrate(profile, home, rec)
            rec = records().get(profile) or {}
        preset, words = DEFAULT_PRESET, choose(profile_texts(home))[1]
        by = "rule"
    path, extra, headless = None, {}, ""
    if preset != "open":
        before = home / "config.yaml"
        had = before.read_bytes() if before.is_file() else None
        wanted = want(load_config(home), preset, keep_mcp(), allow, grok_capabilities(home))
        from . import gui  # twin#76: no screen in this session -> a headless browser, whose screenshots work
        headless = gui.fit_browser(wanted)
        path = write_config(home, wanted)
        # what to put back when twinning stops (forget): only the first rule-applied write is kept as "before"
        if not rec.get("before_written") and by == "rule":
            keep = home / BACKUP_NAME
            if had is not None:
                store.atomic_write_text(keep, had.decode("utf-8", "replace"))
            extra = {"before_written": True, "had_config": had is not None}
        extra["wrote_sha"] = hashlib.sha256(path.read_bytes()).hexdigest()
        extra["wrote_owned"] = owned_sha(load_config(home))
    record(profile, preset=preset, words=words[:10], chosen_by=by, **extra)
    return {"preset": preset, "words": words, "chosen_by": by, "path": str(path) if path else None,
            "capabilities": capabilities(load_config(home), preset), "headless": headless}


def capabilities(c: dict, preset: str) -> list:
    """[{"toolset", "name", "on", "note"}] for every Grok capability, as this config holds it (twin#71)."""
    disabled = set(((c.get("agent") or {}).get("disabled_toolsets")) or [])
    out = []
    for t, words, note in GROK_CAPABILITIES:
        on = t not in disabled and preset != "strict"
        why = note if on else ("off: the owner chose " + preset if preset in ("strict", "standard") and
                               t in (STRICT_DISABLED if preset == "strict" else STANDARD_DENIED)
                               else "off in this profile's config.yaml")
        out.append({"toolset": t, "name": words, "on": on, "note": why})
    return out


def capability_words(caps: list) -> str:
    """"browser ✓, web ✓, shell ✓ (risky commands ask first) ..., off: ..." for a PASS line."""
    parts = [f"{c['name']} {'✓' if c['on'] else '✗'}" + (f" ({c['note']})" if c["note"] else "") for c in caps]
    return ", ".join(parts) + f"; off: {PARITY_OFF_WHY}"


def _migrate(profile: str, home: Path, rec: dict) -> list:
    """A rule-chosen standard or strict twin (before 0.5.1) to parity: the toolset lists and MCP servers the old
    preset narrowed come back from the copy kept before the first safe defaults (.twin-pre-safety.yaml), the
    toolsets it disabled are enabled again (the owner's own disabled ones stay), and the hard floors are written.
    -> the capability names turned on. The record keeps wrote_sha (stop still puts the pre-twin copy back)."""
    old = rec.get("preset")
    c = load_config(home)
    before: dict = {}
    keep = home / BACKUP_NAME
    if rec.get("before_written") and rec.get("had_config") and keep.is_file():
        with contextlib.suppress(Exception):
            from io import StringIO
            kind, y = _yaml()
            text = keep.read_text(encoding="utf-8")
            before = (y.load(StringIO(text)) if kind == "rt" else y.safe_load(text) if y is not None
                      else _read_block(text)) or {}
            before = before if isinstance(before, dict) else {}
    was_off = set(((c.get("agent") or {}).get("disabled_toolsets")) or [])
    ours = set(STRICT_DISABLED if old == "strict" else STANDARD_DENIED)
    base = (was_off - ours) | set(((before.get("agent") or {}).get("disabled_toolsets")) or [])
    c.setdefault("agent", {})["disabled_toolsets"] = sorted(base)
    for key in ("toolsets", "platform_toolsets", "mcp_servers"):
        if key in before:
            c[key] = before[key]
        elif old == "strict":  # (strict wrote these keys itself; standard only narrowed lists that were there)
            c.pop(key, None)
    caps = grok_capabilities(home)
    c = want(c, "parity", keep_mcp(), (), caps)
    path = write_config(home, c)
    turned_on = [w for t, w, _n in GROK_CAPABILITIES if t in caps and t in was_off]
    record(profile, preset="parity", chosen_by="rule", parity_migrated=True, migrated_from=old,
           wrote_sha=hashlib.sha256(path.read_bytes()).hexdigest(), wrote_owned=owned_sha(load_config(home)))
    return turned_on


def migrate_to_parity(profiles: Iterable[str]) -> list:
    """twin#71, run once by `hermes twin setup --auto`: every twin whose preset the rule chose before 0.5.1
    (standard or strict) moves to parity. An owner's choice and a twin already on parity are left alone; a twin
    that cannot be moved is named and left as it was. -> [{"profile", "from", "turned_on": [names]} | {"profile",
    "error"}]."""
    out = []
    data = records()
    for prof in profiles:
        rec = data.get(prof)
        if not isinstance(rec, dict) or rec.get("chosen_by") != "rule" or rec.get("preset") not in ("standard",
                                                                                                    "strict"):
            continue
        try:
            home = store.profile_home(prof)
            out.append({"profile": prof, "from": rec["preset"], "turned_on": _migrate(prof, home, rec)})
        except Exception as exc:  # noqa: BLE001  (named in setup's line; the twin keeps its narrower preset)
            out.append({"profile": prof, "from": rec["preset"], "error": type(exc).__name__})
    return out


# The parts of config.yaml the safe defaults own (want() writes them); every other key (model, memory, display...)
# is the twin's own or a later create step's.
OWNED = (("agent", "disabled_toolsets"), ("approvals",), ("cron", "allow_agent_scheduling"),
         ("terminal", "env_passthrough"), ("toolsets",), ("platform_toolsets",), ("mcp_servers",),
         ("platforms", "telegram", "enabled"))


def owned_sha(c: Any) -> str:
    """A fingerprint of only the keys the safe defaults own."""
    part = {}
    for keys in OWNED:
        v: Any = c
        for k in keys:
            v = v.get(k) if isinstance(v, dict) else None
        part[".".join(keys)] = v
    return hashlib.sha256(json.dumps(part, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def refingerprint(profile: str, home: Optional[Path] = None) -> bool:
    """A twin step after the safe defaults (create's model choice, `twin model`) rewrote config.yaml: when the
    keys the safe defaults own are still exactly as safety wrote them, take the file's new sha as the one safety
    last wrote, so stop does not call that step a change since the safe defaults. A change to an owned key is never
    blessed. -> whether the new fingerprint was added."""
    rec = records().get(profile)
    if not isinstance(rec, dict) or not rec.get("wrote_sha") or not rec.get("wrote_owned"):
        return False
    home = home or store.profile_home(profile)
    cfg = home / "config.yaml"
    try:
        now = hashlib.sha256(cfg.read_bytes()).hexdigest()
    except OSError:
        return False
    also = [x for x in (rec.get("also_sha") or []) if isinstance(x, str)]
    if now == rec["wrote_sha"] or now in also or owned_sha(load_config(home)) != rec["wrote_owned"]:
        return False
    # kept beside wrote_sha, not over it: stop may first take a later step back out (the plugin's own lines), which
    # returns the file to exactly what safety wrote
    record(profile, also_sha=(also + [now])[-5:])
    return True


def forget(profile: str, home: Optional[Path] = None) -> dict:
    """Twinning stopped (with or without keeping the Hermes bot's data): put config.yaml back as it was before the
    safe defaults when nothing changed it since (its sha256 is still the one safety last wrote), then drop the
    record. -> {"had": a record existed, "restored": config.yaml was put back, "backup": the kept pre-twin copy's
    path when it was NOT put back (the owner's or a later edit is left alone, and the copy is kept and named)}.
    The record is dropped only after the restore went through, so a failed restore can be tried again."""
    out: dict = {"had": False, "restored": False, "backup": None}
    rec = records().get(profile)
    if rec is None:
        return out
    out["had"] = True
    home = home or store.profile_home(profile)
    cfg, keep = home / "config.yaml", home / BACKUP_NAME
    try:
        cur = hashlib.sha256(cfg.read_bytes()).hexdigest() if cfg.is_file() else None
        same = cur is not None and (cur == rec.get("wrote_sha") or cur in (rec.get("also_sha") or []))
    except OSError:
        same = False
    if same and rec.get("before_written"):
        if rec.get("had_config") and keep.is_file():
            store.atomic_write_text(cfg, keep.read_text(encoding="utf-8"))  # (raises: the record stays)
            out["restored"] = True
        elif not rec.get("had_config"):
            cfg.unlink()
            out["restored"] = True
    if out["restored"] and keep.is_file():
        keep.unlink()
    elif keep.is_file():
        out["backup"] = str(keep)
    data = records()
    if data.pop(profile, None) is not None:
        store.atomic_write_json(_state_path(), data)
    return out


def set_preset(profile: str, preset: str, home: Optional[Path] = None, allow: Iterable[str] = ()) -> dict:
    """The owner's one command to widen (or tighten) a twin: recorded as the owner's choice. `allow`: with
    standard, toolsets of WIDENABLE the owner lets the twin keep (`--allow web`)."""
    if preset not in PRESETS:
        raise ValueError("unknown preset")
    allow = [a for a in allow if a in WIDENABLE]
    home = home or store.profile_home(profile)
    extra = {}
    if preset != "open":
        wanted = want(load_config(home), preset, keep_mcp(), allow, grok_capabilities(home))
        from . import gui  # twin#76: no screen in this session -> a headless browser, whose screenshots work
        headless = gui.fit_browser(wanted)
        path = write_config(home, wanted)
        extra["wrote_sha"] = hashlib.sha256(path.read_bytes()).hexdigest()  # (stop still puts the old one back)
        extra["wrote_owned"] = owned_sha(load_config(home))
    return record(profile, preset=preset, chosen_by="owner", allow=sorted(set(allow)), **extra)


def set_model_policy(profile: str, policy: str) -> dict:
    if policy not in ("local", "any"):
        raise ValueError("model policy is local or any")
    return record(profile, model_policy=policy)


def check(profile: str, home: Optional[Path] = None) -> dict:
    """{"ok", "preset", "chosen_by", "problems": [...], "model": "local"|"cloud"|"unknown", "model_policy"}.
    A twin with no recorded preset is checked against the rule's choice."""
    home = home or store.profile_home(profile)
    rec = records().get(profile) or {}
    c = load_config(home)
    preset = rec.get("preset") if rec.get("preset") in PRESETS else DEFAULT_PRESET
    bad = problems(c, preset, keep_mcp(), _allow_of(rec) if rec.get("chosen_by") == "owner" else [])
    local = model_is_local(c)
    policy = rec.get("model_policy") or "local"
    model = {True: "local", False: "cloud", None: "unknown"}[local]
    if policy == "local" and local is not True:
        bad.append(f"model is {model}: record a model policy (hermes twin safety {safe.clean_name(profile, 60)} "
                   "--model-policy any) or point the twin at a local model")
    return {"ok": not bad, "preset": preset, "chosen_by": rec.get("chosen_by") or "rule", "problems": bad,
            "model": model, "model_policy": policy, "words": list(rec.get("words") or []),
            "capabilities": capabilities(c, preset)}


def line(profile: str, res: dict) -> str:
    who = safe.clean_name(profile, 60)
    if res["ok"]:
        caps = res.get("capabilities")
        return (f"PASS: twin {who} safety {res['preset']} ({res['chosen_by']}), model {res['model']}"
                + (f"; capabilities: {capability_words(caps)}" if caps and res["preset"] != "open" else ""))
    return f"FAIL: twin {who} safety {res['preset']}: " + "; ".join(res["problems"][:6])
