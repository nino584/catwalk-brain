"""Taste Core input: which posted items draw interest, and which convert.

Clients reply to Catwalk's own Instagram stories rather than sending supplier
links, so a story id is the closest thing the DM history has to an item id.
Counting the distinct people who asked about a story gives demand; following
what happened in the messages after each mention gives conversion.
"""

from __future__ import annotations

import csv
import re
from collections import defaultdict
from pathlib import Path

from ig_export import Thread
from signals import find_sizes, stage_hits

STORY_RE = re.compile(r"instagram\.com/stories/catwalk\.ge/(\d+)")
PRICE_RE = re.compile(r"(\d{2,5})\s*(?:ლარ|₾)")

# A mention is judged on the messages that follow it, up to the next mention.
WINDOW = 40
FULFILMENT = ("arrived", "awaiting_payment", "to_ship")

# Weight fees run about 15-45 GEL and are quoted in the same breath as the
# item price. Anything under this is a fee, not the price of the thing.
MIN_ITEM_PRICE = 50


def _mentions(t: Thread) -> list[tuple[int, str]]:
    out = []
    for i, m in enumerate(t.messages):
        for link in m.links + ([m.text] if m.text else []):
            for sid in STORY_RE.findall(link or ""):
                out.append((i, sid))
    return out


def analyse(threads: list[Thread]) -> dict[str, dict]:
    items: dict[str, dict] = defaultdict(
        lambda: {"asks": 0, "threads": set(), "quoted": 0, "converted": 0,
                 "prices": [], "sizes": set(), "first": None, "last": None}
    )

    for t in threads:
        mentions = _mentions(t)
        for n, (idx, sid) in enumerate(mentions):
            stop = mentions[n + 1][0] if n + 1 < len(mentions) else len(t.messages)
            end = min(stop, idx + WINDOW, len(t.messages))
            window = t.messages[idx:end]

            it = items[sid]
            it["asks"] += 1
            it["threads"].add(t.thread_id)

            day = t.messages[idx].at.date()
            if it["first"] is None or day < it["first"]:
                it["first"] = day
            if it["last"] is None or day > it["last"]:
                it["last"] = day

            # The first price Catwalk names after the question is the item's.
            prices = [int(p) for m in window if m.sender == t.owner
                      for p in PRICE_RE.findall(m.text or "")
                      if int(p) >= MIN_ITEM_PRICE]
            if prices:
                it["quoted"] += 1
                it["prices"].append(prices[0])

            text = " ".join(m.text for m in window if m.text)
            if any(s in stage_hits(text) for s in FULFILMENT):
                it["converted"] += 1
            it["sizes"].update(find_sizes(
                " ".join(m.text for m in window if m.sender != t.owner and m.text)
            ))

    return items


FIELDS = ["story_id", "people_asked", "price_quoted", "converted", "conversion_pct",
          "price_min", "price_max", "sizes_asked", "first_seen", "last_seen", "story_url"]


def rows(items: dict[str, dict]) -> list[dict]:
    out = []
    for sid, it in items.items():
        people = len(it["threads"])
        prices = it["prices"]
        out.append({
            "story_id": sid,
            "people_asked": people,
            "price_quoted": it["quoted"],
            "converted": it["converted"],
            "conversion_pct": round(it["converted"] * 100 / it["asks"]) if it["asks"] else 0,
            "price_min": min(prices) if prices else "",
            "price_max": max(prices) if prices else "",
            "sizes_asked": ";".join(sorted(it["sizes"])),
            "first_seen": it["first"].isoformat() if it["first"] else "",
            "last_seen": it["last"].isoformat() if it["last"] else "",
            "story_url": f"https://www.instagram.com/stories/catwalk.ge/{sid}",
        })
    out.sort(key=lambda r: (r["people_asked"], r["converted"]), reverse=True)
    return out


def write(items: dict[str, dict], out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows(items))
    return out_path
