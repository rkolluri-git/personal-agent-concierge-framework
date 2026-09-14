"""Rules for separating Family Agent iMessages from personal replies."""
import re
from regional_settings import REGIONAL


PREFIX = re.compile(r"^\s*FA(?:\s*[:,-]\s*|\s+)(?P<request>\S(?:.|\n)*)$", re.IGNORECASE)


def strip_agent_prefix(text: str) -> str | None:
    if re.match(r"^\s*(?:FA|Family Agent)\s+request\s*#\d+\s*:", text, re.I):
        return None
    suffix = re.fullmatch(r"(.+?)\s+FA\s+#(\d+)\s*", text, re.I | re.S)
    if suffix:
        return f"#{suffix.group(2)} {suffix.group(1).strip()}"
    match = PREFIX.match(text)
    return match.group("request").strip() if match else None


def handles_match(first: str | None, second: str | None) -> bool:
    if not first or not second:
        return False
    left, right = first.strip().casefold(), second.strip().casefold()
    for prefix in ("mailto:", "tel:"):
        if left.startswith(prefix):
            left = left.removeprefix(prefix)
        if right.startswith(prefix):
            right = right.removeprefix(prefix)
    if "@" in left or "@" in right:
        return left == right
    left_digits = "".join(character for character in left if character.isdigit())
    right_digits = "".join(character for character in right if character.isdigit())
    # Never collapse international country codes into a shared ten-digit suffix.
    if REGIONAL.country == "US":
        if len(left_digits) == 11 and left_digits.startswith("1"):
            left_digits = left_digits[1:]
        if len(right_digits) == 11 and right_digits.startswith("1"):
            right_digits = right_digits[1:]
    return len(left_digits) >= 8 and left_digits == right_digits
