from register.normalize import make_match_key, normalize_name


def test_strips_trailing_whitespace_and_limited_suffix():
    result = normalize_name("COST CUTTER RUGBY LIMITED    ")
    assert result.legal_name == "COST CUTTER RUGBY LIMITED"
    assert result.trading_name is None
    assert result.match_key == "COST CUTTER RUGBY"


def test_splits_trading_as_lowercase_slash_form():
    result = normalize_name("HAH Hospitality Limited t/a Indian Affair Ancoats")
    assert result.legal_name == "HAH Hospitality Limited"
    assert result.trading_name == "Indian Affair Ancoats"
    assert result.match_key == "HAH HOSPITALITY"


def test_splits_trading_as_mixed_case_slash_form():
    result = normalize_name("CASA BAMBOO LTD T/a Pho Le Vietnamese Restaurant")
    assert result.trading_name == "Pho Le Vietnamese Restaurant"
    assert result.match_key == "CASA BAMBOO"


def test_splits_trading_as_full_word_form():
    result = normalize_name("Eleven Hillrise Investments Ltd T/A Chez Lindsay")
    assert result.legal_name == "Eleven Hillrise Investments Ltd"
    assert result.trading_name == "Chez Lindsay"
    assert result.match_key == "ELEVEN HILLRISE INVESTMENTS"


def test_does_not_mangle_unlimited_as_limited_substring():
    result = normalize_name("Northern Rock Unlimited")
    assert result.match_key == "NORTHERN ROCK UNLIMITED"


def test_strips_parentheses_and_punctuation_for_match_key():
    result = normalize_name("F-Secure (UK) Limited")
    assert result.legal_name == "F-Secure (UK) Limited"
    assert result.match_key == "F-SECURE UK"


def test_match_key_is_case_and_whitespace_insensitive():
    assert make_match_key("Some Company Ltd") == make_match_key("SOME   COMPANY   LTD")
    assert make_match_key("Some Company Ltd") == make_match_key("some company ltd")


def test_no_trading_name_when_absent():
    result = normalize_name("BOLTWHIZ LIMITED")
    assert result.trading_name is None
