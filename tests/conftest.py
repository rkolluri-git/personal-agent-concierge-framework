"""Unit tests use an in-memory database URL and never open the household database."""
import os
import tempfile
from pathlib import Path
_TEST_HOME = tempfile.TemporaryDirectory(prefix="personal-agent-tests-")
os.environ["CALENDAR_CONFIG_DIR"] = _TEST_HOME.name
os.environ["FAMILY_SECRETS_KEY_PATH"] = str(Path(_TEST_HOME.name) / "family-secrets.key")

os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
# Existing fixtures describe a US household. Regional tests explicitly override settings.
os.environ['FAMILY_LOCALE'] = 'en-US'
os.environ['FAMILY_COUNTRY'] = 'US'
os.environ['FAMILY_TIMEZONE'] = 'America/New_York'
os.environ['FAMILY_UNITS'] = 'imperial'
os.environ['FAMILY_SCHOOL_CALENDAR'] = 'cobb'
os.environ['FAMILY_MESSAGING_PROVIDER'] = 'imessage'

# Always keep optional external providers off unless a test explicitly mocks them.
os.environ['FAMILY_LLM_PROVIDER'] = 'none'
os.environ['OPENAI_API_KEY'] = ''
os.environ['GOOGLE_PLACES_API_KEY'] = ''
import pytest

@pytest.fixture(autouse=True)
def isolated_transports(monkeypatch):
    import socket
    def blocked(*args, **kwargs):
        raise RuntimeError('Unmocked network access is forbidden in offline tests')
    monkeypatch.setattr(socket.socket, 'connect', blocked)
    import events_service
    monkeypatch.setattr(events_service, 'SOURCES', {'Example Venue': 'https://example.com/events'})
