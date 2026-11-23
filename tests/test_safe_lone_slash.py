"""A lone slash between words is not a path (live: 'Browser / computer use' showed as 'Browser [path] computer use')."""
from twin import safe


def test_a_lone_slash_between_words_is_kept():
    assert safe.redact("Browser / computer use") == "Browser / computer use"


def test_real_paths_are_still_redacted():
    assert safe.redact("saved to /Users/someone/x.txt today") == "saved to [path] today"
    assert safe.redact("see ~/notes and ./a/b") == "see [path] and [path]"
    assert safe.redact(r"C:\Users\x") == "[path]"
