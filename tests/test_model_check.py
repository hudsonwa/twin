"""twin#66: check-model with a fake Hermes turn and a fake Telegram sender; endpoint redaction for Telegram text.
Invented twins only; private addresses are built in the test, never written literally."""
from __future__ import annotations

import ipaddress
import random
import re

from twin_testlib import home, svc  # noqa: F401
from hermes_plugins.grok_bot_twin.twin import model_check as mc  # noqa: E402
from hermes_plugins.grok_bot_twin.twin import store, tg_route  # noqa: E402

PROFILE = "acme-support"
OWNER = "1234567"


def _private_v4(net: str) -> str:
    n = ipaddress.ip_network(net)
    return str(n[random.randint(1, min(n.num_addresses - 2, 5000))])


def _private_addrs() -> list:
    v6u = ipaddress.ip_network("fd00::/8")
    v6l = ipaddress.ip_network("fe80::/10")
    return [_private_v4(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10",
                                     "127.0.0.0/8", "169.254.0.0/16")] + [str(v6u[4660]), str(v6l[17])]


def _port() -> int:
    return random.randint(1025, 65000)


def _config(model="acme-llm-7b", provider="custom", base_url=None):
    h = store.profile_home(PROFILE)
    h.mkdir(parents=True, exist_ok=True)
    body = f"model:\n  default: {model}\n  provider: {provider}\n"
    if base_url:
        body += f"  base_url: '{base_url}'\n"
    (h / "config.yaml").write_text(body)


def _route_on(monkeypatch, owners=(OWNER,)):
    monkeypatch.setattr(tg_route, "state", lambda: {"gateway": "default", "owner_ids": list(owners),
                                                    "twins": {PROFILE: {}}})


def _leaks(text: str, addr: str, port: int) -> bool:
    return addr in text or str(port) in text or re.search(r":\d{2,5}\b", text) is not None


def _url(addr: str, port: int) -> str:
    host = f"[{addr}]" if ":" in addr else addr
    return f"http://{host}:{port}/v1"


def test_redact_every_private_kind():
    for addr in _private_addrs():
        port = _port()
        for text in (f"I run on {_url(addr, port)} today", f"endpoint {addr} port {port}",
                     f"host {addr}:{port}" if ":" not in addr else f"host [{addr}]:{port}"):
            out = mc.redact(text)
            assert addr not in out, (text, out)
            assert f":{port}" not in out, (text, out)
    for name in ("gpu-box.local", "nas.lan", "api.corp.internal", "spark.tail1234.ts.net", "localhost"):
        port = _port()
        out = mc.redact(f"see http://{name}:{port}/v1 or {name}:{port} or {name}")
        assert name not in out and str(port) not in out, out
        assert mc.NETWORK_LABEL in out
    assert mc.redact(f"box:{_port()}") == mc.NETWORK_LABEL  # a bare hostname with a port


def test_redact_keeps_public_host_without_port_or_path():
    port = _port()
    out = mc.redact(f"I use https://api.example.com:{port}/v1/chat and model acme-llm-7b at 10:30, ratio 16:9")
    assert "api.example.com" in out and str(port) not in out and "/v1" not in out
    assert "acme-llm-7b" in out and "10:30" in out and "16:9" in out
    assert mc.endpoint_label("https://api.example.com/v1") == "api.example.com"
    assert mc.endpoint_label(_url(_private_addrs()[0], _port())) == mc.NETWORK_LABEL
    assert mc.endpoint_label("http://sparkbox:8000") == mc.NETWORK_LABEL
    assert mc.endpoint_label("") == mc.DEFAULT_LABEL


def test_pass_in_both_channels_one_message_each_owner_dm_only(home, monkeypatch):
    addr, port = _private_addrs()[0], _port()
    _config(base_url=_url(addr, port))
    _route_on(monkeypatch)
    sent_turns, posted = [], []

    def turn(profile, text):
        sent_turns.append(("hermes", profile, text))
        return {"ok": True, "reply": f"Model acme-llm-7b via custom at {_url(addr, port)}"}

    def tg_turn(profile, text):
        sent_turns.append(("telegram", profile, text))
        return {"ok": True, "reply": f"acme-llm-7b on {addr}:{port}"}

    res = mc.check(PROFILE, turn=turn, tg_turn=tg_turn, sender=lambda chat, text: posted.append((chat, text)) or True)
    assert res["ok"] and res["line"].startswith("PASS"), res["line"]
    assert sent_turns == [("hermes", PROFILE, mc.MESSAGE), ("telegram", PROFILE, mc.MESSAGE)]
    assert len(posted) == 1 and posted[0][0] == OWNER
    for text in (posted[0][1], res["telegram_line"]):
        assert not _leaks(text, addr, port), text
        assert "acme-llm-7b" in text
    assert mc.NETWORK_LABEL in res["telegram_line"]
    assert addr in res["line"]  # the terminal may show the full URL


def test_fail_names_the_silent_or_wrong_channel(home, monkeypatch):
    _config(base_url="https://api.example.com/v1")
    _route_on(monkeypatch)
    res = mc.check(PROFILE, turn=lambda p, t: {"ok": True, "reply": "acme-llm-7b"}, tg_turn=lambda p, t: None)
    assert not res["ok"] and "Telegram" in res["line"] and "Telegram: silent" in res["line"]
    res = mc.check(PROFILE, turn=lambda p, t: {"ok": True, "reply": "I am other-model-1"},
                   tg_turn=lambda p, t: {"ok": True, "reply": "acme-llm-7b"})
    assert not res["ok"] and "(Hermes wrong or silent)" in res["line"] and "named another model" in res["line"]


def test_not_on_route_runs_only_hermes_and_never_posts(home, monkeypatch):
    _config()
    monkeypatch.setattr(tg_route, "state", lambda: {})
    posted = []
    res = mc.check(PROFILE, turn=lambda p, t: {"ok": True, "reply": "acme-llm-7b"},
                   tg_turn=lambda p, t: (_ for _ in ()).throw(AssertionError("no Telegram turn")),
                   sender=lambda c, t: posted.append(c))
    assert res["ok"] and res["telegram"] is None and not posted
    assert "not on the Telegram route" in res["line"]


def test_several_owner_ids_post_nothing(home, monkeypatch):
    _config()
    _route_on(monkeypatch, owners=(OWNER, "7654321"))
    posted = []
    res = mc.check(PROFILE, turn=lambda p, t: {"ok": True, "reply": "acme-llm-7b"},
                   tg_turn=lambda p, t: {"ok": True, "reply": "acme-llm-7b"}, sender=lambda c, t: posted.append(c))
    assert res["ok"] and not posted and "not posted" in res["line"]


def test_no_model_configured_fails(home):
    res = mc.check(PROFILE, turn=lambda p, t: {"ok": True, "reply": "x"})
    assert not res["ok"] and "no model" in res["line"]


def test_route_replies_are_redacted(home, monkeypatch):
    addr, port = _private_addrs()[3], _port()
    _route_on(monkeypatch)
    monkeypatch.setattr(tg_route, "_unsafe", lambda p: False)
    monkeypatch.setattr(tg_route, "_turn", lambda p, t: {"ok": True, "reply": f"served from {addr}:{port}"})
    out = tg_route.handle(f"to {PROFILE} where do you run?", platform="telegram",
                          source={"chat_type": "dm", "user_id": OWNER, "chat_id": OWNER}, profile="default")
    assert out.startswith(f"[{PROFILE}]") and not _leaks(out, addr, port), out
