"""Claude Code Stop hook: save the last answer so whisperkey can read it aloud.

    "Stop": [{ "hooks": [{ "type": "command",
      "command": "python C:\\path\\to\\whisperkey\\tools\\save_last_answer.py" }] }]

Writes `~/.claude/last-answer.txt` (or the path given as the first argument)
after every reply. Headless `claude -p` runs are skipped - those are scripts,
not answers someone wants to hear.
"""

import json
import os
import sys

TARGET = os.path.join(os.path.expanduser("~"), ".claude", "last-answer.txt")


def from_transcript(path: str) -> str:
    """Assistant text after the last real user message (older Claude Code versions)."""
    parts: list[str] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            content = (entry.get("message") or {}).get("content")
            if entry.get("type") == "user":
                # tool results also arrive as "user"; only real text resets
                if isinstance(content, str) or any(
                    isinstance(b, dict) and b.get("type") == "text" for b in content or []
                ):
                    parts = []
            elif entry.get("type") == "assistant" and isinstance(content, list):
                parts += [b["text"] for b in content if b.get("type") == "text" and b.get("text")]
    return "\n\n".join(parts)


def main() -> None:
    if os.environ.get("CLAUDE_CODE_ENTRYPOINT", "").startswith("sdk"):
        return
    try:
        # read bytes: on Windows sys.stdin decodes with the ANSI code page
        data = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    except ValueError:
        return
    text = data.get("last_assistant_message") or ""
    if not text and data.get("transcript_path"):
        try:
            text = from_transcript(data["transcript_path"])
        except OSError:
            return
    if text.strip():
        target = sys.argv[1] if len(sys.argv) > 1 else TARGET
        with open(os.path.expanduser(target), "w", encoding="utf-8") as f:
            f.write(text)


if __name__ == "__main__":
    main()
