import pytest
from pydantic import ValidationError
import events_service as e


def test_budget_unknown_price_and_age():
    prefs = e.EventPreferences(enabled=True, max_ticket_price=50, include_unknown_prices=False, all_ages_only=True).model_dump()
    row = dict(title='Band', genre='Rock', age_restriction='All ages', price='USD 50')
    assert e.preference_match(row, prefs)
    assert not e.preference_match(dict(row, price='USD 51'), prefs)
    assert not e.preference_match(dict(row, price=None), prefs)
    assert not e.preference_match(dict(row, age_restriction='Not listed'), prefs)
    prefs['include_unknown_prices'] = True
    assert e.preference_match(dict(row, price=None), prefs)


def test_artist_or_genre_and_explicit_override():
    prefs = e.EventPreferences(enabled=True, artists=['Jack White'], genres=['Country']).model_dump()
    assert e.preference_match(dict(title='JACK WHITE LIVE', genre='Rock'), prefs)
    assert e.preference_match(dict(title='Other artist', genre='Country'), prefs)
    assert not e.preference_match(dict(title='Other artist', genre='Metal'), prefs)
    assert e.preference_match(dict(title='Other artist', genre='Metal'), prefs, music=False)


def test_save_preserves_shortlist_and_survives_reload(tmp_path, monkeypatch):
    monkeypatch.setattr(e, 'STORE', tmp_path / 'events.json')
    e.write_store({'sources': {}, 'shortlist': ['keep']})
    e.save_event_preferences(e.EventPreferences(artists=[' Rock ', 'rock'], max_ticket_price=0))
    assert e.event_preferences()['artists'] == ['Rock']
    assert e.event_preferences()['max_ticket_price'] == 0
    assert e.read_store()['shortlist'] == ['keep']
    with pytest.raises(ValidationError): e.EventPreferences(max_ticket_price=float('nan'))
    with pytest.raises(ValidationError): e.EventPreferences(max_ticket_price=-1)
