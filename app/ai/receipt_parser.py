import json
import os
import re
from datetime import datetime
from decimal import Decimal
from typing import Dict, Optional

CATEGORY_KEYWORDS = {
    "food": {"grocery", "supermarket", "market", "food", "restaurant", "cafe"},
    "transport": {"train", "bus", "taxi", "transport", "uber", "lyft", "gas"},
    "utilities": {"electric", "water", "gas", "utility", "internet"},
    "shopping": {"store", "mall", "clothes", "electronics", "shop"},
    "entertainment": {"movie", "cinema", "game", "concert"},
    "health": {"pharmacy", "clinic", "hospital", "drug"},
    "other": set(),
}

DATE_PATTERNS = [
    r"(20\d{2})[-/](\d{1,2})[-/](\d{1,2})",
    r"(\d{1,2})[-/](\d{1,2})[-/](20\d{2})",
]

AMOUNT_PATTERN = r"([0-9]+[\.,][0-9]{2})|¥?([0-9]{3,})"


def _normalize_text_from_file(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read()
    except UnicodeDecodeError:
        pass
    except FileNotFoundError:
        return ""

    try:
        with open(path, "rb") as handle:
            data = handle.read()
        return data.decode("utf-8", errors="ignore")
    except Exception:
        return ""


def _infer_category(store: str, text: str) -> str:
    combined = f"{store} {text}".lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if not keywords:
            continue
        if any(keyword in combined for keyword in keywords):
            return category
    return "other"


def _parse_amount(text: str) -> Optional[Decimal]:
    for match in re.finditer(AMOUNT_PATTERN, text):
        groups = [group for group in match.groups() if group]
        if not groups:
            continue
        value = groups[0]
        value = value.replace("¥", "").replace(",", "").strip()
        try:
            return Decimal(value)
        except Exception:
            continue
    return None


def _parse_date(text: str) -> Optional[datetime]:
    for pattern in DATE_PATTERNS:
        match = re.search(pattern, text)
        if not match:
            continue
        parts = [int(p) for p in match.groups()]
        if len(parts) == 3:
            if parts[0] > 1900:
                year, month, day = parts
            else:
                month, day, year = parts
            try:
                return datetime(year, month, day)
            except ValueError:
                continue
    return None


def parse_receipt(path: str) -> Dict[str, Optional[str]]:
    """Parse a receipt file and return structured information.

    The parser is intentionally lightweight so that it can run without
    native OCR libraries. It attempts to interpret UTF-8 text receipts or
    filenames. For image-based receipts, we derive hints from the
    filename. The result is a dictionary containing best-effort guesses.
    """

    text = _normalize_text_from_file(path)
    basename = os.path.basename(path)
    if not text:
        text = basename

    store = None
    store_candidates = re.findall(r"[A-Za-z0-9&'\- ]{3,50}", text)
    if store_candidates:
        store = store_candidates[0].strip()

    amount = _parse_amount(text)
    date_value = _parse_date(text)

    category = _infer_category(store or "", text)

    items_matches = re.findall(r"\n(.+?)\s+[0-9]+[\.,][0-9]{2}", text)
    items = ", ".join({match.strip() for match in items_matches}) if items_matches else None

    return {
        "store_name": store or os.path.splitext(basename)[0],
        "amount": str(amount) if amount is not None else None,
        "purchase_date": date_value.strftime("%Y-%m-%d") if date_value else None,
        "category": category,
        "items": items,
        "raw_text": text,
        "ai_summary": json.dumps(
            {
                "source": "heuristic-parser",
                "filename": basename,
                "has_text": bool(text),
                "matched_items": items_matches[:10],
            }
        ),
    }
