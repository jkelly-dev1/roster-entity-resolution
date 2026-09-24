"""The four survivorship rules, and the lineage invariant, as pure functions.

A survivorship rule that returns the right value with the wrong provenance
scores identically to a correct one. No accuracy figure in
results/exp3_survivorship.json can distinguish them, so the lineage check is
a separate assertion and not an extra column.
"""

import exp3_survivorship as surv


# (value, source_system, source_row_id, observed_at)
def c(value, system, row_id, date):
    return (value, system, row_id, date)


CLUSTER = [
    c("BARB", "payer_feed", 1, "2026-07-28"),
    c("BARBARA", "license_board", 1, "2024-03-11"),
    c("BARB", "site_scrape", 1, "2026-06-02"),
    c("BARB", "clearinghouse", 1, "2026-07-31"),
]


def test_first_non_null_takes_the_first_row_that_offers_anything():
    assert surv.pick_first_non_null(
        [c(None, "payer_feed", 1, "2026-07-28")] + CLUSTER)[0] == "BARB"
    assert surv.pick_first_non_null(
        [c(None, "a", 1, "2026-01-01")]) is None


def test_most_recent_reads_the_freshness_of_the_file_not_of_the_fact():
    # The failure experiment 3 is built around. The clearinghouse pushes daily
    # and is the freshest row here; it is also the only source carrying a
    # stale address.
    assert surv.pick_most_recent(CLUSTER)[1] == "clearinghouse"


def test_most_recent_breaks_a_tie_on_the_data_and_not_on_dict_ordering():
    same_day = [c("A", "payer_feed", 1, "2026-07-31"),
                c("B", "site_scrape", 1, "2026-07-31")]
    assert surv.pick_most_recent(same_day) == \
        surv.pick_most_recent(list(reversed(same_day)))


def test_majority_vote_returns_the_popular_name_and_not_the_legal_one():
    # This is the case that makes majority_vote's first_name accuracy 0.58
    # in results/exp3_survivorship.json.
    assert surv.pick_majority(CLUSTER)[0] == "BARB"


def test_a_majority_winner_is_attributed_to_a_row_that_actually_holds_it():
    # A vote has no single origin. Recording one arbitrarily would make the
    # lineage test pass while saying something false.
    value, system, row_id, _ = surv.pick_majority(CLUSTER)
    match = [x for x in CLUSTER if x[1] == system and x[2] == row_id][0]
    assert match[0] == value


def test_a_tie_in_the_vote_falls_through_to_the_most_recent_row():
    tied = [c("A", "payer_feed", 1, "2026-01-01"),
            c("B", "site_scrape", 1, "2026-06-01")]
    assert surv.pick_majority(tied)[0] == "B"


def test_per_field_priority_takes_the_legal_name_from_the_licensing_board():
    assert surv.pick_source_priority(CLUSTER, "first_name")[0] == "BARBARA"


def test_per_field_priority_puts_the_clearinghouse_last_on_an_address():
    # And first on the NPI. Three lists rank it first and three rank it last,
    # which is the whole content of the strategy and the thing a single ranked
    # source list cannot express.
    assert surv.PRIORITY["npi"][0] == "clearinghouse"
    for field in ("street", "suite", "zip", "phone"):
        assert surv.PRIORITY[field][-1] == "clearinghouse"


def test_a_priority_list_that_knows_no_source_here_falls_back_rather_than_none():
    # An empty golden field is a worse answer than a value from an unranked
    # source, and pretending the list is exhaustive is how a priority scheme
    # quietly loses fields.
    unranked = [c("X", "some_new_feed", 1, "2026-07-01")]
    assert surv.pick_source_priority(unranked, "street")[0] == "X"


def test_only_the_payer_feed_is_ranked_for_network_status():
    assert surv.PRIORITY["network_status"] == ["payer_feed"]


def test_an_address_is_compared_folded_on_both_sides(  ):
    # (mutation-checked: return v.upper() for street instead of folding and
    # every strategy scores about 0.21 on street, which reads as a finding
    # about survivorship and is not one)
    row = {"street": "8864 Parkside Pkwy.", "given_name": "BARB",
           "family_name": "SILVA"}
    got = surv.offered(row, "street", ("BARB", "SILVA"))
    want = surv.truth_value({"street": "8864 Parkside Parkway"}, "street")
    assert got == want == "8864 PARKSIDE PARKWAY"


def test_a_suite_folded_into_a_scraped_street_line_does_not_pollute_the_street():
    row = {"street": "8864 Parkside Pkwy Suite 203"}
    assert surv.offered(row, "street", (None, None)) == "8864 PARKSIDE PARKWAY"


def test_a_phone_offered_in_any_format_normalizes_before_it_is_compared():
    for written in ["(614) 781-6643", "614.781.6643", "6147816643"]:
        assert surv.offered({"phone": written}, "phone",
                            (None, None)) == "6147816643"


def test_a_field_a_source_does_not_carry_offers_nothing():
    assert surv.offered({"street": None}, "street", (None, None)) is None
    assert surv.offered({"street": "   "}, "street", (None, None)) is None


def test_every_shipped_lineage_row_names_a_source_row_that_holds_its_value(
        lineage):
    # The invariant that catches a survivorship rule inventing a value, or
    # carrying one from the wrong row. Asserted here over the shipped sample;
    # scripts/exp3_survivorship.py asserts it over every field it writes and
    # records the count.
    assert lineage["violations_in_full"] == 0
    assert lineage["sample"]
    for row in lineage["sample"]:
        src = row["source_row"]
        parsed = (src["given_name"], src["family_name"])
        assert surv.offered(src, row["field"], parsed) == row["value"]


def test_the_lineage_sample_covers_more_than_one_source_and_one_field(lineage):
    fields = {r["field"] for r in lineage["sample"]}
    systems = {r["source_system"] for r in lineage["sample"]}
    assert len(fields) > 3
    assert len(systems) > 1
