"""Georgian-language signal extraction shared by the three processors."""

from __future__ import annotations

import re

# Georgian mobile numbers: 9 digits starting with 5, optionally +995 prefixed.
# Written every which way -- 555123456, 555 12 34 56, 555-123-456 -- so allow a
# separator between any two digits and normalize afterwards.
PHONE_RE = re.compile(r"(?<!\d)(?:\+?995[\s\-\.]?)?(5(?:[\s\-\.]?\d){8})(?!\d)")

SIZE_RE = re.compile(
    r"\b(XXS|XS|S|M|L|XL|XXL|3XL)\b|\b(3[4-9]|4[0-8])\s*(?:ზომა|размер)?\b",
    re.IGNORECASE,
)

# Keyword -> the order lifecycle stage it hints at. Georgian is agglutinative,
# so these are stems matched anywhere in the word.
STAGE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "to_order": ("გამოსაწერ", "შეკვეთ", "მინდა", "ვიყიდ"),
    "ordered": ("გამოვწერ", "გამოწერილ", "შევუკვეთ"),
    "arrived": ("ჩამოვიდა", "ჩამოსვლ", "წონა"),
    "awaiting_payment": ("ჩარიცხ", "ჩავრიცხ", "გადავრიცხ", "თანხ"),
    "to_ship": ("ტრეკინგ", "გასაგზავნ", "გამოგზავნ", "კურიერ"),
    "done": ("მადლობა", "მივიღე", "გილოცავ"),
    "cancelled": ("გაუქმ", "გადავიფიქრ", "აღარ მინდა", "აღარ იყო"),
}

CANCEL_REASONS: dict[str, tuple[str, ...]] = {
    "ზომა აღარ იყო": ("ზომა აღარ", "ზომა არ არის", "ზომა გათავდა"),
    "ნივთი აღარ იყო": ("ნივთი აღარ", "აღარ არის", "sold out", "გაიყიდა"),
    "გაიწელა": ("გაიწელ", "დაგვიანდ", "ვადა გავიდა"),
    "გადაიფიქრა": ("გადავიფიქრ", "აღარ მინდა"),
    "ფასი": ("ძვირი", "ფასი მაღალ", "იაფად"),
}

QUESTION_MARKS = ("?", "თუ ", "რამდენ", "როდის", "რა ღირს", "როგორ", "სად ")


def find_phones(text: str) -> list[str]:
    """Return normalized 9-digit Georgian mobile numbers found in text."""
    return sorted({re.sub(r"\D", "", m) for m in PHONE_RE.findall(text)})


def find_sizes(text: str) -> list[str]:
    out: set[str] = set()
    for letter, numeric in SIZE_RE.findall(text):
        if letter:
            out.add(letter.upper())
        elif numeric:
            out.add(numeric)
    return sorted(out)


def stage_hits(text: str) -> dict[str, int]:
    """Count lifecycle keyword hits per stage."""
    low = text.lower()
    hits: dict[str, int] = {}
    for stage, stems in STAGE_KEYWORDS.items():
        n = sum(low.count(stem) for stem in stems)
        if n:
            hits[stage] = n
    return hits


def cancel_reason(text: str) -> str | None:
    low = text.lower()
    for reason, stems in CANCEL_REASONS.items():
        if any(stem in low for stem in stems):
            return reason
    return None


def is_question(text: str) -> bool:
    low = text.lower().strip()
    return any(mark in low for mark in QUESTION_MARKS)


def looks_like_order(text: str) -> bool:
    """A thread that shows at least two distinct lifecycle stages is a real sale."""
    return len(stage_hits(text)) >= 2
