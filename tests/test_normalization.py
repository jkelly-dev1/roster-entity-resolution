"""Normalization, which decides what a comparator is even able to see.

Every rule here changes which pairs can still be matched, so each one is a
matching decision and gets a test that names the decision rather than the
mechanism.
"""

import normalize


# ---------------------------------------------------------------------------
# NAMES
# ---------------------------------------------------------------------------

def test_the_payer_feed_writes_surname_first_and_is_parsed_that_way():
    assert normalize.parse_name("payer_feed", "SILVA, BARB") == ("BARB", "SILVA")


def test_the_other_sources_write_given_name_first():
    assert normalize.parse_name("clearinghouse", "Barb Silva") == ("BARB", "SILVA")
    assert normalize.parse_name("license_board", "Barbara Silva") == (
        "BARBARA", "SILVA")


def test_the_format_is_chosen_by_source_and_not_guessed_from_a_comma():
    # A row that arrives from the payer feed WITHOUT a comma is refused rather
    # than split on whitespace, because splitting it would silently swap the
    # given name and the surname on exactly the rows that are already
    # malformed.
    assert normalize.parse_name("payer_feed", "BARB SILVA") == (None, None)


def test_a_scraped_credential_suffix_is_stripped_from_the_name():
    assert normalize.parse_name("site_scrape", "Barb Silva, DO") == (
        "BARB", "SILVA")
    assert normalize.parse_name("site_scrape", "Dr. Barb Silva, M.D.") == (
        "BARB", "SILVA")


def test_a_row_naming_two_providers_resolves_to_the_first_of_them():
    # The row's address and phone belong to the first name on it. Nothing
    # downstream can be right about the second, and results/exp2_threshold.json
    # reports those rows separately rather than absorbing them into precision:
    # its `multi_provider` block, asserted by
    # test_results_invariants.py::test_multi_provider_rows_are_reported_separately.
    raw = "Barb Silva, DO and Elena Patel, MD"
    assert normalize.split_persons(raw) == ["Barb Silva, DO", "Elena Patel, MD"]
    assert normalize.parse_name("site_scrape", raw) == ("BARB", "SILVA")


def test_a_name_with_one_token_is_refused_rather_than_half_parsed():
    assert normalize.parse_name("clearinghouse", "Silva") == (None, None)
    assert normalize.parse_name("clearinghouse", "") == (None, None)
    assert normalize.parse_name("clearinghouse", None) == (None, None)


# ---------------------------------------------------------------------------
# ADDRESSES
# ---------------------------------------------------------------------------

def test_every_spelling_of_a_street_type_folds_to_one_token():
    # (mutation-checked: remove "PKWY" from STREET_TYPE_FOLD and this fails on
    # the third form, which is the one the site scrape actually writes)
    want = ["8864", "PARKSIDE", "PARKWAY"]
    for written in ["8864 Parkside Parkway", "8864 PARKSIDE PKWY",
                    "8864 Parkside Pkwy.", "8864 parkside pkwy"]:
        assert normalize.street_tokens(written) == want


def test_a_suite_folded_into_the_street_line_is_pulled_back_out():
    street, suite = normalize.split_suite("8864 Parkside Pkwy Suite 203")
    assert normalize.street_tokens(street) == ["8864", "PARKSIDE", "PARKWAY"]
    assert suite == "SUITE 203"


def test_a_street_with_no_suite_is_returned_unchanged():
    street, suite = normalize.split_suite("8864 Parkside Pkwy")
    assert street == "8864 Parkside Pkwy"
    assert suite is None


def test_the_suite_abbreviations_collapse_to_one_word():
    assert normalize.normalize_suite("Ste. 203") == "SUITE 203"
    assert normalize.normalize_suite("UNIT 203") == "SUITE 203"
    assert normalize.normalize_suite("") is None


def test_an_unknown_street_type_survives_rather_than_being_dropped():
    # The abbreviation table is allowed to be incomplete, the way a real one
    # is. An unknown word costs a token overlap; dropping it would cost the
    # pair.
    assert "ESPLANADE" in normalize.street_tokens("12 Grand Esplanade")


# ---------------------------------------------------------------------------
# IDENTIFIERS
# ---------------------------------------------------------------------------

def test_four_phone_formats_collapse_to_the_same_ten_digits():
    for written in ["(512) 555-0100", "512-555-0100", "512.555.0100",
                    "5125550100", "1-512-555-0100"]:
        assert normalize.clean_phone(written) == "5125550100"


def test_a_malformed_identifier_becomes_absent_rather_than_a_useless_key():
    # (mutation-checked: return the digits unconditionally and rows with a
    # nine-digit NPI start blocking together on a key that means nothing)
    assert normalize.clean_npi("12345") is None
    assert normalize.clean_npi("") is None
    assert normalize.clean_phone("555-0100") is None
    assert normalize.clean_npi("1835084280") == "1835084280"


def test_a_zip_is_truncated_to_five_digits_and_a_short_one_is_refused():
    assert normalize.clean_zip("78701-1234") == "78701"
    assert normalize.clean_zip("787") is None


def test_a_state_that_is_not_two_letters_is_refused():
    assert normalize.clean_state("tx") == "TX"
    assert normalize.clean_state("TEX") is None
    assert normalize.clean_state("") is None


def test_a_whole_row_normalizes_without_the_answer_key():
    row = {"source_system": "site_scrape", "source_row_id": 1,
           "npi": None, "name_raw": "Barb Silva, DO",
           "street": "8864 Parkside Pkwy. Suite 203", "suite": None,
           "city": "columbus", "state": "oh", "zip": "43208-0001",
           "phone": "(614) 781-6643", "specialty": "Rheumatology"}
    out = normalize.normalize_row(row)
    assert out["given_name"] == "BARB"
    assert out["family_name"] == "SILVA"
    assert out["street_tokens"] == ["8864", "PARKSIDE", "PARKWAY"]
    assert out["suite"] == "SUITE 203"
    assert out["city"] == "COLUMBUS"
    assert out["state"] == "OH"
    assert out["zip"] == "43208"
    assert out["phone"] == "6147816643"
    assert out["npi"] is None
