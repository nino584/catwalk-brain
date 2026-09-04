"""Run the three Instagram-export processors in one go.

    python3 tools/run_all.py <path-to-instagram-export> [--out data/out]

Outputs land under data/ by default, which is gitignored: DM history is
personal data and must not reach GitHub (see CLAUDE.md).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import brain_mine
import e7_clients
import e11_copilot
from ig_export import load_export


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Instagram DM export -> E7 / E11 / Brain")
    parser.add_argument("export", type=Path, help="unzipped Instagram export directory")
    parser.add_argument("--out", type=Path, default=Path("data/out"), help="output directory")
    args = parser.parse_args(argv)

    if not args.export.is_dir():
        print(f"შეცდომა: {args.export} არ არის საქაღალდე", file=sys.stderr)
        return 2

    threads = load_export(args.export)
    if not threads:
        print(
            f"შეცდომა: {args.export}-ში message_*.json ვერ ვიპოვე.\n"
            "დარწმუნდი, რომ ექსპორტი JSON ფორმატშია და გახსნილია (zip არა).",
            file=sys.stderr,
        )
        return 1

    owner = threads[0].owner
    total_msgs = sum(len(t.messages) for t in threads)
    print(f"ჩატი: {len(threads)} · შეტყობინება: {total_msgs} · ანგარიში: {owner}")

    rows = e7_clients.build_rows(threads)
    clients_path = e7_clients.write(rows, args.out / "clients.csv")
    with_phone = sum(1 for r in rows if r["phones"])
    with_order = sum(1 for r in rows if r["looks_like_order"] == "yes")
    print(f"E7  → {clients_path} · {len(rows)} კლიენტი "
          f"({with_phone} ტელეფონით, {with_order} შეკვეთის ნიშნით)")

    selected = e11_copilot.select(threads)
    copilot_path = e11_copilot.write(selected, args.out / "copilot-test-20")
    print(f"E11 → {copilot_path} · {len(selected)} ჩატი")

    mined = brain_mine.mine(threads)
    brain_path = brain_mine.write(mined, len(threads), args.out / "brain-candidates.md")
    print(f"Brain → {brain_path} · {len(mined['questions'])} კითხვა, "
          f"{len(mined['answers'])} შაბლონი")

    print("\nყველა შედეგი data/-შია და git-ში არ ადის.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
