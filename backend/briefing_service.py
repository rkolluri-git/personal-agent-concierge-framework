"""Deterministic, compact family briefing messages."""
from datetime import date, datetime, timedelta


QUOTES = (
    "Small steps make a strong day.",
    "Bring your best effort and your kindest self.",
    "A good day begins with one thoughtful choice.",
    "Make room today for progress and joy.",
    "Together, ordinary moments become good memories.",
    "Be curious, be helpful, and keep moving forward.",
    "Today is a fresh chance to do something meaningful.",
)


JOKES = (
    "Why did the bicycle fall over? It was two-tired!",
    "What do you call a sleeping dinosaur? A dino-snore!",
    "Why did the cookie visit the doctor? It felt crummy!",
    "What do clouds wear under their clothes? Thunderwear!",
    "What do you call a bear with no teeth? A gummy bear!",
    "How does the ocean say hello? It waves!",
    "Why did the banana go to the doctor? It wasn't peeling well!",
    "What kind of tree fits in your hand? A palm tree!",
    "What do you call cheese that isn't yours? Nacho cheese!",
    "Why did the math book look sad? Too many problems!",
    "What do you call a fish wearing a bow tie? Sofishticated!",
    "Why can't your nose be twelve inches long? It would be a foot!",
    "What do you call a pig that does karate? A pork chop!",
    "How do you organize a space party? You planet!",
)


def joke_for_day(day: date, member_id: int = 0) -> str:
    return JOKES[(day.toordinal() + member_id) % len(JOKES)]


def quote_for_day(day: date, member_id: int = 0) -> str:
    return QUOTES[(day.toordinal() + member_id) % len(QUOTES)]


def delivery_state(local_now: datetime, send_time: str) -> str:
    hour, minute = (int(part) for part in send_time.split(":"))
    scheduled = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if local_now < scheduled:
        return "scheduled"
    return "ready"


def event_is_today(event, day: date, zone) -> bool:
    if event.all_day:
        return date.fromisoformat(event.start) == day
    start = datetime.fromisoformat(event.start.replace("Z", "+00:00"))
    return start.astimezone(zone).date() == day


def event_summary(event, zone) -> str:
    if event.all_day:
        return event.title[:55]
    start = datetime.fromisoformat(event.start.replace("Z", "+00:00")).astimezone(zone)
    return f"{start.strftime('%-I:%M %p')} {event.title[:45]}"


def next_weekend_range(day: date) -> tuple[date, date]:
    """Return the next Saturday and Sunday, excluding the current weekend."""
    days_until_saturday = 5 - day.weekday() if day.weekday() < 5 else 12 - day.weekday()
    saturday = day + timedelta(days=days_until_saturday)
    return saturday, saturday + timedelta(days=1)


def event_local_date(event, zone) -> date:
    if event.all_day:
        return date.fromisoformat(event.start)
    start = datetime.fromisoformat(event.start.replace("Z", "+00:00"))
    return start.astimezone(zone).date()


def weekend_event_summary(event, zone) -> str:
    day = event_local_date(event, zone).strftime("%a")
    return f"{day} {event_summary(event, zone)}"


def build_weekend_schedule(member_name, events, saturday, sunday, zone):
    date_range = f"{saturday.strftime('%b %-d')}–{sunday.strftime('%-d')}"
    activities = "; ".join(weekend_event_summary(event, zone) for event in events[:8])
    sections = [
        f"Hi {member_name} — next weekend ({date_range}):",
        activities or "No family activities are currently scheduled.",
        "Have a wonderful weekend!",
    ]
    message = "\n".join(sections)
    if len(message) <= 500:
        return message
    compact = [sections[0], activities[:390].rstrip("; ") + "…", sections[-1]]
    message = "\n".join(compact)
    return message if len(message) <= 500 else message[:497].rstrip() + "…"


def weather_summary(forecast) -> str:
    days = forecast.get("days") or []
    if not days:
        return ""
    day = days[0]
    low, high = day.get("temperature_min"), day.get("temperature_max")
    temperatures = ""
    if low is not None and high is not None:
        temperatures = f", {round(low)}–{round(high)}{forecast.get('units', {}).get('temperature', '°F')}"
    advice = " ".join(day.get("recommendations") or [])
    return f"Weather: {day.get('condition', 'Mixed conditions')}{temperatures}. {advice}".strip()


def build_briefing(member_id, member_name, events, tasks, forecast, family_view, day, zone):
    activity_label = "Family activities" if family_view else "Your activities"
    activity_text = "; ".join(event_summary(event, zone) for event in events[:5])
    task_text = "; ".join(task.title[:55] for task in tasks[:5])
    sections = [
        f"Good morning {member_name}!",
        f"{activity_label}: {activity_text or 'None scheduled today.'}",
        f"Your tasks: {task_text or 'None due today.'}",
    ]
    weather = weather_summary(forecast)
    if weather:
        sections.append(weather)
    footer = f"Today’s thought: “{quote_for_day(day, member_id)}”\nA little smile: {joke_for_day(day, member_id)}"
    message = "\n".join([*sections, footer])
    if len(message) <= 500:
        return message
    # Reserve room for both complete closing lines; compact the summary, not the joke.
    greeting = sections[0]
    if len(greeting) > 80:
        greeting = greeting[:79].rstrip() + "…"
    details = sections[1:]
    available = 500 - len(footer) - len(greeting) - len(details) - 1
    limits = [0] * len(details)
    while available > 0:
        expanded = False
        for index, detail in enumerate(details):
            if available and limits[index] < len(detail):
                limits[index] += 1
                available -= 1
                expanded = True
        if not expanded:
            break
    compact = [detail if len(detail) <= limit else detail[:limit-1].rstrip() + "…"
               for detail, limit in zip(details, limits)]
    return "\n".join([greeting, *compact, footer])
