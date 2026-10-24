"""Claude Code Stop hook: save the last answer so whisperkey can read it aloud.

    "Stop": [{ "hooks": [{ "type": "command",
      "command": "python C:\\path\\to\\whisperkey\\tools\\save_last_answer.py" }] }]

Writes `~/.claude/last-answer.txt` (or the path given as the first argument)
after every reply. Headless `claude -p` runs are skipped - those are scripts,
not answers someone wants to hear.

It also writes `~/.claude/last-session.json` with the process id of the
Claude Code session that answered: spoken dictation is typed into that
session in the background (whisperkey `voice_target`).
"""

import ctypes
import json
import os
import sys
import time
from ctypes import wintypes as w

TARGET = os.path.join(os.path.expanduser("~"), ".claude", "last-answer.txt")
SESSION = os.path.join(os.path.expanduser("~"), ".claude", "last-session.json")


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", w.DWORD), ("cntUsage", w.DWORD), ("th32ProcessID", w.DWORD),
                ("th32DefaultHeapID", ctypes.c_void_p), ("th32ModuleID", w.DWORD),
                ("cntThreads", w.DWORD), ("th32ParentProcessID", w.DWORD),
                ("pcPriClassBase", w.LONG), ("dwFlags", w.DWORD), ("szExeFile", w.WCHAR * 260)]


def claude_pid() -> int | None:
    """Walk up from this hook to the Claude Code process that ran it."""
    k32 = ctypes.windll.kernel32
    k32.CreateToolhelp32Snapshot.restype = w.HANDLE
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)       # TH32CS_SNAPPROCESS
    procs = {}
    entry = _PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(entry)
    ok = k32.Process32FirstW(snap, ctypes.byref(entry))
    while ok:
        procs[entry.th32ProcessID] = (entry.th32ParentProcessID, entry.szExeFile.lower())
        ok = k32.Process32NextW(snap, ctypes.byref(entry))
    k32.CloseHandle(snap)
    pid = os.getpid()
    for _ in range(12):
        parent, _exe = procs.get(pid, (0, ""))
        if not parent or parent not in procs:
            return None
        if procs[parent][1] in ("claude.exe", "node.exe"):
            return parent
        pid = parent
    return None


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
    pid = claude_pid() if sys.platform == "win32" else None
    if pid:
        with open(SESSION, "w", encoding="utf-8") as f:
            json.dump({"pid": pid, "time": time.time(), "cwd": data.get("cwd", "")}, f)


if __name__ == "__main__":
    main()
