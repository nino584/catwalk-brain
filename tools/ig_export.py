"""Shared loader for an Instagram "Download your information" (JSON) export.

Instagram writes UTF-8 bytes escaped as latin-1 in its JSON, so Georgian text
comes out as mojibake until it is re-decoded. Everything downstream depends on
that fix, so it lives here.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


def demojibake(text: str) -> str:
    """Recover UTF-8 text that Instagram escaped as latin-1."""
    if not text:
        return text
    try:
        return text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


def _walk(value):
    """Apply demojibake to every string inside a nested JSON structure."""
    if isinstance(value, str):
        return demojibake(value)
    if isinstance(value, list):
        return [_walk(v) for v in value]
    if isinstance(value, dict):
        return {_walk(k): _walk(v) for k, v in value.items()}
    return value


@dataclass
class Message:
    sender: str
    timestamp_ms: int
    text: str
    links: list[str] = field(default_factory=list)
    has_media: bool = False
    photos: list[str] = field(default_factory=list)

    @property
    def at(self) -> datetime:
        return datetime.fromtimestamp(self.timestamp_ms / 1000, tz=timezone.utc)


@dataclass
class Thread:
    thread_id: str
    title: str
    participants: list[str]
    messages: list[Message]
    source: Path
    owner: str = ""

    @property
    def counterparts(self) -> list[str]:
        """Participants other than the account that owns the export."""
        return [p for p in self.participants if p != self.owner]

    @property
    def first_at(self) -> datetime | None:
        return self.messages[0].at if self.messages else None

    @property
    def last_at(self) -> datetime | None:
        return self.messages[-1].at if self.messages else None

    def by_owner(self) -> list[Message]:
        return [m for m in self.messages if m.sender == self.owner]

    def by_client(self) -> list[Message]:
        return [m for m in self.messages if m.sender != self.owner]

    @property
    def text(self) -> str:
        return "\n".join(m.text for m in self.messages if m.text)


LINK_RE = re.compile(r"https?://[^\s<>\"']+")


def _message_from_raw(raw: dict) -> Message | None:
    sender = raw.get("sender_name") or ""
    ts = raw.get("timestamp_ms")
    if ts is None:
        return None
    text = raw.get("content") or ""
    links = LINK_RE.findall(text)
    share = raw.get("share")
    if isinstance(share, dict) and share.get("link"):
        links.append(share["link"])
    has_media = bool(raw.get("photos") or raw.get("videos") or raw.get("audio_files"))
    return Message(sender=sender, timestamp_ms=int(ts), text=text, links=links, has_media=has_media)


def load_thread(path: Path, owner: str = "") -> Thread | None:
    """Load one message_*.json file. Returns None if it is not a message file."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return None
    if not isinstance(raw, dict) or "messages" not in raw:
        return None
    raw = _walk(raw)

    participants = [p.get("name", "") for p in raw.get("participants", []) if isinstance(p, dict)]
    messages = [m for m in (_message_from_raw(r) for r in raw.get("messages", [])) if m]
    messages.sort(key=lambda m: m.timestamp_ms)

    return Thread(
        thread_id=raw.get("thread_path") or path.parent.name,
        title=raw.get("title") or path.parent.name,
        participants=participants,
        messages=messages,
        source=path,
        owner=owner,
    )


def guess_owner(threads: list[Thread]) -> str:
    """The account that owns the export appears in nearly every thread.

    A thread is titled after the counterpart, so a sender matching its own
    thread title is the client, never the owner. That rule alone settles a
    single-thread export, where counting would be a coin flip.
    """
    counts: dict[str, int] = {}
    for t in threads:
        title = (t.title or "").strip()
        for name in {m.sender for m in t.messages if m.sender}:
            if name.strip() == title:
                continue
            counts[name] = counts.get(name, 0) + 1
    if not counts:
        return ""
    return max(counts.items(), key=lambda kv: kv[1])[0]


def load_thread_html(path: Path) -> Thread | None:
    """Load one message_*.html page (the HTML flavour of the export)."""
    from ig_html import parse_thread_html

    parsed = parse_thread_html(path)
    if not parsed:
        return None

    messages = [
        Message(
            sender=m["sender_name"],
            timestamp_ms=m["timestamp_ms"],
            text=m["content"],
            links=m["links"],
            has_media=m["has_media"],
            photos=m.get("photos", []),
        )
        for m in parsed["messages"]
    ]
    messages.sort(key=lambda m: m.timestamp_ms)
    senders = sorted({m.sender for m in messages if m.sender})

    return Thread(
        thread_id=path.parent.name,
        title=parsed["title"],
        participants=senders,
        messages=messages,
        source=path,
    )


def load_export(root: Path) -> list[Thread]:
    """Find and load every conversation under an export directory.

    Handles both flavours Instagram ships -- JSON and HTML -- and the several
    layouts (``messages/inbox/``, ``your_instagram_activity/messages/inbox/``,
    or a bare folder of threads).
    """
    threads: list[Thread] = []
    for path in sorted(p for p in root.rglob("message_*.json") if p.is_file()):
        t = load_thread(path)
        if t and t.messages:
            threads.append(t)
    for path in sorted(p for p in root.rglob("message_*.html") if p.is_file()):
        t = load_thread_html(path)
        if t and t.messages:
            threads.append(t)

    # Threads split across message_1.json, message_2.json ... belong together.
    merged: dict[str, Thread] = {}
    for t in threads:
        key = t.thread_id
        if key in merged:
            merged[key].messages.extend(t.messages)
            merged[key].messages.sort(key=lambda m: m.timestamp_ms)
        else:
            merged[key] = t
    result = list(merged.values())

    owner = guess_owner(result)
    for t in result:
        t.owner = owner
    return result
