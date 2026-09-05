"""Build the rubric's 100-item test: 50 core, 50 border.

    python3 tools/build_taste_test.py <export-dir> [--sheet data/sheet-orders.csv]

The two halves come from different evidence, because each half needs a
different kind of proof:

- **core** -- items that actually sold, taken from the order sheet, so each row
  carries a name, a brand, a price and the supplier link.
- **border** -- items several people asked about and nobody bought, taken from
  the DM history. These are the interesting ones: the taste, price or timing
  boundary sits exactly there. A story has no item name, so each row carries
  the client's own question and Catwalk's reply instead.

Output is docs/taste-core/test-100.csv, in the template's column order plus a
few columns that say where the row came from. Nino fills the six axes, the
verdict and the why; the AI answers the same 100 blind.
"""

from __future__ import annotations

import argparse
import csv
import random
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import taste_signals
from ig_export import load_export

CORE, BORDER = 50, 50

# Enough people asked that indifference is not the explanation.
BORDER_MIN_ASKS = 3

FIELDS = [
    "id", "set", "brand", "item_name", "price_gel", "link",
    "evidence", "photo_path",
    "silhouette", "color_material", "brand_score", "value", "season",
    "catwalkness", "verdict", "why",
]

BRANDS = [
    "valentino", "nike", "sandro", "jacquemus", "nakd", "golden goose", "maje",
    "all saints", "ganni", "adidas", "marni", "boss", "hugo", "isabel marant",
    "margiela", "mm6", "coach", "zadig", "acne", "ami", "carhartt", "gucci",
    "prada", "nude project", "off white", "off-white", "dr martens", "polo",
    "ralph", "tommy", "calvin", "guess", "furla", "pinko", "liu jo", "max mara",
    "twinset", "michael kors", "apc", "aloha", "stone island", "new balance",
    "birkenstock", "ugg", "lacoste", "levi", "kenzo", "versace", "bottega",
    "celine", "loewe", "autry", "veja", "asics", "balenciaga",
]


def brand_of(name: str) -> str:
    low = (name or "").lower()
    for b in BRANDS:
        if b in low:
            return b
    return ""


def _num(x):
    x = (x or "").replace("₾", "").replace(",", "").replace("%", "").strip()
    try:
        return float(x)
    except ValueError:
        return None


def core_rows(sheet: Path, want: int) -> list[dict]:
    """Items that sold, spread across brands and price bands.

    Picking the top sellers alone would hand Nino fifty near-identical rows, so
    walk the brands in turn and take the priciest unused item from each.
    """
    rows = list(csv.DictReader(sheet.open(encoding="utf-8")))
    by_brand: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        name = (r.get("ნივთი") or "").strip()
        price = _num(r.get("გასაყიდი ₾"))
        if not name or not price:
            continue
        status = (r.get("") or "").strip()
        if "გაუქმდა" in status:            # cancelled is not evidence of taste
            continue
        by_brand[brand_of(name) or "(სხვა)"].append({
            "name": name,
            "brand": (r.get("ბრენდი") or "").strip(),
            "label": brand_of(name) or "",
            "price": price,
            "markup": _num(r.get("Markup %")),
            "link": (r.get("ლინკი") or "").strip(),
            "size": (r.get("ზომა") or "").strip(),
        })

    for items in by_brand.values():
        items.sort(key=lambda d: -d["price"])

    order = sorted(by_brand, key=lambda b: -len(by_brand[b]))
    picked, seen, depth = [], set(), 0
    while len(picked) < want and any(len(by_brand[b]) > depth for b in order):
        for b in order:
            if len(picked) >= want:
                break
            if len(by_brand[b]) <= depth:
                continue
            it = by_brand[b][depth]
            key = it["name"].lower()
            if key in seen:
                continue
            seen.add(key)
            picked.append(it)
        depth += 1
    return picked[:want]


def border_rows(export: Path, want: int) -> list[dict]:
    """Stories several people asked about that never reached fulfilment."""
    threads = load_export(export)
    items = taste_signals.analyse(threads)

    # Keep the question that was actually asked, so the row reads as something.
    quotes: dict[str, tuple[str, str]] = {}
    for t in threads:
        msgs = t.messages
        for i, m in enumerate(msgs):
            haystack = " ".join(m.links + ([m.text] if m.text else []))
            for sid in taste_signals.STORY_RE.findall(haystack):
                if sid in quotes:
                    continue
                ask = (m.text or "").strip()
                ask = re.sub(r"https?://\S+", "", ask).strip()
                reply = next(
                    ((x.text or "").strip() for x in msgs[i + 1:i + 6]
                     if x.sender == t.owner and (x.text or "").strip()),
                    "",
                )
                if ask or reply:
                    quotes[sid] = (ask[:120], reply[:120])

    out = []
    for sid, it in items.items():
        if it["converted"] or len(it["threads"]) < BORDER_MIN_ASKS:
            continue
        ask, reply = quotes.get(sid, ("", ""))
        prices = it["prices"]
        out.append({
            "story": sid,
            "asked": len(it["threads"]),
            "price": max(prices) if prices else None,
            "sizes": ";".join(sorted(it["sizes"])),
            "ask": ask,
            "reply": reply,
            "first": it["first"],
        })
    out.sort(key=lambda d: -d["asked"])
    return out[:want]


def build(export: Path, sheet: Path, out_path: Path, seed: int = 11) -> Path:
    core = core_rows(sheet, CORE)
    border = border_rows(export, BORDER)

    rows = []
    for it in core:
        rows.append({
            "set": "core",
            "brand": it["brand"] or "Catwalk",
            "item_name": f"{it['label'] or ''} {it['name']}".strip(),
            "price_gel": f"{it['price']:.0f}",
            "link": it["link"],
            "evidence": f"გაიყიდა · markup {it['markup']:.0f}%" if it["markup"] is not None else "გაიყიდა",
            "photo_path": "",
        })
    for it in border:
        ask = it["ask"] or "—"
        rows.append({
            "set": "border",
            "brand": "",
            "item_name": f"[სთორი {it['story']}] კითხვა: {ask}",
            "price_gel": f"{it['price']:.0f}" if it["price"] else "",
            "link": f"https://www.instagram.com/stories/catwalk.ge/{it['story']}",
            "evidence": f"{it['asked']} ადამიანმა ჰკითხა, 0 იყიდა"
                        + (f" · ზომები {it['sizes']}" if it["sizes"] else ""),
            "photo_path": "",
        })

    # Shuffle so the two halves are not visibly grouped during scoring.
    random.Random(seed).shuffle(rows)
    for i, r in enumerate(rows, start=1):
        r["id"] = i
        for axis in ("silhouette", "color_material", "brand_score", "value",
                     "season", "catwalkness", "verdict", "why"):
            r[axis] = ""

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    return out_path


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="ავაწყოს რუბრიკის 100-ნივთიანი ტესტი")
    p.add_argument("export", type=Path, help="გახსნილი Instagram ექსპორტი")
    p.add_argument("--sheet", type=Path, default=Path("data/sheet-orders.csv"))
    p.add_argument("--out", type=Path, default=Path("docs/taste-core/test-100.csv"))
    a = p.parse_args(argv)

    if not a.sheet.exists():
        print(f"შეცდომა: {a.sheet} არ არსებობს", file=sys.stderr)
        return 2
    out = build(a.export, a.sheet, a.out)
    rows = list(csv.DictReader(out.open(encoding="utf-8-sig")))
    core = sum(1 for r in rows if r["set"] == "core")
    print(f"{out} · {len(rows)} ნივთი ({core} ბირთვი, {len(rows) - core} მოსაზღვრე)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
