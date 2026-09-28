"""The generator, which is the answer key and is therefore the thing every
number in this repository ultimately rests on.

A generated answer key is only worth its invariants. Where the real world
guarantees something, NPIs are unique, an NPI is Luhn-valid over its
constant prefix, the generator has to guarantee it by construction, and
these tests are what say it still does.
"""

import generate_roster as gen


# ---------------------------------------------------------------------------
# DETERMINISM
# ---------------------------------------------------------------------------

def test_a_provider_is_a_pure_function_of_the_seed_and_the_row_number():
    assert gen.canonical_provider(1) == gen.canonical_provider(1)
    assert gen.canonical_provider(1) != gen.canonical_provider(2)


def test_any_provider_can_be_regenerated_without_the_ones_before_it():
    # The property that makes the manifest hash meaningful: nothing is drawn
    # from a stream, so generating provider 500 alone gives the same row as
    # generating five hundred of them.
    alone = gen.canonical_provider(500)
    in_sequence = [gen.canonical_provider(i) for i in range(1, 501)][-1]
    assert alone == in_sequence


def test_two_different_coordinates_cannot_collide_into_one_draw():
    # Keyed rather than concatenated: ("a", "bc") and ("ab", "c") must differ,
    # which is the failure that makes a generator look random while silently
    # correlating two fields.
    assert gen._bits("a", "bc") != gen._bits("ab", "c")


# ---------------------------------------------------------------------------
# NPI
# ---------------------------------------------------------------------------

def test_twenty_thousand_providers_hold_twenty_thousand_distinct_npis():
    # (mutation-checked: derive the digits with digits(8, "npi", pid) instead
    # of the bijection and this fails with 19,998: the birthday bound at
    # 20,000 draws over 10^8 values)
    npis = {gen.make_npi(pid) for pid in range(1, gen.N_PROVIDERS + 1)}
    assert len(npis) == gen.N_PROVIDERS


def test_every_npi_is_luhn_valid_over_the_constant_prefix():
    # Real NPIs check out against 80840 + the nine base digits. Generating
    # valid ones costs nothing and catches a generator that has started
    # producing plausible-looking garbage.
    for pid in (1, 2, 997, 5000, 19999, 20000):
        npi = gen.make_npi(pid)
        assert len(npi) == 10 and npi.isdigit()
        assert npi[9] == gen.npi_check_digit(npi[:9])


def test_an_npi_allocated_to_an_individual_begins_with_one():
    assert all(gen.make_npi(pid).startswith("1") for pid in (1, 12345, 20000))


# ---------------------------------------------------------------------------
# The corruption is the design
# ---------------------------------------------------------------------------

def test_a_typo_never_touches_the_first_character():
    # A modeling decision with a consequence. Soundex keys on the first
    # letter, so a first-character typo would put every typo beyond soundex's
    # reach and make the pair completeness in results/exp1_blocking.json a
    # restatement of the typo rate rather than a measurement.
    for i in range(200):
        assert gen.typo("Fitzgerald", "t", i)[0] == "F"


def test_a_typo_almost_always_changes_the_string_and_never_lengthens_it():
    # Not always. A substitution can draw the character that was already
    # there, which is a real keystroke error producing no corruption, and
    # forcing every draw to differ would make the corruption rate in
    # results/exp1_blocking.json higher than the constant that names it.
    out = [gen.typo("Fitzgerald", "t", i) for i in range(200)]
    changed = sum(1 for o in out if o != "Fitzgerald")
    assert changed >= 190
    assert all(len(o) in (len("Fitzgerald") - 1, len("Fitzgerald"))
               for o in out)


def test_a_name_too_short_to_corrupt_is_returned_unchanged():
    assert gen.typo("Li", "t", 1) == "Li"


def test_the_license_board_and_the_practice_site_carry_the_current_surname():
    # Two sources against two. That split is what a single ranked source
    # priority list cannot express, and experiment 3 measures the cost.
    assert set(gen.SOURCES_WITH_CURRENT_SURNAME) == {"license_board",
                                                     "site_scrape"}


def test_the_clearinghouse_is_the_freshest_file_and_the_stalest_address():
    # The point of experiment 3 in one assertion. Recency of the file is not
    # recency of the fact, and any survivorship rule reading one as the other
    # picks this source every time.
    assert min(gen.OBSERVED_WITHIN_DAYS,
               key=gen.OBSERVED_WITHIN_DAYS.get) == "clearinghouse"


def test_a_provider_who_moved_is_carried_at_the_old_address_by_the_clearinghouse():
    movers = [gen.canonical_provider(pid) for pid in range(1, 400)]
    movers = [p for p in movers if p["has_moved"]]
    assert movers, "the sample should contain at least one mover"
    p = movers[0]
    row = gen.clearinghouse_row(p, 1, 1)
    assert row["street"] != p["street"]
    assert row["zip"] != p["zip"] or row["street"] != p["street"]


def test_a_provider_who_did_not_move_is_carried_at_the_current_address():
    stayers = [gen.canonical_provider(pid) for pid in range(1, 400)]
    p = [q for q in stayers if not q["has_moved"]][0]
    row = gen.clearinghouse_row(p, 1, 1)
    assert row["zip"] == p["zip"]


def test_the_license_board_ships_no_address_and_no_phone_at_all():
    p = gen.canonical_provider(7)
    row = gen.license_board_row(p, 1, 1)
    assert row["street"] is None and row["suite"] is None
    assert row["zip"] is None and row["phone"] is None and row["city"] is None
    assert row["license_state"] == p["state"]


def test_the_payer_feed_is_the_only_source_carrying_network_status():
    p = gen.canonical_provider(7)
    assert gen.payer_feed_row(p, 1, 1)["network_status"] == p["network_status"]
    assert gen.license_board_row(p, 1, 1)["network_status"] is None
    assert gen.clearinghouse_row(p, 1, 1)["network_status"] is None
    assert gen.site_scrape_row(p, 1, 1)["network_status"] is None


def test_an_observation_date_comes_from_the_reference_date_not_the_clock():
    # A generator that reads the clock produces different data on every run
    # and nothing downstream is reproducible.
    a = gen.observed_at("payer_feed", 5)
    b = gen.observed_at("payer_feed", 5)
    assert a == b <= gen.REFERENCE_DATE


def test_the_second_ingest_only_adds_rows_and_reuses_no_row_id():
    providers = [gen.canonical_provider(pid) for pid in range(1, 600)]
    rows1 = []
    for p in providers:
        rows1.append(gen.payer_feed_row(p, p["provider_id"], 1))
    rows2, links2 = gen.generate_batch2(providers, rows1)
    seen = {(r["source_system"], r["source_row_id"]) for r in rows1}
    for r in rows2:
        assert r["ingest_batch"] == 2
        assert (r["source_system"], r["source_row_id"]) not in seen
    assert len(links2) == len(rows2)
