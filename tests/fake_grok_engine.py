"""A fake `botport grok` for tests: replays JSON answers from a scenario file, in order, per command.

Tests install it as an executable (their own interpreter in the shebang) and give it, in its environment:
  FAKE_GROK_SCENARIO  a JSON file {"<command>": [answer, ...]}; command is the word after `grok` (status, bots,
                      ask, wait, read, routines). Each answer: {"rc": int, "stdout": {...} | "raw text",
                      "stderr": "...", "log": [entry, ...]}. The last answer of a command repeats when the list
                      runs out; a command with no answers exits 1 with no output.
  FAKE_GROK_CALLS     the plugin's one-prompt log (calls.jsonl): each `log` entry is appended to it, with "at" set
                      to now (what `hermes twin from-grok` / `chat-sync` write when the bot runs them).
  FAKE_GROK_ARGV      every call's argv is appended here as one JSON line.
An answer may also carry "write": {"name": N, "content": TEXT} (for `files <bot> fetch ... --out DIR`): the stub
writes TEXT to DIR/N, as botport does (0600), and adds name, saved_to, bytes and sha256 to its JSON answer.
The answers are synthetic shapes of botport's frozen docs/GROK-ENGINE-INTERFACES.md (invented bots only): every
JSON answer gets `exit` (= rc) and a `proof` line unless it gives its own; the proof is repeated on stderr.
"""
import json
import os
import sys
import time


def main() -> int:
    argv = sys.argv[1:]
    with open(os.environ["FAKE_GROK_ARGV"], "a", encoding="utf-8") as f:
        f.write(json.dumps(argv) + "\n")
    if len(argv) < 2 or argv[0] != "grok":
        return 1
    cmd = argv[1]
    path = os.environ["FAKE_GROK_SCENARIO"]
    with open(path, encoding="utf-8") as f:
        scen = json.load(f)
    seen_path = path + ".seen"
    seen = json.load(open(seen_path, encoding="utf-8")) if os.path.exists(seen_path) else {}
    answers = scen.get(cmd) or []
    if not answers:
        return 1
    i = seen.get(cmd, 0)
    ans = answers[min(i, len(answers) - 1)]
    seen[cmd] = i + 1
    with open(seen_path, "w", encoding="utf-8") as f:
        json.dump(seen, f)
    for entry in ans.get("log") or []:
        e = dict(entry)
        e["at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with open(os.environ["FAKE_GROK_CALLS"], "a", encoding="utf-8") as f:
            f.write(json.dumps(e) + "\n")
    out = ans.get("stdout", {})
    rc = int(ans.get("rc", 0))
    if ans.get("write") and "--out" in argv:
        import hashlib
        w = ans["write"]
        data = w["content"].encode("utf-8")
        path = os.path.join(argv[argv.index("--out") + 1], w["name"])
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        sha = hashlib.sha256(data).hexdigest()
        out = {"name": w["name"], "saved_to": path, "bytes": len(data), "sha256": w.get("sha256", sha),
               "app_sha256": sha, **(out if isinstance(out, dict) else {})}
    if isinstance(out, dict):
        out = {"exit": rc, "proof": ans.get("stderr") or ("PASS: fake; replayed" if rc == 0 else "FAIL: fake; replayed"),
               **out}
        sys.stderr.write(out["proof"] + "\n")
    elif ans.get("stderr"):
        sys.stderr.write(ans["stderr"] + "\n")
    sys.stdout.write(out if isinstance(out, str) else json.dumps(out))
    return rc


if __name__ == "__main__":
    sys.exit(main())
