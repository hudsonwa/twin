"""`hermes twin setup --auto`: setup with no manual step and no question (zero-touch issue 07).

Steps, in order; the first that fails ends the run with one FAIL line naming it, and the run ends with one PASS line
when all hold:

1. botport: when this computer has none, setup downloads the pinned release file for this computer itself (the
   address is fixed text plus the pinned tag and one of four file names, `pins.download_for`), checks its SHA-256
   against the table this plugin carries (`botport_pins.json`) BEFORE anything else touches it, and hands it to the
   same checks the Twins page uses (`choose_helper`). Then botport is verified as always (`trust_botport`, pinned
   route: no GitHub tool, no login). Nothing goes through ~/Downloads and the owner never downloads anything.
2. Reach from any profile: a Hermes terminal keeps the profile last chosen with `hermes -p` ("sticky"). When that
   profile does not have the plugin, `hermes twin` was "invalid choice" there. Setup links the plugin folder into
   that profile's plugins folder (a symlink, the way one plugin is shared across profiles by hand) and enables it
   with Hermes' own `hermes -p PROFILE plugins enable`, and the PASS line says so. A twin's own profile is refused
   (the twin would get the plugin's tools), and another copy of the plugin there (a link elsewhere, or a folder)
   is left alone and FAILs. Twin data is shared by every profile already
   (`<root>/plugin-data/grok-bot-twin`), so the twin verbs then work the same from there.
3. The PATH the Grok app sees: an app started from the Dock gets launchd's short PATH, not the terminal's. Setup
   reads it (`launchctl getenv PATH`, else the system default) and says whether `hermes` and `botport` are on it.
   Twin never depends on that: it starts both by absolute path (behaviour.hermes_path, the verified botport), so
   a short PATH is reported, never "fixed" by changing the system.
4. Engine and port under the fast preset: `botport grok status`; when botport has no saved Grok policy, `botport
   grok policy preset fast` (the owner's default: the port opens on demand, with a time limit); an owner-chosen
   preset is kept and named. The port is not opened by setup unless `--open-port` is given (opening it restarts the
   Grok app); under fast it opens on demand at the first twin job.
5. Grok settings stay as they are: "Execution on Local Computer" (`local_tool_permission`) is read before and
   after; any change is a FAIL. Setup never writes a Grok setting.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import tempfile
import urllib.request
from pathlib import Path
from typing import Any, Callable, Optional

from . import osflags as _osflags, pins, safe, store
from .engine import EngineError, EXPECTED_BOTPORT_TAG, engine_needed_line, engine_pinned

PLUGIN_NAME = "grok-bot-twin"
PLUGIN_DIR = Path(__file__).resolve().parent.parent
DOWNLOAD_CAP = 64 * 1024 * 1024
DOWNLOAD_TIMEOUT_S = 120
LAUNCHD_DEFAULT_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"
LAUNCHCTL = "/bin/launchctl"
INSTALL_REPO = "hudsonwa/twin"

Fetch = Callable[[str, int], bytes]          # (url, cap) -> bytes
Run = Callable[[list, float], tuple]         # (argv, timeout) -> (rc, stdout, stderr)


class Stop(Exception):
    """One step failed: the message is the FAIL line's reason."""


# ---- 1. botport --------------------------------------------------------------------------------------------------
def _fetch(url: str, cap: int) -> bytes:
    """https only; the body is capped. Redirects stay on https (GitHub sends release files from its file host)."""
    if not url.startswith("https://"):
        raise Stop("download refused: not https")

    class _Https(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            if not str(newurl).startswith("https://"):
                raise Stop("download refused: redirected off https")
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    opener = urllib.request.build_opener(_Https())
    req = urllib.request.Request(url, headers={"User-Agent": "grok-bot-twin-setup"})
    with opener.open(req, timeout=DOWNLOAD_TIMEOUT_S) as resp:
        data = resp.read(cap + 1)
    if len(data) > cap:
        raise Stop("download refused: larger than the release file can be")
    return data


def fetch_pinned(tag: str, target: Optional[str] = None, fetch: Optional[Fetch] = None) -> Path:
    """Download this computer's pinned release file, check its SHA-256 against the plugin's table, and return the
    path of a private copy (0600 in a 0700 folder of the plugin's own). Raises Stop on any mismatch."""
    target = target or pins.platform_target()
    dl = pins.download_for(tag, target)
    if dl is None:
        raise Stop(f"botport has no build for this computer ({safe.clean_name(platform.system(), 20)} "
                   f"{safe.clean_name(platform.machine(), 20)})")
    want = (pins.load().get(tag) or {}).get("archives", {}).get(dl["file_name"])
    if not want:
        raise Stop(f"release {tag} is not pinned in this plugin version; nothing downloaded")
    try:
        data = (fetch or _fetch)(dl["url"], DOWNLOAD_CAP)
    except Stop:
        raise
    except Exception as exc:  # network, TLS, HTTP status
        raise Stop(f"could not download botport {tag} ({safe.clean_summary(str(exc), 120)})") from exc
    got = hashlib.sha256(data).hexdigest()
    if got != want:
        raise Stop(f"downloaded botport {tag} does not match the pinned SHA-256 (got {got[:12]}…); nothing used")
    folder = store.ensure_dir(store.central_dir() / "downloads")
    os.chmod(folder, 0o700)
    fd, tmp = tempfile.mkstemp(prefix=".dl-", dir=str(folder))
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    os.chmod(tmp, 0o600)
    path = folder / dl["file_name"]
    _osflags.replace(tmp, path)
    return path


def ensure_botport(svc: Any, fetch: Optional[Fetch] = None) -> dict:
    """botport present and verified against the pinned table. Returns {"version", "tag", "sha", "downloaded"}."""
    downloaded = False
    tag = svc.release_tag()

    def take_pinned() -> None:
        path = fetch_pinned(tag, fetch=fetch)
        try:
            svc.choose_helper(str(path))
        except EngineError as exc:
            raise Stop(f"the pinned botport file was refused: {safe.clean_summary(exc.message, 160)}") from exc
        finally:
            try:
                os.unlink(path)  # Hermes keeps its own copy; the download itself is not kept
            except OSError:
                pass
        if svc.botport() is None:
            raise Stop("botport was taken but cannot be found afterwards")

    if svc.botport() is None:
        take_pinned()
        downloaded = True
    try:
        res = svc.trust_botport(False, tag)
    except EngineError as exc:
        if downloaded:
            raise Stop(f"botport is not verified: {safe.clean_summary(exc.message, 160)}") from exc
        # (an older botport from an earlier plugin version, or another build: take the pinned release, once)
        take_pinned()
        downloaded = True
        try:
            res = svc.trust_botport(False, tag)
        except EngineError as exc2:
            raise Stop(f"botport is not verified: {safe.clean_summary(exc2.message, 160)}") from exc2
    if not res.get("attested"):
        raise Stop("botport is not verified (no pinned or signed match)")
    return {"version": res.get("version") or "", "tag": res.get("release_tag") or tag,
            "sha": str(res.get("sha256") or "")[:12], "downloaded": downloaded}


# ---- 2. any profile ----------------------------------------------------------------------------------------------
def active_profile(root: Optional[Path] = None) -> str:
    """The sticky profile `hermes` uses with no -p (<root>/active_profile), "default" when none is set."""
    root = root or store.hermes_root()
    try:
        name = (root / "active_profile").read_text(encoding="utf-8").strip()
    except OSError:
        return "default"
    return name if name and store.valid_id(name) else "default"


def _enabled_in(home: Path) -> bool:
    from . import profile_safety
    try:
        cfg = profile_safety.load_config(home)
    except Exception:
        return False
    plugins = cfg.get("plugins") if isinstance(cfg.get("plugins"), dict) else {}
    return PLUGIN_NAME in (plugins.get("enabled") or []) and PLUGIN_NAME not in (plugins.get("disabled") or [])


def has_plugin(home: Path) -> bool:
    return (home / "plugins" / PLUGIN_NAME).exists() and _enabled_in(home)


def _hermes() -> Optional[str]:
    from .behaviour import hermes_path
    return hermes_path()


def _run(argv: list, timeout: float) -> tuple:
    p = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout, check=False)
    return p.returncode, p.stdout, p.stderr


def _is_link(path: Path) -> bool:
    """A symbolic link, or on Windows also a junction (what _link_dir makes when symlinks are not allowed)."""
    try:
        return _osflags.is_link(os.lstat(path))
    except OSError:
        return False


def _link_dir(target: Path, link: Path) -> None:
    """Link a folder. Windows lets an ordinary account make a symlink only in Developer Mode, so there a
    directory junction (no privilege needed, same folder for Hermes) is made when the symlink is refused."""
    try:
        os.symlink(str(target), str(link), target_is_directory=True)
    except OSError as exc:
        if not _osflags.WINDOWS:
            raise Stop(f"could not link the plugin into the profile ({exc.__class__.__name__})") from exc
        try:
            import _winapi  # type: ignore
            _winapi.CreateJunction(str(target), str(link))
        except OSError as exc2:
            raise Stop(f"could not link the plugin into the profile ({exc2.__class__.__name__})") from exc2


def twin_profiles(svc: Any) -> tuple:
    """The Hermes profiles of this computer's twins (never given the plugin by reach)."""
    try:
        reg = svc._registry()
    except Exception:
        return ()
    out = []
    for e in (reg.values() if isinstance(reg, dict) else []):
        prof = ((e or {}).get("hermes") or {}).get("profile") if isinstance(e, dict) else None
        if isinstance(prof, str) and prof:
            out.append(prof)
    return tuple(out)


def reach(profile: str, run: Optional[Run] = None, hermes: Optional[str] = None,
          plugin_dir: Path = PLUGIN_DIR, twins: tuple = (), link_other: bool = False) -> str:
    """Make `hermes twin` work in `profile`. Returns "had it", "linked" or "left alone"; raises Stop. A twin's own
    profile is never given the plugin (its tools would reach the twin), and another copy of the plugin is left alone.
    Audit 2026-11-16: a sticky profile other than "default" is one of the owner's own bots; enabling the plugin there
    adds the twin toolset to that bot (it happened to the owner's main bot). It is left alone unless the owner asked
    (`--link-profile`): `hermes -p default twin ...` works from any terminal."""
    shown = safe.clean_name(profile, 60)
    if profile in twins:
        raise Stop(f"profile {shown} is a twin's own Hermes bot; the plugin is not added to it (choose another "
                   "profile with hermes -p)")
    if profile != "default" and not link_other and not has_plugin(store.profile_home(profile)):
        return "left alone"
    home = store.profile_home(profile)
    link = home / "plugins" / PLUGIN_NAME
    linked = _is_link(link)
    if linked and Path(os.path.realpath(link)) != plugin_dir.resolve():
        raise Stop(f"profile {shown} links another copy of the plugin; left alone")
    if not linked and link.exists() and link.resolve() != plugin_dir.resolve():
        raise Stop(f"profile {shown} has another copy of the plugin (a folder, not a link to this one); left alone")
    if has_plugin(home):
        return "had it"
    if not home.is_dir():
        raise Stop(f"profile {shown} has no folder")
    if not link.exists() and not linked:
        store.ensure_dir(home / "plugins")
        _link_dir(plugin_dir.resolve(), link)
    exe = hermes or _hermes()
    if not exe:
        raise Stop("Hermes' own command was not found to enable the plugin")
    try:
        rc, _out, err = (run or _run)([exe, "-p", profile, "plugins", "enable", PLUGIN_NAME], 60)
    except Exception as exc:
        raise Stop(f"hermes plugins enable did not run ({safe.clean_summary(str(exc), 100)})") from exc
    if rc != 0 or not _enabled_in(home):
        raise Stop(f"hermes -p {safe.clean_name(profile, 60)} plugins enable {PLUGIN_NAME} failed "
                   f"({safe.clean_summary((err or b'').decode('utf-8', 'replace'), 120)})")
    return "linked"


# ---- 3. the Grok app's PATH --------------------------------------------------------------------------------------
def app_path(run: Optional[Run] = None) -> str:
    """The PATH an app started from the Dock gets: launchd's (`launchctl getenv PATH`), else the system default."""
    if platform.system() != "Darwin" or not os.path.exists(LAUNCHCTL):
        return os.environ.get("PATH", LAUNCHD_DEFAULT_PATH)
    try:
        rc, out, _ = (run or _run)([LAUNCHCTL, "getenv", "PATH"], 10)
        val = (out or b"").decode("utf-8", "replace").strip()
        return val if rc == 0 and val else LAUNCHD_DEFAULT_PATH
    except Exception:
        return LAUNCHD_DEFAULT_PATH


def on_path(name: str, path: str) -> Optional[str]:
    return shutil.which(name, path=path)


def path_note(svc: Any, run: Optional[Run] = None) -> str:
    sp = app_path(run)
    hermes = _hermes()
    if not hermes:
        raise Stop("Hermes' own command was not found by absolute path")
    missing = [n for n in ("hermes", "botport") if not on_path(n, sp)]
    if not missing:
        return "Grok app PATH has hermes and botport"
    return f"Grok app PATH lacks {' and '.join(missing)}; twin starts them by absolute path"


# ---- 4/5. engine, preset, port, Grok settings ---------------------------------------------------------------------
def policy_saved() -> bool:
    """Whether botport has a saved Grok policy, in the folder the engine botport uses: ~/.botport under the HOME
    the plugin passes it (engine._env passes no BOTPORT_HOME, so a BOTPORT_HOME set here is not looked at)."""
    home = os.path.join(os.path.expanduser("~"), ".botport")
    return os.path.isfile(os.path.join(home, "grok-policy.toml"))


def engine_check(eng: Any, open_port: bool = False, saved: Optional[bool] = None) -> dict:
    """{"preset", "set_now", "port", "permission"}. `eng` is a grok_engine.GrokEngine (tests: a fake runner)."""
    from . import grok_engine as ge
    st = eng.status()
    if not ge.has_engine(st):
        raise Stop("this botport has no Grok engine (botport grok); a signed release with it is needed")
    if st.data.get("installed") is False:
        raise Stop("the Grok app is not installed on this computer")
    before = ge.local_permission(st)
    pol = eng.policy_show()
    preset = str(((pol.data.get("policy") or {}) if isinstance(pol.data.get("policy"), dict) else {})
                 .get("preset") or st.data.get("preset") or "")
    set_now = False
    if not (policy_saved() if saved is None else saved):
        res = eng.policy_preset("fast")
        if res.exit != ge.DONE:
            raise Stop(f"botport grok policy preset fast failed ({safe.clean_summary(res.proof, 120)})")
        preset, set_now = "fast", True
    port = "open" if st.data.get("port_open") else "opens on demand" if preset == "fast" else "closed"
    if open_port and not st.data.get("port_open"):
        res = eng.launch()
        if res.exit != ge.DONE:
            raise Stop(f"botport grok launch failed ({safe.clean_summary(res.proof, 120)})")
        port = "open"
    elif port == "closed":
        raise Stop(f"the Grok port is closed and preset {safe.clean_name(preset, 20)} does not open it on demand; "
                   "run hermes twin setup --auto --open-port")
    after = ge.local_permission(eng.status())
    if before != after:
        raise Stop(f"Grok's Execution setting changed during setup ({before} -> {after})")
    return {"preset": preset, "set_now": set_now, "port": port, "permission": after}


# ---- the run -----------------------------------------------------------------------------------------------------
def run(svc: Any, open_port: bool = False, fetch: Optional[Fetch] = None, runner: Optional[Run] = None,
        engine: Any = None, say: Callable[[str], None] = print, link_profile: bool = False) -> tuple:
    """(exit code, the one PASS/FAIL line). Progress goes to `say`; nothing is asked."""
    step = "botport"
    if not engine_pinned():  # (the pinned release has no Grok engine: say so before downloading anything)
        return 1, f"FAIL: hermes twin setup --auto: {engine_needed_line()}"
    try:
        bp = ensure_botport(svc, fetch)
        say(("Downloaded and verified" if bp["downloaded"] else "Verified")
            + f" botport {bp['version']} (release {bp['tag']}, sha {bp['sha']}…).".replace("  ", " "))
        step = "profile"
        prof = active_profile()
        how = reach(prof, run=runner, twins=twin_profiles(svc), link_other=link_profile)
        if how == "left alone":
            say(f"Profile {prof} was left as it is (the plugin is not added to your own bots); use "
                "hermes -p default twin ..., or setup --auto --link-profile to add it there.")
            prof = "default"
        else:
            say(f"hermes twin works from profile {prof} ({how}).")
        step = "path"
        note = path_note(svc, runner)
        say(note + ".")
        step = "engine"
        if engine is None:
            from . import grok_engine as ge
            try:
                engine = ge.from_service(svc)
            except ge.Unavailable as exc:
                raise Stop(str(exc)) from exc
        eng = engine_check(engine, open_port)
        say(f"Engine ready: preset {eng['preset']}{' (set now)' if eng['set_now'] else ''}, port {eng['port']}.")
    except Stop as exc:
        return 1, f"FAIL: hermes twin setup --auto: {step}: {exc}"
    return 0, (f"PASS: hermes twin setup --auto: botport {bp['tag']} verified, engine ready (preset {eng['preset']}, "
               f"port {eng['port']}), reachable from profile {prof}"
               + (" (plugin linked and enabled there)" if how == "linked" else "")
               + ("" if how != "left alone" else " (the sticky profile was left alone)")
               + (", Grok settings unchanged " f"(Execution: {eng['permission']})" if eng["permission"] != "unknown"
                  else ", Grok's Execution setting not read (the port was closed; it is read and compared before "
                       "and after every export instead)"))


BUILD_FILE = "BUILD"  # twin/BUILD: {"commit", "tree"}, written by tools/stamp_build.py into a release or a copy


def _hexref(ref: object) -> str:
    return ref if isinstance(ref, str) and 7 <= len(ref) <= 40 and all(c in "0123456789abcdef" for c in ref) else ""


def build_stamp() -> dict:
    """The build stamp shipped in this tree ({"commit", "tree"}), {} when there is none or it is not plain."""
    try:
        data = json.loads((Path(__file__).resolve().parent / BUILD_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict) or not _hexref(data.get("commit")):
        return {}
    return {"commit": data["commit"], **({"tree": data["tree"]} if _hexref(data.get("tree")) else {})}


def install_record_ref() -> str:
    """The commit Hermes' install record names for this plugin, or ""."""
    for meta in (PLUGIN_DIR.parent / ".install-metadata.json", PLUGIN_DIR / ".install-metadata.json"):
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        entry = data.get(PLUGIN_NAME) if isinstance(data.get(PLUGIN_NAME), dict) else data
        ref = _hexref(entry.get("commit") or entry.get("ref") if isinstance(entry, dict) else None)
        if ref:
            return ref
    return ""


def install_check() -> dict:
    """Does the folder's build stamp match Hermes' install record (twin#58)? {"ok", "stamp", "record",
    "message", "fix"}. With no stamp the build is "unknown": the record's revision is never quoted as the truth."""
    stamp, record = build_stamp().get("commit", ""), install_record_ref()
    fix = (f"Install it again the supported way: hermes plugins install {INSTALL_REPO} --ref <commit> --force; for "
           "a folder copy, run tools/stamp_build.py before copying, then hermes plugins adopt")
    if not stamp:
        return {"ok": True, "stamp": None, "record": record or None, "fix": "",
                "message": "plugin build: unknown (no build stamp in this folder)"
                           + (f"; Hermes' install record names {record[:12]}" if record else "")}
    same = bool(record) and (stamp.startswith(record) or record.startswith(stamp))
    if same:
        return {"ok": True, "stamp": stamp, "record": record, "fix": "",
                "message": f"plugin build {stamp[:12]} matches Hermes' install record"}
    return {"ok": False, "stamp": stamp, "record": record or None, "fix": fix,
            "message": f"plugin build {stamp[:12]} does not match Hermes' install record ("
                       + (f"it names {record[:12]}" if record else "it names no revision")
                       + "): the folder was replaced without a new install"}


def plugin_ref() -> str:
    """The commit this plugin copy is: its build stamp, else Hermes' install record, else the folder's git HEAD,
    or ""."""
    ref = build_stamp().get("commit") or install_record_ref()
    if ref:
        return ref
    try:
        p = subprocess.run(["git", "-C", str(PLUGIN_DIR), "rev-parse", "HEAD"], capture_output=True, timeout=10,
                           check=False, stdin=subprocess.DEVNULL)
        ref = p.stdout.decode().strip()
        return ref if p.returncode == 0 and len(ref) == 40 else ""
    except Exception:
        return ""


def install_line(ref: Optional[str] = None) -> str:
    """The pinned one-line install an agent runs when told "install Grok Bot Twin": Hermes' own installer at one
    exact commit (no unpinned pipe to a shell), then this setup."""
    ref = ref if ref is not None else plugin_ref()
    return (f"hermes plugins install {INSTALL_REPO} --ref {ref or '<commit>'} --enable && "
            "hermes twin setup --auto")


__all__ = ["run", "install_line", "reach", "active_profile", "fetch_pinned", "ensure_botport", "engine_check",
           "app_path", "path_note", "EXPECTED_BOTPORT_TAG"]
