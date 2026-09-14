"""Read only the scoped local worker credential created by API startup."""
from pathlib import Path


def worker_headers():
    path = Path(__file__).resolve().parents[1] / 'config/worker-auth.key'
    return {'Authorization': 'Bearer ' + path.read_text(encoding='ascii').strip()}
