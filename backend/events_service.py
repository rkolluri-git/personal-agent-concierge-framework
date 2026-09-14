"""Public concert discovery. No household information is sent to venues."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from zoneinfo import ZoneInfo
from hashlib import sha256
from html.parser import HTMLParser
from pathlib import Path
from threading import RLock
from urllib.parse import urlparse
import json
import os
import math
import re
import tempfile
import requests
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

router = APIRouter(prefix='/events', tags=['Events'])
from regional_settings import REGIONAL
CONFIG = Path(os.environ.get('CALENDAR_CONFIG_DIR', '/app/config'))
STORE = CONFIG / 'concert-discovery.json'
LOCK = RLock()
ZONE = ZoneInfo(REGIONAL.timezone)

def load_sources():
    path = CONFIG / 'event-sources.json'
    if not path.exists():
        return {}, 'USD'
    settings = json.loads(path.read_text())
    sources = settings.get('sources', {})
    currency = settings.get('currency', 'USD')
    if not isinstance(sources, dict) or len(sources) > 20:
        raise ValueError('Configure at most 20 event sources')
    if not isinstance(currency, str) or not re.fullmatch(r'[A-Z]{3}', currency):
        raise ValueError('Event currency must be a three-letter code')
    for name, url in sources.items():
        if not isinstance(name, str) or not name.strip() or not isinstance(url, str):
            raise ValueError('Event sources require a name and HTTPS URL')
        parsed = urlparse(url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('Event sources require an HTTPS URL without credentials')
    return sources, currency

SOURCES, CURRENCY = load_sources()

class StructuredData(HTMLParser):
    def __init__(self):
        super().__init__(); self.active = False; self.buffer = []; self.items = []
    def handle_starttag(self, tag, attrs):
        if tag == 'script' and dict(attrs).get('type') == 'application/ld+json':
            self.active = True; self.buffer = []
    def handle_data(self, data):
        if self.active: self.buffer.append(data)
    def handle_endtag(self, tag):
        if tag == 'script' and self.active:
            try: self.items.append(json.loads(''.join(self.buffer)))
            except (ValueError, TypeError): pass
            self.active = False

def objects(value):
    if isinstance(value, list):
        for child in value: yield from objects(child)
    elif isinstance(value, dict):
        yield value
        for key in ('@graph', 'itemListElement', 'item'):
            if key in value: yield from objects(value[key])

def safe_url(value):
    if not isinstance(value, str): return None
    parsed = urlparse(value)
    return value if parsed.scheme == 'https' and parsed.hostname and not parsed.username else None

def venue_details(html):
    # Read embedded public page data as JSON, never execute website scripts.
    details = {}
    for match in re.finditer(r'self\.__next_f\.push\((.*?)\)</script>', html, re.S):
        try:
            chunk = json.loads(match[1])
            text = chunk[1] if len(chunk) > 1 else ''
            if not isinstance(text, str): continue
            for marker in re.finditer(r'"events":', text):
                values, _ = json.JSONDecoder().raw_decode(text[marker.end():].lstrip())
                if isinstance(values, list):
                    for event in values:
                        if isinstance(event, dict) and event.get('url'): details[event['url']] = event
        except (ValueError, TypeError, IndexError): continue
    return details

def parse_events(html, source):
    parser = StructuredData(); parser.feed(html)
    rows = []
    details = venue_details(html)
    for item in objects(parser.items):
        kind = item.get('@type', [])
        if isinstance(kind, str): kind = [kind]
        if 'MusicEvent' not in kind: continue
        try:
            raw = item['startDate']
            date = datetime.fromisoformat(raw.replace('Z', '+00:00'))
            if date.tzinfo is None: date = date.replace(tzinfo=ZONE)
            date = date.astimezone(ZONE)
            title = str(item['name']).strip()[:300]
            detail = details.get(item.get('url'), {})
            if detail.get('segment') and detail['segment'] != 'Music': continue
            if any(word in title.lower() for word in ('season tickets', 'not a concert ticket')): continue
            location = item.get('location') or {}
            venue = str(location.get('name') or source)[:200]
            address = location.get('address') or {}
            if isinstance(address, dict):
                address = ', '.join(str(address[k]) for k in ('streetAddress', 'addressLocality', 'addressRegion') if address.get(k))
            url = safe_url(item.get('url')) or SOURCES[source]
            offers = item.get('offers') or []
            if isinstance(offers, dict): offers = [offers]
            price = next((f"{o.get('priceCurrency', 'Unknown currency')} {o.get('price', o.get('lowPrice'))}" for o in offers if isinstance(o, dict) and (o.get('price') is not None or o.get('lowPrice') is not None)), None)
            status = str(detail.get('status_code') or item.get('eventStatus', 'Status not listed')).rsplit('/', 1)[-1].replace('Event', '').capitalize()
            info = str(detail.get('important_info') or '')
            age = str(item.get('typicalAgeRange') or 'Not listed')
            if re.search(r'\ball ages\b', info, re.I): age = 'All ages'
            else:
                restriction = re.search(r'\b(18|21)\s*\+', info)
                if restriction: age = restriction[1] + '+'
            identity = sha256(f'{title.casefold()}|{venue.casefold()}|{date.isoformat()}'.encode()).hexdigest()[:24]
            rows.append(dict(id=identity, title=title, start=date.isoformat(), time_known='T' in raw,
                venue=venue, address=str(address)[:400], url=url, source=source, source_url=SOURCES[source],
                status=status, price=price, genre=str(detail.get('genre') or item.get('genre') or 'Not listed')[:100],
                age_restriction=age[:100]))
        except (KeyError, ValueError, TypeError, AttributeError): continue
    return rows

def fetch_source(source):
    try:
        with requests.get(SOURCES[source], timeout=(5, 15), stream=True) as response:
            response.raise_for_status()
            chunks = []; size = 0
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > 3_000_000: raise ValueError('Page too large')
                chunks.append(chunk)
        rows = parse_events(b''.join(chunks).decode('utf-8', errors='replace'), source)
        # Empty structured data may mean a website redesign, not zero concerts.
        return source, rows, 'ok' if rows else 'unavailable'
    except (requests.RequestException, ValueError): return source, [], 'unavailable'

def read_store():
    try: return json.loads(STORE.read_text())
    except (FileNotFoundError, ValueError): return {'sources': {}, 'shortlist': []}

def write_store(data):
    STORE.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=STORE.parent)
    try:
        with os.fdopen(fd, 'w') as f: json.dump(data, f)
        os.replace(name, STORE)
    finally:
        if os.path.exists(name): os.unlink(name)

def response_data(data):
    today = datetime.now(ZONE).date(); rows = {}; statuses = []
    saved_ids = set(data.get('shortlist', []))
    for source in SOURCES:
        result = data['sources'].get(source, {})
        statuses.append(dict(name=source, url=SOURCES[source], status=result.get('status', 'not_checked'), checked_at=result.get('checked_at')))
        for row in result.get('events', []):
            day = datetime.fromisoformat(row['start']).date()
            if today <= day <= today.replace(month=12, day=31):
                rows[row['id']] = dict(row, shortlisted=row['id'] in saved_ids, stale=result.get('status') != 'ok')
    prefs = EventPreferences(**data.get('preferences', {})).model_dump()
    for row in rows.values(): row['matches_preferences'] = preference_match(row, prefs)
    return dict(events=sorted(rows.values(), key=lambda r: r['start']), sources=statuses, year=today.year, timezone=str(ZONE), currency=CURRENCY, preferences=prefs)

@router.get('/concerts')
def concerts():
    with LOCK: return response_data(read_store())

@router.post('/concerts/refresh')
def refresh():
    with LOCK:
        data = read_store(); now = datetime.now(ZONE)
        if data.get('last_refresh') and (now-datetime.fromisoformat(data['last_refresh'])).total_seconds() < 60:
            return response_data(data)
        with ThreadPoolExecutor(max_workers=3) as pool:
            for source, rows, status in pool.map(fetch_source, SOURCES):
                previous = data['sources'].get(source, {})
                data['sources'][source] = dict(status=status, checked_at=now.isoformat(), events=rows if status == 'ok' else previous.get('events', []))
        data['last_refresh'] = now.isoformat(); write_store(data)
        return response_data(data)

class ShortlistUpdate(BaseModel):
    shortlisted: bool

@router.put('/concerts/{event_id}/shortlist')
def shortlist(event_id: str, payload: ShortlistUpdate):
    with LOCK:
        data = read_store()
        if not any(e['id'] == event_id for s in data['sources'].values() for e in s.get('events', [])):
            raise HTTPException(404, 'Concert not found. Refresh events.')
        ids = set(data.get('shortlist', []))
        if payload.shortlisted: ids.add(event_id)
        else: ids.discard(event_id)
        data['shortlist'] = sorted(ids); write_store(data)
        return {'shortlisted': payload.shortlisted}

class EventPreferences(BaseModel):
    enabled: bool = False
    artists: list[str] = []
    genres: list[str] = []
    max_ticket_price: float | None = None
    include_unknown_prices: bool = True
    all_ages_only: bool = False

    @field_validator('artists', 'genres')
    @classmethod
    def clean_choices(cls, values):
        if len(values) > 30: raise ValueError('Choose up to 30 artists or genres')
        result = []
        for value in values:
            value = value.strip()
            if len(value) > 100: raise ValueError('Keep each name under 100 characters')
            if value and value.casefold() not in [v.casefold() for v in result]: result.append(value)
        return result

    @field_validator('max_ticket_price')
    @classmethod
    def valid_price(cls, value):
        if value is not None and (not math.isfinite(value) or not 0 <= value <= 10000):
            raise ValueError('Enter a budget from 0 to 10000 dollars')
        return value


def preference_match(row, prefs, music=True):
    if not prefs.get('enabled'): return True
    if music and (prefs.get('artists') or prefs.get('genres')):
        artist = any(a.casefold() in row['title'].casefold() for a in prefs.get('artists', []))
        genre = any(g.casefold() in row.get('genre', '').casefold() for g in prefs.get('genres', []))
        if not (artist or genre): return False
    if prefs.get('all_ages_only') and row.get('age_restriction') != 'All ages': return False
    budget = prefs.get('max_ticket_price')
    if budget is not None:
        price = re.fullmatch(re.escape(CURRENCY) + r'\s+(\d+(?:\.\d+)?)', row.get('price') or '')
        if price:
            if float(price[1]) > budget: return False
        elif not prefs.get('include_unknown_prices', True): return False
    return True


@router.get('/preferences')
def event_preferences():
    with LOCK: return EventPreferences(**read_store().get('preferences', {})).model_dump()


@router.put('/preferences')
def save_event_preferences(payload: EventPreferences):
    with LOCK:
        data = read_store(); data['preferences'] = payload.model_dump(); write_store(data)
        return data['preferences']
