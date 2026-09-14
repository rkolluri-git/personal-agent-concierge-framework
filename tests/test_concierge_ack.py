from datetime import datetime
from unittest.mock import patch
import pytest
from concierge_ack import is_ack_test
from concierge_chain import run_request
from concierge_dialog import finish, reply_message

@pytest.mark.parametrize('text', ['FA test send ACK if received','test send ACK if received','FA ping','FA: test message','Please confirm receipt','reply with ACK','test'])
def test_receipt_checks(text):
    assert is_ack_test(text)
    with patch('concierge_chain.preview_request', side_effect=AssertionError('Must bypass LLM')):
        plan = run_request(text, [], datetime(2026, 9, 14))
    assert finish(plan)['reply_text'] == 'ACK—received.'
    assert not plan['missing_fields']
    assert 'Reply FA' not in reply_message(22, plan)

@pytest.mark.parametrize('text', ['Child One has a test tomorrow at 4pm','Schedule a test appointment','Test send ACK if received and remind Parent One at 4pm','Find rock concerts','test results due Monday'])
def test_real_requests_are_not_swallowed(text):
    assert not is_ack_test(text)
