"""What gets read aloud: markdown → plain sentences, split into chapters.

Pure and dependency free (like `states.py`), so it is tested without audio.
"""

from __future__ import annotations

import re


def clean(text: str) -> str:
    """Markdown → plain speech: drop code, tables, links and markup."""
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = "\n".join(s for s in text.splitlines() if not s.lstrip().startswith("|"))
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\[\[([^\]|]+)(\|([^\]]+))?\]\]", lambda m: m.group(3) or m.group(1), text)
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"^\s*(#+|>|[-*+]|\d+\.)\s+", "", text, flags=re.M)
    text = re.sub(r"[*_~]{1,3}", "", text)
    text = re.sub(r"\s*(→|->|=>)\s*", ", ", text)
    return re.sub(r"[ \t]+", " ", text).strip()


def sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?:;])\s+|\n+", text)
    return [p.strip() for p in parts if re.search(r"\w", p)]


_HEADING = re.compile(r"^\s*#{1,6}\s+(.+?)\s*#*\s*$")
_LABEL = re.compile(r"^\s*(?:[-*+]\s+)?\*\*([^*\n]{1,48}?)[:.]?\*\*[:.]?\s*")


def chapters(raw: str) -> list[tuple[str, str]]:
    """Split markdown into (title, text) chapters, like video chapters.

    A chapter starts at a heading or at a paragraph that opens with a bold
    label ("**Speed:** ..."). Without either, every paragraph is a chapter.
    The title is the heading/label, else the first words of the text.
    """
    raw = re.sub(r"```.*?```", " ", raw, flags=re.S)
    out: list[list[str]] = []          # [title, body]
    marked = False
    for para in re.split(r"\n\s*\n", raw):
        first = para.lstrip().splitlines()[0] if para.strip() else ""
        head = _HEADING.match(first)
        label = _LABEL.match(para)
        if head:
            out.append([clean(head.group(1)), para.split("\n", 1)[1] if "\n" in para.strip() else ""])
            marked = True
        elif label:
            out.append([clean(label.group(1)), para[label.end():]])
            marked = True
        elif out:
            out[-1][1] += "\n\n" + para
        else:
            out.append(["", para])
    if not marked:
        out = [["", p] for p in re.split(r"\n\s*\n", raw)]
    result = []
    for title, body in out:
        body = clean(body)
        if not sentences(body) and not title:
            continue
        if not title:
            words = body.split()
            title = " ".join(words[:5]) + ("…" if len(words) > 5 else "")
        result.append((title, body))
    return result
