"""Cross-platform alert delivery. No sends occur during --check."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from urllib.request import Request, urlopen

from messaging_settings import allowed_number, load_settings


def api(config, path, payload=None):
    base = os.environ.get('FAMILY_API_URL', 'http://127.0.0.1:8000').rstrip('/')
    request = Request(base + path, data=json.dumps(payload or {}).encode(), headers={
        'Content-Type': 'application/json', 'Authorization': 'Bearer ' + config['bridge_token']})
    with urlopen(request, timeout=60) as response:
        return json.load(response)


def deliver(config, alert):
    number = alert['imessage_handle']  # Legacy storage/API name; remote transports require E.164.
    if not allowed_number(config, number):
        return 'failed'
    if config['provider'] == 'openclaw':
        executable = shutil.which('openclaw')
        if not executable:
            return 'failed'
        try:
            # Run alongside OpenClaw in WSL/Linux/macOS; never interpolate a shell command.
            result = subprocess.run([executable, 'message', 'send', '--channel', 'whatsapp',
                                     '--account', config['openclaw_account'], '--target', number,
                                     '--message', alert['message'], '--json'],
                                    capture_output=True, timeout=45, check=False)
            # A nonzero result can follow a partial send. Never retry it automatically.
            return 'sent' if result.returncode == 0 else 'uncertain'
        except (OSError, subprocess.TimeoutExpired):
            return 'uncertain'
    from twilio.base.exceptions import TwilioRestException
    from twilio.http.http_client import TwilioHttpClient
    from twilio.rest import Client
    client = Client(config['account_sid'], config['auth_token'],
                    http_client=TwilioHttpClient(timeout=20, max_retries=0))
    values = {'to': number, 'from_': config['sender_number']}
    if config['provider'] == 'twilio-whatsapp':
        values.update(to='whatsapp:' + number, from_='whatsapp:' + config['sender_number'],
                      content_sid=config['content_sid'])
        variables = {key: value.replace('{message}', alert['message']).replace('{member_name}', alert['member_name'])
                     for key, value in config.get('content_variables', {}).items()}
        if variables:
            values['content_variables'] = json.dumps(variables)
    else:
        values['body'] = alert['message']
    try:
        result = client.messages.create(**values)
        if result.status in {'failed', 'undelivered', 'canceled'}:
            return 'failed'
        return 'sent' if result.sid else 'uncertain'
    except TwilioRestException as error:
        return 'failed' if 400 <= error.status < 500 else 'uncertain'
    except Exception:
        # An interrupted request may already have been accepted. Do not duplicate it.
        return 'uncertain'


def run_once(config):
    for path in ['/alerts/calendar/sync', '/alerts/morning/sync']:
        try:
            api(config, path)
        except Exception:
            print('A scheduled sync is unavailable; existing alerts will still be checked.', flush=True)
    for _ in range(100):
        alert = api(config, '/alerts/claim?provider=' + config['provider'])
        if alert is None:
            return
        outcome = deliver(config, alert)
        # If completion fails, stop: the server will mark the abandoned claim uncertain.
        api(config, '/alerts/{}/{}'.format(alert['id'], outcome))
        print('Alert {}: {} (sent means provider accepted, not recipient delivery).'.format(alert['id'], outcome), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    if 'FAMILY_MESSAGING_CONFIG' not in os.environ and not Path('/app/config').exists():
        os.environ['FAMILY_MESSAGING_CONFIG'] = str(Path(__file__).resolve().parents[1] / 'config/messaging.json')
    config = load_settings()
    if config['provider'] == 'imessage':
        raise ValueError('Choose an optional messaging provider before starting this worker')
    if config['provider'] == 'openclaw':
        if not shutil.which('openclaw'):
            raise ValueError('Install OpenClaw in this WSL/Linux/macOS environment and link the dedicated account')
    else:
        from twilio.rest import Client  # Dependency check only; does not contact Twilio.
    if args.check:
        print('Messaging configuration and local dependencies passed. Account activation and delivery are not tested.')
        return
    while True:
        try:
            run_once(config)
        except Exception:
            print('Messaging cycle could not complete; check API and provider setup. Private details omitted.', flush=True)
            if args.once:
                raise SystemExit(1)
        if args.once:
            return
        time.sleep(30)
        config = load_settings()  # Pick up recipient opt-out/configuration changes.


if __name__ == '__main__':
    try:
        main()
    except ValueError as error:
        raise SystemExit(str(error)) from None
