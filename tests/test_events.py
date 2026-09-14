import json
from datetime import datetime
from unittest.mock import patch
import events_service as e


def listing(**changes):
    item = {'@type': 'MusicEvent', 'name': 'Test Band', 'startDate': '2026-11-14T20:00:00',
            'url': 'https://www.ticketmaster.com/test', 'location': {'name': 'Example Venue'}}
    item.update(changes)
    return '<script type="application/ld+json">' + json.dumps(item) + '</script>'


def test_structured_music_only_and_safe_links():
    rows = e.parse_events(listing(url='javascript:alert(1)'), 'Example Venue')
    assert rows[0]['url'] == e.SOURCES['Example Venue']
    assert rows[0]['start'].endswith('-05:00')
    assert rows[0]['price'] is None
    assert not e.parse_events(listing(**{'@type': 'ComedyEvent'}), 'Example Venue')
    assert not e.parse_events(listing(startDate='not a date'), 'Example Venue')


def test_refresh_failure_preserves_shortlist_and_flags_stale(tmp_path, monkeypatch):
    monkeypatch.setattr(e, 'STORE', tmp_path / 'events.json')
    row = e.parse_events(listing(startDate=f'{datetime.now(e.ZONE).year}-12-30T20:00:00'), 'Example Venue')[0]
    e.write_store({'sources': {'Example Venue': {'events': [row], 'status': 'ok'}}, 'shortlist': [row['id']]})
    with patch.object(e, 'fetch_source', side_effect=lambda s: (s, [], 'unavailable')):
        result = e.refresh()
    assert result['events'][0]['stale']
    assert result['events'][0]['shortlisted']
    e.shortlist(row['id'], e.ShortlistUpdate(shortlisted=False))
    assert not e.concerts()['events'][0]['shortlisted']


def test_year_cutoff_and_duplicates():
    year = datetime.now(e.ZONE).year
    rows = []
    for date in (f'{year}-12-31T20:00:00', f'{year + 1}-01-01T20:00:00', '2020-01-01T20:00:00'):
        rows += e.parse_events(listing(startDate=date), 'Example Venue')
    result = e.response_data({'sources': {'Example Venue': {'events': rows + rows, 'status': 'ok'}}, 'shortlist': []})
    assert len(result['events']) == 1


def test_detailed_source_overrides_mislabelled_music_and_status():
    def page(segment):
        detail = {'events': [{'url': 'https://www.ticketmaster.com/test', 'segment': segment,
                             'genre': 'Rock', 'status_code': 'rescheduled', 'important_info': 'All ages welcome.'}]}
        return listing() + '<script>self.__next_f.push(' + json.dumps([1, json.dumps(detail)]) + ')</script>'
    assert e.parse_events(page('Arts & Theatre'), 'Example Venue') == []
    row = e.parse_events(page('Music'), 'Example Venue')[0]
    assert (row['status'], row['genre'], row['age_restriction']) == ('Rescheduled', 'Rock', 'All ages')
