"""Build the taste test from the photos Catwalk itself sent clients.

    python3 tools/build_photo_test.py <export-dir> --photos <unzipped-photos-dir>

Why these and not the order sheet: the sheet has no images at all, story links
expire, and every supplier site is unreachable from here. What survives is the
export itself. Catwalk sends the client a photograph of the item and quotes its
price in the same breath, which makes those messages the only cards that carry
a real picture, a real price, and a real outcome.

Two passes. The first names the photo files worth having, so a specific handful
can be zipped instead of the ~12,000 an export holds. The second, once those
files exist locally, embeds them as data URIs -- an artifact cannot load an
external image, and a link to one would break the same way the story links did.

The outcome (did the thread reach fulfilment) is carried in the manifest for
scoring and deliberately kept out of the cards.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import random
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ig_export import Thread, load_export
from signals import stage_hits

PRICE_RE = re.compile(r"(\d{2,5})\s*(?:ლარ|₾)")

# Weight fees sit around 15-45 GEL and are quoted alongside the item price.
MIN_ITEM_PRICE = 50
# How far past the photo to look for the price and for the outcome.
PRICE_WINDOW = 6
OUTCOME_WINDOW = 30
FULFILMENT = ("arrived", "awaiting_payment", "to_ship")

# Spread the sample over the price range rather than the middle of it.
BANDS = [(50, 200), (200, 400), (400, 700), (700, 1100), (1100, 10 ** 9)]
SHARE = {(50, 200): 0.20, (200, 400): 0.25, (400, 700): 0.20,
         (700, 1100): 0.175, (1100, 10 ** 9): 0.175}

CARD_PX = 760
CARD_QUALITY = 72

# The whole selection has to fit in one pasted shell command, because a list
# file has to be downloaded first and that step kept failing.
MAX_PATH = 110


def candidates(threads: list[Thread]) -> list[dict]:
    """Photos Catwalk sent with a price named just after."""
    out = []
    for t in threads:
        msgs = t.messages
        for i, m in enumerate(msgs):
            if m.sender != t.owner or not m.photos:
                continue
            price = None
            for j in range(i, min(len(msgs), i + PRICE_WINDOW)):
                if msgs[j].sender != t.owner:
                    continue
                for p in PRICE_RE.findall(msgs[j].text or ""):
                    if int(p) >= MIN_ITEM_PRICE:
                        price = int(p)
                        break
                if price:
                    break
            if not price:
                continue
            after = " ".join(x.text for x in msgs[i:i + OUTCOME_WINDOW] if x.text)
            out.append({
                "thread": t.thread_id,
                "photo": m.photos[0],
                "price": price,
                "sold": any(s in stage_hits(after) for s in FULFILMENT),
                "date": str(m.at.date()),
            })
    return out


def select(cands: list[dict], want: int, seed: int = 77) -> list[dict]:
    """Even split across price bands and, inside each, between sold and not."""
    rnd = random.Random(seed)
    buckets: dict[tuple, dict[str, list]] = defaultdict(lambda: {"sold": [], "not": []})
    seen = set()
    for c in cands:
        if c["photo"] in seen or len(c["photo"]) > MAX_PATH:
            continue
        seen.add(c["photo"])
        for band in BANDS:
            if band[0] <= c["price"] < band[1]:
                buckets[band]["sold" if c["sold"] else "not"].append(c)
                break

    picked = []
    for band in BANDS:
        quota = max(1, round(want * SHARE[band]))
        sold, unsold = buckets[band]["sold"][:], buckets[band]["not"][:]
        rnd.shuffle(sold)
        rnd.shuffle(unsold)
        half = quota // 2
        picked += sold[:half] + unsold[:quota - half]
    rnd.shuffle(picked)
    picked = picked[:want]
    for n, it in enumerate(picked, start=1):
        it["id"] = n
    return picked


def zip_command(picked: list[dict], export_name: str = "instagram-catwalk",
                out: str = "~/Desktop/foto.zip") -> str:
    """A single-line command that zips exactly these photos and nothing else."""
    paths = " ".join(it["photo"] for it in picked)
    return (f"cd ~/Downloads/{export_name} && rm -f {out} && "
            f"zip -q {out} {paths} && ls -lh {out}")


def build_cards(picked: list[dict], photo_root: Path) -> list[dict]:
    """Embed each photo as a data URI. Requires Pillow."""
    from PIL import Image

    on_disk = {p.name: p for p in photo_root.rglob("*")
               if p.suffix.lower() in {".jpg", ".jpeg", ".png"}}
    cards = []
    for it in picked:
        found = on_disk.get(Path(it["photo"]).name)
        if not found:
            continue
        img = Image.open(found).convert("RGB")
        img.thumbnail((CARD_PX, CARD_PX), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=CARD_QUALITY, optimize=True, progressive=True)
        cards.append({
            "i": it["id"], "p": it["price"], "d": it["date"],
            "img": "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode(),
        })
    return cards


def public(cards: list[dict]) -> list[dict]:
    """Cards as the page sees them -- never the outcome."""
    return [{"i": c["i"], "p": c["p"], "d": c["d"], "img": c["img"]} for c in cards]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="ფოტო-ბარათები გემოვნების ტესტისთვის")
    ap.add_argument("export", type=Path, help="გახსნილი Instagram ექსპორტი")
    ap.add_argument("--count", type=int, default=40)
    ap.add_argument("--photos", type=Path, help="გახსნილი ფოტოების საქაღალდე")
    ap.add_argument("--out", type=Path, default=Path("data/out/taste-cards"))
    args = ap.parse_args(argv)

    threads = load_export(args.export)
    cands = candidates(threads)
    sold = sum(1 for c in cands if c["sold"])
    print(f"კანდიდატი: {len(cands)} (გაიყიდა {sold}, არა {len(cands) - sold})")

    picked = select(cands, args.count)
    print(f"შერჩეული: {len(picked)} (გაიყიდა {sum(1 for p in picked if p['sold'])})")

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "manifest.json").write_text(
        json.dumps(picked, ensure_ascii=False, indent=1), encoding="utf-8")
    (args.out / "zip-command.txt").write_text(zip_command(picked) + "\n", encoding="utf-8")
    print(f"→ {args.out}/manifest.json · {args.out}/zip-command.txt")

    if not args.photos:
        print("\nფოტოები ჯერ არ არის. გაუშვი zip-command.txt ნინოს კომპიუტერზე,\n"
              "მერე იგივე ბრძანება --photos <საქაღალდე>-თი.")
        return 0

    cards = build_cards(picked, args.photos)
    (args.out / "cards.json").write_text(
        json.dumps(public(cards), ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8")
    size = sum(len(c["img"]) for c in cards) / 1024 / 1024
    print(f"ბარათი ფოტოთი: {len(cards)}/{len(picked)} · {size:.1f} MB")
    print(f"→ {args.out}/cards.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
