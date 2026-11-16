"""twin#68: an opt-in, same-named Telegram bot per twin through Telegram managed bots. Every Bot API call goes to
a fake (FakeBotApi); no test talks to Telegram. Invented names and ids only."""
from __future__ import annotations

import io
import logging
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

from twin_testlib import all_text_under, cli, home, svc  # noqa: F401
from hermes_plugins.grok_bot_twin.twin import config, profile_safety as ps, secret_ref, store, tg_bots

OWNER = 100200300
STRANGER = 999888777
TWIN = "acme-support"
BOT_ID = 7000111222
SENTINEL = "123456:TEST-not-a-token-sentinel"
GATEWAY_TOKEN = "654321:TEST-gateway-sentinel-value"


class MemStore:
    name = "mocked store"

    def __init__(self):
        self.data = {}

    def available(self):
        return None

    def put(self, name, value):
        self.data[name] = value

    def get(self, name):
        return self.data.get(name)

    def delete(self, name):
        self.data.pop(name, None)


class FakeBotApi:
    """Records every call; answers like Telegram's Bot API would (shapes from docs/design/managed-bots.md)."""

    def __init__(self, can_manage=True):
        self.calls = []
        self.can_manage = can_manage
        self.fail = set()

    def __call__(self, method, params):
        self.calls.append((method, dict(params)))
        if method in self.fail:
            return {"ok": False, "description": f"Bad Request: refused, bot{GATEWAY_TOKEN}"}
        if method == "getMe":
            return {"ok": True, "result": {"id": 42, "username": "acme_gateway_bot", "can_manage_bots": self.can_manage}}
        if method == "getManagedBotToken":
            return {"ok": True, "result": SENTINEL}
        return {"ok": True, "result": True}

    def methods(self):
        return [m for m, _ in self.calls]


def _profile(home: Path, name: str, config_text: str = "", env: str = "") -> Path:
    h = home if name == "default" else home / "profiles" / name
    h.mkdir(parents=True, exist_ok=True)
    if config_text:
        (h / "config.yaml").write_text(config_text, encoding="utf-8")
    if env:
        (h / ".env").write_text(env, encoding="utf-8")
    return h


@pytest.fixture
def world(home, monkeypatch):
    mem = MemStore()
    monkeypatch.setattr(secret_ref, "_override", [mem])
    _profile(home, "default", "gateway:\n  multiplex_profiles: true\n",
             f"TELEGRAM_BOT_TOKEN={GATEWAY_TOKEN}\nTELEGRAM_ALLOWED_USERS={OWNER}\n")
    th = _profile(home, TWIN, "model:\n  default: acme-llm-7b\n", "OTHER_KEY=x\n")
    ps.apply_default(TWIN, th)
    api = FakeBotApi()
    monkeypatch.setattr(tg_bots, "_transport", api)
    config.set_override({"telegram_bot_per_twin": True})
    return {"home": home, "twin": th, "mem": mem, "api": api}


def _update(creator=OWNER, bot_id=BOT_ID, username="acme_support_twin_bot"):
    return {"update_id": 1, "managed_bot": {"user": {"id": creator, "is_bot": False, "first_name": "Ada"},
                                            "bot": {"id": bot_id, "is_bot": True, "first_name": "Acme Support",
                                                    "username": username}}}


def _made(world):
    api = tg_bots.default_api()
    assert tg_bots.request(TWIN, api).startswith("PASS")
    return tg_bots.on_managed_bot(_update(), api, check_model=lambda p: {"line": "PASS: check-model: acme-support"})


# ---- off by default ------------------------------------------------------------------------------------------------
def test_setting_off_by_default_changes_nothing(home, monkeypatch):
    api = FakeBotApi()
    monkeypatch.setattr(tg_bots, "_transport", api)
    assert config.DEFAULTS["telegram_bot_per_twin"] is False and tg_bots.enabled() is False
    before = all_text_under(home)
    assert tg_bots.request(TWIN, tg_bots.default_api()) == tg_bots.OFF
    assert tg_bots.on_managed_bot(_update(), tg_bots.default_api()) is None
    assert api.calls == [] and all_text_under(home) == before
    assert not (store.central_dir() / tg_bots.STATE_FILE).exists()


def test_new_twin_with_setting_off_makes_no_bot_api_call(home, monkeypatch, svc):
    api = FakeBotApi()
    monkeypatch.setattr(tg_bots, "_transport", api)
    _profile(home, TWIN)
    svc._safe_defaults(TWIN)
    assert api.calls == []


# ---- the one tap ---------------------------------------------------------------------------------------------------
def test_request_sends_one_private_button(world):
    line = tg_bots.request(TWIN, tg_bots.default_api())
    assert line.startswith("PASS") and "acme_support_twin_bot" in line and "t.me/newbot/acme_gateway_bot/" in line
    assert world["api"].methods() == ["getMe", "sendMessage"]
    sent = world["api"].calls[1][1]
    assert sent["chat_id"] == OWNER
    btn = sent["reply_markup"]["keyboard"][0][0]["request_managed_bot"]
    assert 0 < btn["request_id"] < 2 ** 31 and btn["suggested_name"] == "Acme Support"
    assert btn["suggested_username"] == "acme_support_twin_bot"


def test_new_twin_with_setting_on_costs_one_tap(world, svc):
    note = svc._safe_defaults(TWIN)
    assert "PASS: telegram bot: asked the owner" in note
    assert world["api"].methods().count("sendMessage") == 1


def test_bot_management_mode_off_fails_with_the_owner_step(world):
    world["api"].can_manage = False
    line = tg_bots.request(TWIN, tg_bots.default_api())
    assert line.startswith("FAIL") and "Bot Management Mode" in line and "BotFather" in line
    assert world["api"].methods() == ["getMe"]


def test_per_profile_gateways_fail_naming_migrate_and_leave_gateway(world):
    cfg = world["home"] / "config.yaml"
    cfg.write_text("gateway:\n  multiplex_profiles: false\n", encoding="utf-8")
    before = cfg.read_bytes()
    line = tg_bots.request(TWIN, tg_bots.default_api())
    assert line.startswith("FAIL") and "hermes gateway migrate" in line
    assert world["api"].calls == [] and cfg.read_bytes() == before


def test_no_os_store_fails_before_asking(world, monkeypatch):
    monkeypatch.setattr(secret_ref, "_override", [None])
    line = tg_bots.request(TWIN, tg_bots.default_api())
    assert line.startswith("FAIL") and "plain .env" in line and world["api"].calls == []


def test_unsafe_twin_is_refused(world):
    ps.mark_unsafe(TWIN, "Boom")
    assert tg_bots.request(TWIN, tg_bots.default_api()).startswith("FAIL: telegram bot: safe profile defaults")
    assert world["api"].calls == []


# ---- the managed_bot update ----------------------------------------------------------------------------------------
def test_owner_tap_keeps_token_by_reference(world):
    line = _made(world)
    assert line.startswith("PASS") and "@acme_support_twin_bot" in line and "PASS: check-model" in line
    name = tg_bots.secret_name(TWIN)
    assert world["mem"].data[name] == SENTINEL
    m = world["api"].methods()
    assert m[-2:] == ["getManagedBotToken", "setManagedBotAccessSettings"]
    assert world["api"].calls[-2][1] == {"user_id": BOT_ID}
    assert world["api"].calls[-1][1] == {"user_id": BOT_ID, "is_access_restricted": True}
    env = (world["twin"] / ".env").read_text()
    assert f"TELEGRAM_ALLOWED_USERS={OWNER}" in env and "TELEGRAM_BOT_TOKEN=" not in env and "OTHER_KEY=x" in env
    cfg = ps.load_config(world["twin"])
    assert cfg["secrets"]["command"] == f"hermes twin telegram token {TWIN}"
    assert cfg["platforms"]["telegram"]["enabled"] is True
    assert cfg["platform_toolsets"]["telegram"] == ps.STRICT_ALLOWED and cfg["approvals"]["mode"] == "manual"
    assert tg_bots.has_bot(TWIN)


def test_token_never_in_files_logs_output_or_model_context(world, caplog, capsys):
    caplog.set_level(logging.DEBUG)
    out = io.StringIO()
    with redirect_stdout(out), redirect_stderr(out):
        line = _made(world)
        tg_bots.on_bot_update(TWIN, _msg(OWNER, OWNER, "private"), tg_bots.default_api(),
                              lambda p, t: {"reply": "hello"})
    from hermes_plugins.grok_bot_twin.twin import awareness
    block = awareness.build_block(TWIN, None) if hasattr(awareness, "build_block") else ""
    seen = "\n".join([line, out.getvalue(), caplog.text, str(capsys.readouterr()), str(block or ""),
                      all_text_under(world["home"]), repr(tg_bots.state())])
    assert SENTINEL not in seen and GATEWAY_TOKEN not in seen.replace(
        (world["home"] / ".env").read_bytes().decode("utf-8"), "")  # (the gateway's own .env is the owner's; read
        # as bytes like all_text_under, so Windows CRLF matches)
    for p in world["twin"].rglob("*"):
        if p.is_file():
            assert SENTINEL not in p.read_text(errors="replace"), p


def test_api_error_text_never_carries_a_token(world):
    tg_bots.request(TWIN, tg_bots.default_api())
    world["api"].fail.add("getManagedBotToken")
    line = tg_bots.on_managed_bot(_update(), tg_bots.default_api())
    assert line.startswith("FAIL") and GATEWAY_TOKEN not in line and "[token]" in line
    assert world["mem"].data == {}


def test_creator_not_owner_is_ignored(world):
    tg_bots.request(TWIN, tg_bots.default_api())
    n = len(world["api"].calls)
    assert tg_bots.on_managed_bot(_update(creator=STRANGER), tg_bots.default_api()) is None
    assert len(world["api"].calls) == n and world["mem"].data == {}


def test_no_pending_or_expired_request_is_ignored(world):
    api = tg_bots.default_api()
    assert tg_bots.on_managed_bot(_update(), api) is None
    tg_bots.request(TWIN, api, now=1000.0)
    assert tg_bots.on_managed_bot(_update(), api, now=1000.0 + tg_bots.PENDING_S + 1) is None
    assert "getManagedBotToken" not in world["api"].methods()


def test_profile_with_own_token_is_not_overwritten(world):
    (world["twin"] / ".env").write_text("TELEGRAM_BOT_TOKEN=owner-own\n")
    tg_bots.request(TWIN, tg_bots.default_api())
    line = tg_bots.on_managed_bot(_update(), tg_bots.default_api())
    assert line.startswith("FAIL") and (world["twin"] / ".env").read_text() == "TELEGRAM_BOT_TOKEN=owner-own\n"


def test_strict_check_accepts_the_twins_own_bot(world):
    ps.set_preset(TWIN, "strict")
    ps.set_model_policy(TWIN, "any")
    _made(world)
    assert ps.check(TWIN)["ok"], ps.check(TWIN).get("problems")


# ---- who gets an answer on the twin's bot --------------------------------------------------------------------------
def _msg(user, chat_id, chat_type, text="hi"):
    return {"update_id": 9, "message": {"message_id": 1, "from": {"id": user, "is_bot": False},
                                        "chat": {"id": chat_id, "type": chat_type}, "text": text}}


@pytest.mark.parametrize("user,chat_id,chat_type", [
    (STRANGER, STRANGER, "private"),          # a non-owner DM
    (OWNER, -100500600, "group"),             # the owner, in a group
    (OWNER, -100500601, "supergroup"),
    (OWNER, -100500602, "channel"),
])
def test_non_owner_group_channel_get_no_reply(world, user, chat_id, chat_type):
    _made(world)
    n = len(world["api"].calls)
    ran = []
    assert tg_bots.on_bot_update(TWIN, _msg(user, chat_id, chat_type), tg_bots.default_api(),
                                 lambda p, t: ran.append(t) or {"reply": "x"}) is False
    assert ran == [] and len(world["api"].calls) == n


def test_channel_post_gets_no_reply(world):
    _made(world)
    n = len(world["api"].calls)
    post = {"update_id": 3, "channel_post": {"chat": {"id": -1001, "type": "channel"}, "text": "hi"}}
    assert tg_bots.on_bot_update(TWIN, post, tg_bots.default_api(), lambda p, t: {"reply": "x"}) is False
    assert len(world["api"].calls) == n


def test_owner_dm_gets_a_reply(world):
    _made(world)
    assert tg_bots.on_bot_update(TWIN, _msg(OWNER, OWNER, "private"), tg_bots.default_api(),
                                 lambda p, t: {"reply": "ok"})
    assert world["api"].calls[-1] == ("sendMessage", {"chat_id": OWNER, "text": "ok"})


# ---- stop ----------------------------------------------------------------------------------------------------------
def test_stop_turns_the_bot_off_and_suggests_deleting(world):
    _made(world)
    line = tg_bots.stop(TWIN)
    assert "is off" in line and "BotFather" in line
    assert world["mem"].data == {} and not tg_bots.has_bot(TWIN)
    cfg = ps.load_config(world["twin"])
    assert cfg["platforms"]["telegram"]["enabled"] is False and "command" not in (cfg.get("secrets") or {})
    assert "secrets.command" not in (world["twin"] / ".env").read_text()
    assert "deleteBot" not in " ".join(world["api"].methods())
    assert tg_bots.on_bot_update(TWIN, _msg(OWNER, OWNER, "private"), tg_bots.default_api(),
                                 lambda p, t: {"reply": "x"}) is False


def test_token_command_never_prints_to_a_terminal(world):
    _made(world)

    class Tty(io.StringIO):
        def isatty(self):
            return True
    t = Tty()
    assert tg_bots.print_token(TWIN, t) == 1 and t.getvalue() == ""
    pipe = io.StringIO()
    assert tg_bots.print_token(TWIN, pipe) == 0 and pipe.getvalue() == f"TELEGRAM_BOT_TOKEN={SENTINEL}\n"


# ---- review rc/0.5.2 -----------------------------------------------------------------------------------------------
def test_strict_check_wants_manual_approvals_on_the_twins_own_bot(world):
    ps.set_preset(TWIN, "strict")
    ps.set_model_policy(TWIN, "any")
    _made(world)
    cfg = ps.load_config(world["twin"])
    cfg["approvals"]["mode"] = "off"
    assert "platforms.telegram.enabled" in ps.problems(cfg, "strict")


def test_stop_forgets_the_token_even_when_the_config_is_odd(world):
    _made(world)
    (world["twin"] / "config.yaml").write_text("secrets: [odd]\n", encoding="utf-8")
    assert "is off" in tg_bots.stop(TWIN)
    assert world["mem"].data == {} and not tg_bots.has_bot(TWIN)


def test_request_uses_the_routes_own_gateway(world, monkeypatch):
    from hermes_plugins.grok_bot_twin.twin import tg_route
    _profile(world["home"], "helper", "", "TELEGRAM_BOT_TOKEN=1:x\nTELEGRAM_ALLOWED_USERS=999\nTELEGRAM_ALLOWED_USERS_X=1\n")
    seen = []
    real = tg_route.find_gateway
    monkeypatch.setattr(tg_route, "state", lambda: {"gateway": "default"})
    monkeypatch.setattr(tg_route, "find_gateway", lambda via=None, tp=(): seen.append(via) or real(via, tp))
    assert tg_bots.request(TWIN, tg_bots.default_api()).startswith("PASS")
    assert seen == ["default"]
