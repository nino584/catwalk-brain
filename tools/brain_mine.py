"""Catwalk Brain -- mine recurring questions and answers out of the DM history.

Produces two drafts for Anako: the questions clients keep asking (candidate
SOP topics) and the answers Catwalk keeps sending (candidate templates, with
the varying parts turned into {variables}).
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from ig_export import Thread
from signals import is_question

MIN_REPEATS = 3
MAX_ITEMS = 40

# Parts of an answer that change every time become template variables.
VARIABLE_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Bank details first: an IBAN must never survive into a reusable template.
    (re.compile(r"\bGE\d{2}[A-Z]{2}\d{14,18}\b"), "{ანგარიში}"),
    (re.compile(r"\b\d{1,3}[.,]\d+\s*(?:კგ|kg)\b", re.IGNORECASE), "{წონა}"),
    (re.compile(r"\b\d+\s*(?:ლარ|₾|gel)\w*", re.IGNORECASE), "{თანხა}"),
    (re.compile(r"\b[A-Z]{2}\d{6,}[A-Z]{0,2}\b"), "{ტრეკინგი}"),
    (re.compile(r"\b\d{1,2}[./]\d{1,2}(?:[./]\d{2,4})?\b"), "{თარიღი}"),
    (re.compile(r"\b\d{1,3}\s*[-–]\s*\d{1,3}\s*(?:სამუშაო\s*)?დღ\w*"), "{ვადა}"),
    (re.compile(r"https?://\S+"), "{ლინკი}"),
    (re.compile(r"(?<!\d)5(?:[\s\-\.]?\d){8}(?!\d)"), "{ტელეფონი}"),
    (re.compile(r"\b\d+\b"), "{რიცხვი}"),
]


def templatize(text: str) -> str:
    """Replace the varying parts of a message so repeats collapse together."""
    out = text.strip()
    for pattern, placeholder in VARIABLE_PATTERNS:
        out = pattern.sub(placeholder, out)
    return re.sub(r"\s+", " ", out).strip()


def _normalize_key(text: str) -> str:
    """Loose key for grouping: templatized, lowercased, punctuation dropped."""
    key = templatize(text).lower()
    key = re.sub(r"[^\w{}ა-ჰ ]+", " ", key)
    return re.sub(r"\s+", " ", key).strip()


def _collect(messages: list[str]) -> list[tuple[str, int, str]]:
    """Group messages by normalized key; return (key, count, sample) sorted."""
    counts: Counter[str] = Counter()
    samples: dict[str, str] = {}
    for text in messages:
        stripped = text.strip()
        if len(stripped) < 6:
            continue
        key = _normalize_key(stripped)
        if not key:
            continue
        counts[key] += 1
        samples.setdefault(key, stripped)
    return [(key, n, samples[key]) for key, n in counts.most_common() if n >= MIN_REPEATS]


def mine(threads: list[Thread]) -> dict[str, list[tuple[str, int, str]]]:
    client_questions = []
    owner_answers = []
    for t in threads:
        for m in t.by_client():
            if m.text and is_question(m.text):
                client_questions.append(m.text)
        for m in t.by_owner():
            if m.text:
                owner_answers.append(m.text)
    return {
        "questions": _collect(client_questions)[:MAX_ITEMS],
        "answers": _collect(owner_answers)[:MAX_ITEMS],
    }


def render(mined: dict[str, list[tuple[str, int, str]]], thread_count: int) -> str:
    lines = [
        "# Brain: კანდიდატები ჩატებიდან",
        "",
        "ავტომატურად გამოტანილი. **ეს ჯერ წესი არ არის** — ანაკომ უნდა გადაამოწმოს,",
        "გაასწოროს და გადაიტანოს `docs/brain/sop/`, `rules/`, `templates/`-ში.",
        "",
        f"წყარო: {thread_count} ჩატი. ზღვარი: მინიმუმ {MIN_REPEATS} გამეორება.",
        "",
        "## 1. კლიენტების განმეორებადი კითხვები → `sop/` კანდიდატები",
        "",
        "| # | გამეორება | კითხვა (ნიმუში) |",
        "|---|---|---|",
    ]
    for i, (_key, n, sample) in enumerate(mined["questions"], start=1):
        lines.append(f"| {i} | {n} | {sample.replace('|', '/')} |")

    lines += [
        "",
        "## 2. ჩვენი განმეორებადი პასუხები → `templates/` კანდიდატები",
        "",
        "ცვლადები ავტომატურად დაბლოკილია `{...}`-ით.",
        "",
        "| # | გამეორება | შაბლონი |",
        "|---|---|---|",
    ]
    for i, (_key, n, sample) in enumerate(mined["answers"], start=1):
        lines.append(f"| {i} | {n} | {templatize(sample).replace('|', '/')} |")

    lines += [
        "",
        "## რა უნდა გააკეთოს ანაკომ",
        "",
        "1. ზედა 8 პასუხი → `templates/` (მინიმუმი გასაშვებად 8 შაბლონი).",
        "2. ზედა 6 კითხვა → `sop/`, თითო ფაილი თითო პროცესზე.",
        "3. ციფრები (ტარიფი, ვადა, მინ. ფასი) → `rules/`.",
        "4. ყოველ ფაილს თავში: `განახლდა: თარიღი · ვინ`.",
        "",
    ]
    return "\n".join(lines) + "\n"


def write(mined: dict, thread_count: int, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render(mined, thread_count), encoding="utf-8")
    return out_path
