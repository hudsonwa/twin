"""The twin's tool-level veto (field audit 24 Nov 2026): CAPTCHAs and remote-debugging attach are blocked in a twin
profile whatever the model decides; nothing else is touched, and other profiles are never guarded."""
from twin import tool_guard as g


def test_captcha_steps_are_blocked():
    for args in ({"action": "click", "description": "Tick the reCAPTCHA checkbox"},
                 {"instruction": "tick hydrant tiles (1,1),(2,2) then VERIFY", "note": "Select all images with a fire hydrant"},
                 {"text": "I'm not a robot"}):
        assert g.check("browser_exec", args) == g.CAPTCHA_STOP


def test_remote_debugging_attach_is_blocked():
    assert g.check("terminal", {"command": "python3 cdp_attach.py --port 9222"}) == g.DEBUG_STOP
    assert g.check("terminal", {"command": "curl http://127.0.0.1:9222/json/version"}) == g.DEBUG_STOP
    assert g.check("code_execution", {"code": "await chromium.connect_over_cdp(url)"}) == g.DEBUG_STOP


def test_ordinary_steps_run():
    assert g.check("browser_exec", {"action": "open", "url": "https://example.com/login"}) is None
    assert g.check("terminal", {"command": "git status"}) is None
    assert g.check("web_search", {"query": "captcha"}) is None  # not a tool that acts


def test_only_a_twin_profile_is_guarded(tmp_path, monkeypatch):
    twin = tmp_path / "profiles" / "acme"
    (twin / "botport").mkdir(parents=True)
    other = tmp_path / "profiles" / "mine"
    other.mkdir(parents=True)
    bad = {"action": "click", "description": "tick the captcha"}
    monkeypatch.setenv("HERMES_HOME", str(twin))
    assert g.hook("browser_exec", bad) == {"action": "block", "message": g.CAPTCHA_STOP}
    monkeypatch.setenv("HERMES_HOME", str(other))
    assert g.hook("browser_exec", bad) is None


def test_gateway_profile_comes_from_hermes_not_the_env(tmp_path, monkeypatch):
    """In the shared gateway HERMES_HOME is the Hermes root; the call's own profile comes from Hermes' context."""
    twin = tmp_path / "profiles" / "acme"
    (twin / "botport").mkdir(parents=True)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    from twin import config
    monkeypatch.setattr(config, "hermes_home", lambda: str(twin))
    assert g.hook("browser_exec", {"code": "new_tab('https://www.google.com/recaptcha/api2/demo')"}) == {
        "action": "block", "message": g.CAPTCHA_STOP}
