"""Cobb County school-day calendar with a private weekly local cache."""
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
import json
import os
from pathlib import Path
import re
from regional_settings import REGIONAL
from urllib.request import Request, urlopen

CONFIG = Path(os.environ.get("CALENDAR_CONFIG_DIR", "/app/config"))
CACHE_PATH = CONFIG / "cobb-school-calendar.json"
SOURCE_URL = "https://media.cobbk12.org/media/WWWCobb/medialib/2026-2027-staff-use-calendar.6d50b7128535.pdf"
MONTHS = {
    name: number for number, name in enumerate(
        ("JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE", "JULY", "AUGUST", "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER"),
        1,
    )
}
NO_COMMUTE_TERMS = (
    "SCHOOLS CLOSED", "STUDENT/TEACHER HOLIDAYS", "STUDENT HOLIDAY", "DIGITAL LEARNING DAY",
)


def school_year_for(day: date) -> str:
    start = day.year if day.month >= 7 else day.year - 1
    return f"{start}-{start + 1}"


def parse_school_calendar_text(text: str, school_year: str) -> dict:
    start_year, end_year = (int(value) for value in school_year.split("-"))
    month = None
    first_day = last_day = None
    excluded = set()
    for raw in text.splitlines():
        line = " ".join(raw.upper().replace("–", "-").split())
        if line in MONTHS:
            month = MONTHS[line]
            continue
        if month is None:
            continue
        match = re.match(r"^(\d{1,2})(?:\*+)?(?:\s*-\s*(\d{1,2})(?:\*+)?)?\b", line)
        if not match:
            continue
        year = start_year if month >= 7 else end_year
        first, last = int(match.group(1)), int(match.group(2) or match.group(1))
        if "FIRST DAY OF SCHOOL" in line:
            first_day = date(year, month, first)
        if "LAST DAY OF SCHOOL" in line:
            last_day = date(year, month, last)
        if any(term in line for term in NO_COMMUTE_TERMS):
            for number in range(first, last + 1):
                excluded.add(date(year, month, number))
    if first_day is None or last_day is None or len(excluded) < 10:
        raise ValueError("The official school calendar format could not be verified")
    return {
        "school_year": school_year,
        "first_day": first_day.isoformat(),
        "last_day": last_day.isoformat(),
        "excluded_dates": sorted(day.isoformat() for day in excluded),
    }


def fetch_school_calendar(school_year: str) -> dict:
    from pypdf import PdfReader

    if school_year != "2026-2027":
        raise ValueError("A verified Cobb County calendar source is not configured for this school year")
    request = Request(SOURCE_URL, headers={"User-Agent": "FamilyAgent/1.0"})
    with urlopen(request, timeout=30) as response:
        document = response.read()
    text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(document)).pages)
    result = parse_school_calendar_text(text, school_year)
    result.update({"source_url": SOURCE_URL, "refreshed_at": datetime.now(timezone.utc).isoformat()})
    CONFIG.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = CACHE_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(CACHE_PATH)
    return result


def read_cached_calendar() -> dict | None:
    try:
        value = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def school_calendar(day: date, refresh: bool = False) -> dict:
    if REGIONAL.school_calendar == "none":
        raise ValueError("School calendar filtering is disabled")
    if REGIONAL.school_calendar == "custom":
        value = json.loads((CONFIG / "school-calendar.json").read_text(encoding="utf-8"))
        first, last = date.fromisoformat(value["first_day"]), date.fromisoformat(value["last_day"])
        if not first <= day <= last:
            raise ValueError("Custom calendar does not cover this date; update its coverage")
        excluded = [date.fromisoformat(item).isoformat() for item in value["excluded_dates"]]
        weekdays = value.get("weekdays", [0, 1, 2, 3, 4])
        if not weekdays or any(type(item) is not int or item not in range(7) for item in weekdays):
            raise ValueError("School weekdays must be integers from 0 (Monday) to 6 (Sunday)")
        return dict(value, excluded_dates=excluded, weekdays=weekdays,
                    school_year=value.get("school_year", f"{first.year}-{last.year}"),
                    source_url=value.get("source_url", ""), refreshed_at=value.get("refreshed_at", ""))
    expected = school_year_for(day)
    cached = read_cached_calendar()
    fresh = False
    if cached and cached.get("school_year") == expected:
        try:
            refreshed = datetime.fromisoformat(cached["refreshed_at"].replace("Z", "+00:00"))
            fresh = datetime.now(timezone.utc) - refreshed < timedelta(days=7)
        except (KeyError, TypeError, ValueError):
            pass
    if refresh or not fresh:
        try:
            return fetch_school_calendar(expected)
        except Exception:
            if cached and cached.get("school_year") == expected:
                return cached
            raise
    return cached


def school_day_status(day: date, refresh: bool = False) -> dict:
    calendar = school_calendar(day, refresh)
    first = date.fromisoformat(calendar["first_day"])
    last = date.fromisoformat(calendar["last_day"])
    excluded = set(calendar["excluded_dates"])
    is_school_day = day.weekday() in calendar.get("weekdays", [0, 1, 2, 3, 4]) and first <= day <= last and day.isoformat() not in excluded
    return {
        "date": day.isoformat(),
        "is_school_day": is_school_day,
        "school_year": calendar["school_year"],
        "first_day": calendar["first_day"],
        "last_day": calendar["last_day"],
        "refreshed_at": calendar["refreshed_at"],
        "source_url": calendar["source_url"],
    }
