"""E11 -- pick 20 real chats for the Sales Copilot acceptance test.

The spec asks for 20 real conversations shown to two top sellers, who judge
"would I have sent this?". Selection aims for a realistic spread rather than
the 20 longest threads: sales that closed, sales that were lost, and pure
questions all have to be represented.
"""

from __future__ import annotations

from pathlib import Path

from ig_export import Thread
from signals import cancel_reason, is_question, looks_like_order, stage_hits

TARGET = 20


def classify(t: Thread) -> str:
    text = t.text
    stages = stage_hits(text)
    if cancel_reason(text) or "cancelled" in stages:
        return "დაკარგული"
    if looks_like_order(text):
        return "დახურული"
    if any(is_question(m.text) for m in t.by_client()):
        return "კითხვა"
    return "სხვა"


def score(t: Thread) -> float:
    """Prefer threads with real back-and-forth and a visible outcome."""
    client_msgs = t.by_client()
    owner_msgs = t.by_owner()
    if not client_msgs or not owner_msgs:
        return 0.0
    turns = min(len(client_msgs), len(owner_msgs))
    stages = len(stage_hits(t.text))
    questions = sum(1 for m in client_msgs if is_question(m.text))
    recency = (t.last_at.timestamp() if t.last_at else 0) / 1e12
    return turns * 2 + stages * 3 + questions + recency


def select(threads: list[Thread], target: int = TARGET) -> list[tuple[str, Thread]]:
    """Round-robin across categories so no single kind of chat dominates."""
    buckets: dict[str, list[Thread]] = {}
    for t in threads:
        if score(t) <= 0:
            continue
        buckets.setdefault(classify(t), []).append(t)
    for items in buckets.values():
        items.sort(key=score, reverse=True)

    # Categories that matter most to the Copilot test come first.
    order = [c for c in ("დახურული", "დაკარგული", "კითხვა", "სხვა") if c in buckets]
    picked: list[tuple[str, Thread]] = []
    index = 0
    while len(picked) < target and any(len(buckets[c]) > index for c in order):
        for category in order:
            if len(picked) >= target:
                break
            if len(buckets[category]) > index:
                picked.append((category, buckets[category][index]))
        index += 1
    return picked


def render(category: str, t: Thread, number: int) -> str:
    lines = [
        f"# ჩატი {number:02d} — {category}",
        "",
        f"- თრედი: `{t.thread_id}`",
        f"- პერიოდი: {t.first_at.date() if t.first_at else '?'} → {t.last_at.date() if t.last_at else '?'}",
        f"- შეტყობინება: {len(t.messages)} (კლიენტი {len(t.by_client())} / Catwalk {len(t.by_owner())})",
        "",
        "## დიალოგი",
        "",
    ]
    for m in t.messages:
        who = "Catwalk" if m.sender == t.owner else "კლიენტი"
        stamp = m.at.strftime("%d.%m %H:%M")
        body = m.text or ("[media]" if m.has_media else "")
        if not body:
            continue
        lines.append(f"**{who}** · {stamp}")
        lines.append(f"> {body}")
        for link in m.links:
            lines.append(f"> ლინკი: {link}")
        lines.append("")
    lines += [
        "## გამყიდველის შეფასება",
        "",
        "| კითხვა | პასუხი |",
        "|---|---|",
        "| Copilot-ის დრაფტს გავგზავნიდი? | yes / no |",
        "| რა შევცვალე? | |",
        "",
    ]
    return "\n".join(lines)


def write(selected: list[tuple[str, Thread]], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    index = [
        "# Copilot-ის სატესტო ნაკრები (E11)",
        "",
        "ზღვარი: 2 ტოპ-გამყიდველიდან „გავგზავნიდი“ ≥70%. ქვემოთ 20 რეალური ჩატი.",
        "",
        "| # | კატეგორია | თრედი | შეტყობინება | ფაილი |",
        "|---|---|---|---|---|",
    ]
    for i, (category, t) in enumerate(selected, start=1):
        name = f"chat-{i:02d}.md"
        (out_dir / name).write_text(render(category, t, i), encoding="utf-8")
        index.append(f"| {i} | {category} | `{t.thread_id}` | {len(t.messages)} | [{name}]({name}) |")

    index_path = out_dir / "README.md"
    index_path.write_text("\n".join(index) + "\n", encoding="utf-8")
    return index_path
