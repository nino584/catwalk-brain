"""Reader for the HTML flavour of an Instagram export.

Instagram delivers either JSON or HTML depending on what was requested. The
HTML export nests each message in a card:

    <div class="... _a6-g ...">
      <h2 class="... _a6-h _a6-i">SENDER</h2>
      <div class="... _a6-p"> ...text, images, reactions... </div>
      <div class="... _a6-o">Aug 31, 2026 4:34 am</div>
    </div>

Unlike the JSON export the text is already valid UTF-8, so no mojibake fix is
needed here.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

SENDER_CLASS = "_a6-h"
CONTENT_CLASS = "_a6-p"
TIME_CLASS = "_a6-o"
CARD_CLASS = "_a6-g"
REACTION_CLASS = "_a6-q"

TIME_FORMATS = ("%b %d, %Y %I:%M %p", "%b %d, %Y %I:%M:%S %p", "%d %b %Y, %H:%M")

# Rows Instagram writes for reactions rather than real messages.
SYSTEM_TEXTS = {"liked a message", "reacted to your message"}


def _classes(attrs: list[tuple[str, str | None]]) -> set[str]:
    for name, value in attrs:
        if name == "class" and value:
            return set(value.split())
    return set()


def parse_timestamp(text: str) -> int | None:
    """Return epoch milliseconds for one of Instagram's HTML date strings."""
    cleaned = " ".join(text.split())
    for fmt in TIME_FORMATS:
        try:
            dt = datetime.strptime(cleaned, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        return int(dt.timestamp() * 1000)
    return None


class _ThreadParser(HTMLParser):
    """Collect one message card at a time out of a thread page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title: str = ""
        self.rows: list[dict] = []

        self._in_title = False
        self._card_depth: int | None = None
        self._depth = 0
        self._zone: str | None = None       # sender | content | time
        self._zone_depth: int | None = None
        self._reaction_depth: int | None = None
        self._card: dict = {}

    # -- helpers -------------------------------------------------------
    def _start_card(self) -> None:
        self._card = {"sender": "", "text": [], "time": "", "links": [], "media": False}

    def _finish_card(self) -> None:
        card = self._card
        if card.get("sender") or card.get("text"):
            self.rows.append(card)
        self._card = {}

    # -- HTMLParser ----------------------------------------------------
    def handle_starttag(self, tag, attrs):
        self._depth += 1
        if tag == "title":
            self._in_title = True
            return

        classes = _classes(attrs)

        if tag == "div" and CARD_CLASS in classes and self._card_depth is None:
            self._card_depth = self._depth
            self._start_card()
            return

        if self._card_depth is None:
            return

        if tag == "ul" and REACTION_CLASS in classes:
            self._reaction_depth = self._depth
        elif tag == "h2" and SENDER_CLASS in classes:
            self._zone, self._zone_depth = "sender", self._depth
        elif tag == "div" and CONTENT_CLASS in classes:
            self._zone, self._zone_depth = "content", self._depth
        elif tag == "div" and TIME_CLASS in classes:
            self._zone, self._zone_depth = "time", self._depth
        elif tag == "img":
            for name, value in attrs:
                if name == "src" and value and "/photos/" in value:
                    self._card["media"] = True
        elif tag == "a":
            for name, value in attrs:
                if name != "href" or not value:
                    continue
                if value.startswith("http"):
                    self._card["links"].append(value)
                elif "/photos/" in value or "/videos/" in value:
                    self._card["media"] = True

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if self._reaction_depth is not None and self._depth <= self._reaction_depth:
            self._reaction_depth = None
        if self._zone_depth is not None and self._depth <= self._zone_depth:
            self._zone, self._zone_depth = None, None
        if self._card_depth is not None and self._depth <= self._card_depth:
            self._finish_card()
            self._card_depth = None
        self._depth -= 1

    def handle_data(self, data):
        text = data.strip()
        if not text:
            return
        if self._in_title and not self.title:
            self.title = text
            return
        if self._card_depth is None or self._reaction_depth is not None:
            return
        if self._zone == "sender":
            self._card["sender"] = (self._card["sender"] + " " + text).strip()
        elif self._zone == "content":
            self._card["text"].append(text)
        elif self._zone == "time":
            self._card["time"] = (self._card["time"] + " " + text).strip()


LINK_RE = re.compile(r"https?://[^\s<>\"']+")


def parse_thread_html(path: Path) -> dict | None:
    """Parse a message_N.html page into {title, messages:[...]}."""
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    if CONTENT_CLASS not in raw:
        return None

    parser = _ThreadParser()
    parser.feed(raw)
    parser.close()

    messages = []
    for card in parser.rows:
        text = " ".join(card["text"]).strip()
        ts = parse_timestamp(card["time"]) if card["time"] else None
        if ts is None:
            continue
        if text.lower() in SYSTEM_TEXTS:
            continue
        links = list(dict.fromkeys(card["links"] + LINK_RE.findall(text)))
        if not text and not card["media"] and not links:
            continue
        messages.append(
            {
                "sender_name": card["sender"],
                "timestamp_ms": ts,
                "content": text,
                "links": links,
                "has_media": card["media"],
            }
        )

    if not messages:
        return None
    return {"title": parser.title or path.parent.name, "messages": messages}


def parse_chats_index(path: Path) -> list[tuple[str, str]]:
    """Read chats.html -- the table of contents -- as (display name, relative path)."""
    raw = path.read_text(encoding="utf-8", errors="replace")
    out = []
    for href, label in re.findall(r'<a href="([^"]*messages/inbox/[^"]+)">(.*?)</a>', raw, re.S):
        name = re.sub(r"<[^>]+>", "", label)
        out.append((" ".join(name.split()), href))
    return out
