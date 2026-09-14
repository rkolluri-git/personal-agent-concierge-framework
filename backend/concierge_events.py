"""Read-only concert discovery intent and search, shared by chat and previews."""
import calendar
import re
from events_service import refresh, preference_match


def is_events_search(text):
    return bool(re.search(r'\b(?:find|search|look for|discover|show|what|any|which)\b', text, re.I)
                and re.search(r'\b(?:concerts?|bands?|gigs|music events)\b', text, re.I)
                and not re.search(r'\b(?:book|schedule|add to|remind)\b', text, re.I))


def search_plan(text, now):
    month = next((i for i in range(1, 13) if re.search(rf'\b(?:{calendar.month_name[i]}|{calendar.month_abbr[i]})\b', text, re.I)), None)
    year_match = re.search(r'\b20\d{2}\b', text)
    year = int(year_match[0]) if year_match else now.year
    query = re.sub(r'\b(?:matching (?:my|our) preferences|(?:my|our|family) favorites|using (?:my|our) preferences)\b', ' ', text.lower())
    query = re.sub(r'\b(?:rest of (?:the )?year|this year|near me|look for|music events)\b', ' ', query)
    for i in range(1, 13):
        query = re.sub(rf'\b(?:{calendar.month_name[i]}|{calendar.month_abbr[i]})\b', ' ', query, flags=re.I)
    query = re.sub(r'\b(?:fa|find|search|discover|show|me|us|what|which|any|are|there|upcoming|concerts?|bands?|gigs|in|for|by|the|a|at|this|please|20\d{2})\b', ' ', query)
    terms = re.findall(r'[\w]+', query)
    plan = dict(request_type='events', title='Concert search', missing_fields=[],
                dialog_state='ready_for_review', question_field=None, notification_members=[],
                proposed_actions=['Review matching concerts and shortlist favorites in Events'],
                workflow_version=1, workflow_steps=['recognize_events_search', 'refresh_venue_listings', 'filter_concerts', 'show_results'],
                interpreter_this_turn='local_fallback', llm_used=False, search_month=month, search_query=' '.join(terms), search_year=year)
    if year != now.year:
        plan.update(event_results=[], reply_text=f'Events currently covers configured venues through December {now.year}. Please search within that year.')
        return plan
    data = refresh()
    rows = [row for row in data['events'] if (not month or int(row['start'][5:7]) == month)
            and all(term in f"{row['title']} {row['genre']} {row['venue']}".lower() for term in terms)]
    prefs = data.get('preferences', {})
    rows = [r for r in rows if preference_match(r, prefs, music=not bool(terms))]
    count = len(rows)
    summary = '; '.join(f"{r['title'][:65]} ({r['start'][5:10]})" for r in rows[:3])
    partial = any(s['status'] != 'ok' for s in data['sources'])
    reply = f'Found {count} matching listings at our configured venues.'
    if prefs.get('enabled'): reply += ' Saved budget/age filters applied' + ('; favorite artists or genres applied.' if not terms else '.')
    if summary: reply += ' ' + summary + '.'
    if partial: reply += ' Some sources could not refresh; listings may be outdated.'
    if not count: reply += ' Try another artist, genre or month; coverage is limited to selected venues.'
    reply += ' Open Events in the dashboard to shortlist. Nothing booked.'
    plan.update(event_results=rows, event_sources=data['sources'], reply_text=reply, result_count=count)
    return plan
