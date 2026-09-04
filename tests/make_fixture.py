"""Build a synthetic Instagram export that mimics the real one, mojibake included.

Used by the tests; also handy for a dry run of the pipeline before the real
export arrives. No real client data ever goes in here.
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

OWNER = "Catwalk"

CLIENT_LINES = [
    "გამარჯობა, ეს კაბა თუ არის M ზომაში?",
    "რა ღირს ჩამოტანა?",
    "როდის ჩამოვა?",
    "ჩავრიცხე თანხა, გადაამოწმეთ",
    "ჩემი ნომერია 555123456",
    "S ზომა მინდა",
    "გამარჯობა, შეკვეთა სად არის?",
    "ტრეკინგი თუ გამომიგზავნით?",
    "ძვირია, გადავიფიქრე",
    "დიდი მადლობა!",
]

OWNER_LINES = [
    "გამარჯობა! დიახ, M ზომა არის.",
    "წონის ტარიფი S — 20 ლარი.",
    "ჩამოსვლა 14-21 სამუშაო დღეა.",
    "თანხა დაგვიდასტურდა, მადლობა.",
    "შეკვეთა გამოწერილია.",
    "ნივთი ჩამოვიდა, წონა 0.4 კგ, ჯამში 320 ლარი.",
    "ტრეკინგი: GE123456789DE",
    "სამწუხაროდ ეს ზომა აღარ იყო.",
    "გისურვებთ სასიამოვნო ტარებას!",
]

LINKS = [
    "https://www.yoox.com/item/12345",
    "https://www.zalando.de/item/67890",
    "https://www.bestsecret.com/product/111",
]


def escape_like_instagram(value):
    """Instagram writes UTF-8 bytes as latin-1 characters. Reproduce that."""
    if isinstance(value, str):
        return value.encode("utf-8").decode("latin-1")
    if isinstance(value, list):
        return [escape_like_instagram(v) for v in value]
    if isinstance(value, dict):
        return {escape_like_instagram(k): escape_like_instagram(v) for k, v in value.items()}
    return value


def build(root: Path, thread_count: int = 40, seed: int = 7) -> None:
    rnd = random.Random(seed)
    inbox = root / "your_instagram_activity" / "messages" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)

    base_ts = 1_750_000_000_000  # mid-2025, ms

    for i in range(thread_count):
        client = f"client_{i:03d}"
        folder = inbox / f"{client}_{rnd.randint(10**16, 10**17):d}"
        folder.mkdir(parents=True, exist_ok=True)

        n = rnd.randint(2, 14)
        ts = base_ts + i * 86_400_000
        messages = []
        for j in range(n):
            ts += rnd.randint(60_000, 3_600_000)
            if j % 2 == 0:
                text = rnd.choice(CLIENT_LINES)
                sender = client
            else:
                text = rnd.choice(OWNER_LINES)
                sender = OWNER
            entry = {"sender_name": sender, "timestamp_ms": ts, "content": text}
            if j == 0 and rnd.random() < 0.5:
                entry["share"] = {"link": rnd.choice(LINKS)}
            if rnd.random() < 0.15:
                entry["photos"] = [{"uri": "media/photo.jpg"}]
            messages.append(entry)

        # Instagram stores messages newest-first.
        payload = {
            "participants": [{"name": client}, {"name": OWNER}],
            "messages": list(reversed(messages)),
            "title": client,
            "thread_path": f"inbox/{folder.name}",
        }
        out = folder / "message_1.json"
        out.write_text(
            json.dumps(escape_like_instagram(payload), ensure_ascii=False, indent=1),
            encoding="utf-8",
        )


if __name__ == "__main__":
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "tests/fixtures/export")
    build(target)
    print(f"fixture written to {target}")
