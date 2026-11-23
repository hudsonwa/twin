"""A new twin links the owner's existing sign-ins from the Hermes root instead of asking again (field audit
24 Nov 2026). Links only, never copies or overwrites; backups and unrelated files are ignored."""
from twin import access_links as al


def _root(tmp_path):
    root = tmp_path / "hermes"
    prof = root / "profiles" / "acme"
    prof.mkdir(parents=True)
    for n in ("google_token.json", "google_token_work.json", "google_client_secret.json",
              "google_token.json.bak-1", "config.yaml"):
        (root / n).write_text("{}")
    return root, prof


def test_links_every_shared_sign_in_file(tmp_path):
    root, prof = _root(tmp_path)
    got = al.link_existing(prof)
    assert got == ["google_client_secret.json", "google_token.json", "google_token_work.json"]
    for n in got:
        assert (prof / n).is_symlink() and (prof / n).resolve() == (root / n).resolve()
    assert not (prof / "google_token.json.bak-1").exists() and not (prof / "config.yaml").exists()
    assert "accounts: primary, work" in al.note(got)


def test_never_overwrites_and_is_idempotent(tmp_path):
    root, prof = _root(tmp_path)
    (prof / "google_token.json").write_text('{"own": true}')
    got = al.link_existing(prof)
    assert "google_token.json" not in got and (prof / "google_token.json").read_text() == '{"own": true}'
    assert al.link_existing(prof) == []


def test_nothing_to_link_says_nothing(tmp_path):
    prof = tmp_path / "hermes" / "profiles" / "acme"
    prof.mkdir(parents=True)
    assert al.link_existing(prof) == [] and al.note([]) is None
