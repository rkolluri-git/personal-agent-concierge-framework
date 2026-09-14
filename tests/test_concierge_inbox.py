from concierge_inbox import handles_match, strip_agent_prefix


def test_accepts_explicit_fa_prefix_variants():
    assert strip_agent_prefix("FA schedule an appointment") == "schedule an appointment"
    assert strip_agent_prefix(" fa: remind me at seven ") == "remind me at seven"
    assert strip_agent_prefix("FA- notify parents") == "notify parents"
    assert strip_agent_prefix("FA, add milk to my tasks") == "add milk to my tasks"


def test_ignores_personal_replies_and_incomplete_prefixes():
    assert strip_agent_prefix("Sounds good, thank you") is None
    assert strip_agent_prefix("Family appointment tomorrow") is None
    assert strip_agent_prefix("FA") is None
    assert strip_agent_prefix("FAMILY: do this") is None


def test_matches_saved_emails_without_case_sensitivity():
    assert handles_match("Family.Member@example.com", "family.member@EXAMPLE.com")
    assert handles_match("Family.Member@example.com", "mailto:family.member@example.com")
    assert not handles_match("one@example.com", "two@example.com")


def test_matches_us_phone_numbers_with_optional_country_code():
    assert handles_match("+1 (770) 555-1212", "7705551212")
    assert handles_match("+1 (770) 555-1212", "tel:+17705551212")
    assert not handles_match("+1 (770) 555-1212", "+1 (404) 555-1212")
    assert not handles_match("5551212", "5551212")


def test_does_not_match_different_international_country_codes():
    assert not handles_match("+91 7705551212", "+1 7705551212")
    assert handles_match("+44 20 7946 0123", "tel:+442079460123")


def test_rejects_agent_echoes_and_accepts_trailing_reply_marker():
    from concierge_dialog import reply_message
    for heading in ('FA request #12: ', 'Family Agent request #12: '):
        assert strip_agent_prefix(heading+'Is this a task? Reply FA #12 followed by your answer.') is None
    generated=reply_message(12,{'dialog_state':'awaiting_details','reply_text':'What date is it?'})
    assert strip_agent_prefix(generated) is None
    assert strip_agent_prefix('This is a calendar activity. FA #10')=='#10 This is a calendar activity.'
    assert strip_agent_prefix('FA #10 Parent One will drive')=='#10 Parent One will drive'
    assert strip_agent_prefix('Parent One will drive') is None
