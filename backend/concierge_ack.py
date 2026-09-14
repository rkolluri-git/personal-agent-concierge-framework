"""Recognize standalone connectivity checks without swallowing real requests."""
import re


def is_ack_test(text):
    text = re.sub(r'^\s*FA(?:\s*[:,-]\s*|\s+)', '', text, flags=re.I)
    text = re.sub(r'[.!?,;—–-]+', ' ', text.lower())
    text = ' '.join(text.split())
    return bool(re.fullmatch(
        r'(?:ping|test|test message|ack|'
        r'(?:test(?: message)? )?(?:please )?(?:send|reply(?: with)?) (?:an? )?ack(?:nowledg(?:e)?ment)?(?: if received)?|'
        r'(?:please )?confirm (?:receipt|you received (?:this|this message))|'
        r'did you (?:get|receive) (?:this|this message))', text))


def ack_plan():
    return dict(request_type='acknowledgment', title='Message receipt test',
                missing_fields=[], notification_members=[], proposed_actions=[],
                dialog_state='ready_for_review', question_field=None,
                reply_text='ACK—received.', workflow_version=1,
                workflow_steps=['recognize_receipt_test', 'acknowledge_receipt'],
                interpreter_this_turn='local_fallback', llm_used=False)
