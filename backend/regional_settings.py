"""Shared installation settings; storage keeps Fahrenheit and meters for compatibility."""
from dataclasses import dataclass, asdict
import os
import re
from zoneinfo import ZoneInfo

@dataclass(frozen=True)
class RegionalSettings:
    locale: str
    country: str
    timezone: str
    units: str
    school_calendar: str

    @classmethod
    def from_env(cls, env=None):
        env = os.environ if env is None else env
        locale = env.get("FAMILY_LOCALE", "en-US")
        if not re.fullmatch(r"[a-zA-Z]{2,3}(?:-[a-zA-Z]{4})?-[a-zA-Z]{2}", locale):
            raise ValueError("FAMILY_LOCALE must be a language-region tag such as en-IN or en-GB")
        country = env.get("FAMILY_COUNTRY", locale.rsplit("-", 1)[-1]).upper()
        if not re.fullmatch(r"[A-Z]{2}", country):
            raise ValueError("FAMILY_COUNTRY must be a two-letter country code")
        timezone = env.get("FAMILY_TIMEZONE", "America/New_York")
        ZoneInfo(timezone)  # Fail at startup instead of silently scheduling in the wrong zone.
        units = env.get("FAMILY_UNITS", "imperial" if country == "US" else "metric")
        if units not in {"metric", "imperial"}:
            raise ValueError("FAMILY_UNITS must be metric or imperial")
        school = env.get("FAMILY_SCHOOL_CALENDAR", "none")
        if school not in {"none", "custom", "cobb"}:
            raise ValueError("FAMILY_SCHOOL_CALENDAR must be none, custom, or cobb")
        return cls(locale, country, timezone, units, school)

    def public(self):
        return asdict(self)

    def temperature(self, fahrenheit):
        if fahrenheit is None:
            return None
        return round((fahrenheit - 32) * 5 / 9, 1) if self.units == "metric" else fahrenheit

    def distance(self, meters):
        divisor, unit = (1000, "km") if self.units == "metric" else (1609.344, "mi")
        return f"{meters / divisor:.1f} {unit}"

REGIONAL = RegionalSettings.from_env()
