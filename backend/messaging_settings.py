"""Optional transport settings. Private configuration is never returned to the UI."""
import json
import os
from pathlib import Path
import re
from urllib.parse import urlparse

PROVIDERS = {'imessage', 'twilio-sms', 'twilio-whatsapp', 'openclaw'}
PHONE = re.compile(r'^\+[1-9][0-9]{7,14}$')


def provider():
    value = os.environ.get('FAMILY_MESSAGING_PROVIDER', 'imessage')
    if value not in PROVIDERS:
        raise ValueError('Unsupported FAMILY_MESSAGING_PROVIDER')
    return value


def load_settings(path=None):
    selected = provider()
    if selected == 'imessage':
        return {'provider': selected}
    path = Path(path or os.environ.get('FAMILY_MESSAGING_CONFIG', '/app/config/messaging.json'))
    try:
        config = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        raise ValueError('Create a valid private config/messaging.json from the matching example') from None
    if not isinstance(config, dict) or config.get('provider') != selected:
        raise ValueError('Messaging config provider must match FAMILY_MESSAGING_PROVIDER')
    token = config.get('bridge_token', '')
    if not isinstance(token, str) or len(token) < 32 or token.startswith('REPLACE'):
        raise ValueError('Set a random bridge_token of at least 32 characters')
    recipients = config.get('opted_in_recipients')
    if not isinstance(recipients, list) or not recipients or any(not isinstance(n, str) or not PHONE.fullmatch(n) for n in recipients):
        raise ValueError('List opted_in_recipients as full E.164 phone numbers')
    sender = config.get('sender_number', '')
    if not isinstance(sender, str) or not PHONE.fullmatch(sender) or sender in recipients:
        raise ValueError('Set a separate sender_number in E.164 format')
    if selected.startswith('twilio-'):
        if not re.fullmatch(r'AC[0-9a-fA-F]{32}', str(config.get('account_sid', ''))):
            raise ValueError('Set the Twilio account_sid')
        if not re.fullmatch(r'[0-9a-fA-F]{32}', str(config.get('auth_token', ''))):
            raise ValueError('Set the Twilio auth_token')
        url = urlparse(config.get('webhook_url', ''))
        if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment or url.path != '/webhooks/twilio':
            raise ValueError('Set the exact public HTTPS webhook_url ending /webhooks/twilio without query parameters')
        if selected == 'twilio-whatsapp':
            if not re.fullmatch(r'HX[0-9a-fA-F]{32}', str(config.get('content_sid', ''))):
                raise ValueError('Scheduled WhatsApp alerts require an approved Twilio content_sid')
            variables = config.get('content_variables', {})
            if not isinstance(variables, dict) or any(not re.fullmatch(r'[1-9][0-9]*', k) or not isinstance(v, str) for k, v in variables.items()):
                raise ValueError('content_variables must map numeric template slots to strings')
    elif not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', str(config.get('openclaw_account', ''))):
        raise ValueError('Set the dedicated openclaw_account identifier')
    return config


def allowed_number(config, number):
    return isinstance(number, str) and bool(PHONE.fullmatch(number)) and number in config['opted_in_recipients']


if __name__ == '__main__':
    import sys
    try:
        config = load_settings()
        print('Messaging configuration valid for ' + config['provider'] + '. No credentials or phone numbers displayed.')
    except ValueError as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
