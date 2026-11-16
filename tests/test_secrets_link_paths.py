"""Audit 2026-11-16: a bot memory holding a course link (lowercase words and a long number joined by "/" and "-")
was read as a 90-character "random word" and refused a whole export. Synthetic texts only."""
import pytest

from twin import bot_export, secrets

COURSE = ("Course page: https://lms.example.edu/courses/123456789012345678/pages/"
          "week-3-module-overview-and-readings-2026-term-6 (sign in yourself).")


def test_a_plain_link_path_is_not_a_secret():
    assert not secrets.has_secret(COURSE)
    assert not secrets.has_secret("briefs in /workspace/courses/abc90100/week-3-module-notes-and-drafts/")
    assert not secrets.has_secret("see https://docs.example.org/guides/2026/section-12-assessment-rubric-and-marking-guide")


@pytest.mark.parametrize("text", [
    # a long random path part (a capability link) still counts
    "https://files.example.com/d/9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08/view",
    "https://x.example.com/a/q8w7e6r5t4y3u2i1o9p8a7s6d5f4g3h2j1k0l9z8x7c6v5",
    # capitals in the path: judged whole, as before
    "https://hooks.example.com/services/T00000000/B00000000/XXXXXXXXXXXXXXXXXXXXXXXXaB12cdEFgh34",
    # not in a link: as before
    "path/without/link/abc123def456ghi789jkl012mno345pqr678",
    # a query value: sign_in_value, as before
    "https://x.example.com/a?token=abcdef1234567890",
])
def test_secrets_in_links_are_still_found(text):
    assert secrets.has_secret(text)


def _doc(memory):
    return {"format": bot_export.FORMAT, "bot_name": "Course Bot", "instructions": "", "skills": [],
            "memory": memory}


def test_the_export_with_a_course_link_in_memory_passes():
    out = bot_export.validate(_doc(["first note", COURSE, "third"]), "Course Bot")
    assert out["memory"][1] == COURSE


def test_a_refused_memory_names_the_kind_and_line_never_the_value():
    key = "q8w7e6r5t4y3u2i1o9p8a7s6d5f4g3h2j1k0l9z8x7c6v5"
    with pytest.raises(bot_export.Bad) as e:
        bot_export.validate(_doc(["ok", f"line one\nhttps://x.example.com/a/{key}"]), "Course Bot")
    msg = str(e.value)
    assert "memory 2" in msg and "line 2" in msg and "long word that looks random" in msg
    assert key not in msg
