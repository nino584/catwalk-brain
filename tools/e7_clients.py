"""E7 -- client base migration source, built from Instagram DM threads.

One row per counterpart: who they are, when they were active, what they
ordered, the phone and sizes they mentioned. Output stays under data/ because
it is personal data (see CLAUDE.md).
"""

from __future__ import annotations

import csv
from pathlib import Path

from ig_export import Thread
from signals import find_phones, find_sizes, stage_hits, cancel_reason, looks_like_order

FIELDS = [
    "ig_username",
    "thread_title",
    "first_seen",
    "last_seen",
    "days_active",
    "messages_total",
    "messages_client",
    "messages_catwalk",
    "phones",
    "sizes",
    "item_links",
    "stages_seen",
    "cancel_reason",
    "looks_like_order",
    "segment_hint",
]


def _segment_hint(order_like_threads: int, msgs: int) -> str:
    """Rough pre-segment; the real segment is computed from GMV after migration."""
    if order_like_threads >= 2:
        return "განმეორებითი"
    if order_like_threads == 1:
        return "მყიდველი"
    if msgs >= 4:
        return "დაინტერესებული"
    return "შემხებლობა"


def build_rows(threads: list[Thread]) -> list[dict]:
    by_client: dict[str, dict] = {}

    for t in threads:
        names = t.counterparts or [t.title]
        # Group chats have several counterparts and are not a single client.
        if len(names) != 1:
            continue
        name = names[0]

        client_msgs = t.by_client()
        owner_msgs = t.by_owner()
        text = t.text
        links = sorted({link for m in t.messages for link in m.links})
        stages = stage_hits(text)
        is_order = looks_like_order(text)

        row = by_client.setdefault(
            name,
            {
                "ig_username": name,
                "thread_title": t.title,
                "first_seen": None,
                "last_seen": None,
                "messages_total": 0,
                "messages_client": 0,
                "messages_catwalk": 0,
                "_phones": set(),
                "_sizes": set(),
                "_links": set(),
                "_stages": set(),
                "cancel_reason": "",
                "_order_threads": 0,
            },
        )

        first, last = t.first_at, t.last_at
        if first and (row["first_seen"] is None or first < row["first_seen"]):
            row["first_seen"] = first
        if last and (row["last_seen"] is None or last > row["last_seen"]):
            row["last_seen"] = last

        row["messages_total"] += len(t.messages)
        row["messages_client"] += len(client_msgs)
        row["messages_catwalk"] += len(owner_msgs)
        row["_phones"].update(find_phones(text))
        row["_sizes"].update(find_sizes(" ".join(m.text for m in client_msgs)))
        row["_links"].update(links)
        row["_stages"].update(stages)
        row["_order_threads"] += 1 if is_order else 0
        row["cancel_reason"] = row["cancel_reason"] or (cancel_reason(text) or "")

    rows = []
    for row in by_client.values():
        first, last = row["first_seen"], row["last_seen"]
        rows.append(
            {
                "ig_username": row["ig_username"],
                "thread_title": row["thread_title"],
                "first_seen": first.date().isoformat() if first else "",
                "last_seen": last.date().isoformat() if last else "",
                "days_active": (last - first).days if first and last else 0,
                "messages_total": row["messages_total"],
                "messages_client": row["messages_client"],
                "messages_catwalk": row["messages_catwalk"],
                "phones": ";".join(sorted(row["_phones"])),
                "sizes": ";".join(sorted(row["_sizes"])),
                "item_links": ";".join(sorted(row["_links"])),
                "stages_seen": ";".join(sorted(row["_stages"])),
                "cancel_reason": row["cancel_reason"],
                "looks_like_order": "yes" if row["_order_threads"] else "no",
                "segment_hint": _segment_hint(row["_order_threads"], row["messages_total"]),
            }
        )

    rows.sort(key=lambda r: (r["last_seen"], r["messages_total"]), reverse=True)
    return rows


def write(rows: list[dict], out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return out_path
