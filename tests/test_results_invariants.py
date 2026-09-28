"""Invariants over the shipped results/*.json.

These are not regression tests against frozen numbers. Each one states a
property that has to hold of any correct run, so a re-run on a different
machine still passes while a run whose measurement logic has broken does not.
Several of them exist because the corresponding defect actually rendered as a
plausible table and was only visible against a rule stated in advance.
"""

import pytest


# ---------------------------------------------------------------------------
# EXPERIMENT 1: BLOCKING
# ---------------------------------------------------------------------------

def test_no_strategy_finds_more_true_pairs_than_exist(exp1):
    # (mutation-checked: drop the parentheses around the strategy clause in
    # exp1's join and the union emits every pair twice, which reports a pair
    # completeness of 2.6634, measured against this tree on 2026-09-14)
    for s in exp1["strategies"]:
        assert s["true_pairs_found"] <= exp1["true_pairs"]
        assert s["true_pairs_found"] <= s["candidate_pairs"]


def test_pair_completeness_is_a_share(exp1):
    for s in exp1["strategies"]:
        assert 0.0 <= s["pair_completeness"] <= 1.0
        assert 0.0 <= s["reduction_ratio"] <= 1.0


def test_the_union_is_at_least_as_complete_as_any_strategy_in_it(exp1):
    union = [s for s in exp1["strategies"] if s["strategy"] == "union"][0]
    for s in exp1["strategies"]:
        if s["strategy"] != "union":
            assert union["pair_completeness"] >= s["pair_completeness"]
            assert union["candidate_pairs"] >= s["candidate_pairs"]


def test_npi_blocking_alone_was_predicted_sufficient_and_was_refuted(exp1):
    # The prediction is part of the result. It was recorded before the run and
    # it is kept whichever way it went.
    p = exp1["prediction"]
    assert p["verdict"] == "REFUTED"
    assert p["measured"] < p["threshold"]


def test_the_license_board_can_never_block_on_an_address_or_a_phone(exp1):
    lb = [r for r in exp1["blockable_by_source"]
          if r["source_system"] == "license_board"][0]
    assert lb["can_block_on_zip"] == 0
    assert lb["can_block_on_phone"] == 0
    assert lb["can_block_on_soundex"] == lb["rows"]


def test_the_clearinghouse_carries_an_npi_on_every_row(exp1):
    ch = [r for r in exp1["blockable_by_source"]
          if r["source_system"] == "clearinghouse"][0]
    assert ch["can_block_on_npi"] == ch["rows"]


def test_an_index_is_measured_against_a_genuinely_unindexed_plan(exp1):
    # (mutation-checked: un-qualify the DROP INDEX statement and the drop
    # silently does nothing, which made the un-indexed incremental probe read
    # 0.4 ms against a true 8.6 ms)
    plans = exp1["query_plans"]
    before = plans["incremental_no_index"]["50"]["nodes"]
    after = plans["incremental_with_index"]["50"]["nodes"]
    assert any("Seq Scan" in n for n in before)
    assert before != after


def test_the_full_batch_join_is_not_helped_by_an_index(exp1):
    # A negative result that is published as one. A blocking join reads both
    # sides of the table once whatever indexes exist, so the planner hashes it
    # and the btree changes nothing. The index earns its keep on the
    # incremental probe and nowhere else.
    plans = exp1["query_plans"]
    assert (plans["full_batch_no_index"]["nodes"]
            == plans["full_batch_with_index"]["nodes"])


# ---------------------------------------------------------------------------
# EXPERIMENT 2: THE THRESHOLD
# ---------------------------------------------------------------------------

def test_recall_never_rises_as_the_threshold_rises(exp2):
    # A grid walked ascending in sweep() collapses every row onto the
    # accept-everything point. sweep() refuses that curve before a results
    # file is written, and tests/test_sweep.py runs that edit.
    curve = exp2["curve"]
    for a, b in zip(curve, curve[1:]):
        assert b["threshold"] > a["threshold"]
        assert b["recall"] <= a["recall"] + 1e-9
        assert b["tp"] <= a["tp"]
        assert b["fp"] <= a["fp"]


def test_the_curve_is_not_one_point_repeated(exp2):
    """The collapse that the monotonicity test above cannot see.

    Walking the grid upward makes tp and fp (running totals) accept everything
    at the first and lowest threshold and then report those same counts for
    every threshold after it. The curve is then constant, and a constant curve
    satisfies every clause of test_recall_never_rises_as_the_threshold_rises:
    recall never rises, tp never rises, fp never rises. The only clause a
    collapse trips is the `threshold` ordering, and only in the variant that
    also drops the reverse.

    What distinguishes a collapsed curve from a swept one is that its ends
    agree. Asserted here, and in sweep() itself so a run fails before it
    writes a results file instead of after.
    """
    curve = exp2["curve"]
    assert len(curve) > 1
    ends = ((curve[0]["tp"], curve[0]["fp"]), (curve[-1]["tp"], curve[-1]["fp"]))
    assert ends[0] != ends[1], (
        "threshold %.3f and threshold %.3f report the same tp and fp, so the "
        "sweep accepted the same pairs at every threshold"
        % (curve[0]["threshold"], curve[-1]["threshold"]))
    # More than two distinct points, so not two ends around a flat middle.
    assert len({(r["tp"], r["fp"]) for r in curve}) > 2


def test_multi_provider_rows_are_reported_separately(exp2):
    """The promise made in schema.sql and normalize.py, given something to read.

    A site_scrape row naming two providers is about two people and carries one
    address, one phone and one specialty. No pairwise resolver can be right
    about it, and both of those files say the results report such rows
    separately "instead of letting them move precision unseen". This holds
    the results file to that sentence.
    """
    m = exp2["multi_provider"]
    assert m["rows"] > 0, (
        "no multi-provider rows at all, so the claim in sql/schema.sql and "
        "scripts/normalize.py is about a case this data does not contain")
    # They must be a MINORITY, or "unseen" is the wrong word and the headline
    # precision is mostly a statement about rows nobody could resolve.
    assert m["eval_pairs_touching_one"] < exp2["eval_pairs_scored"] * 0.5
    assert 0 <= m["accepted_and_false_at_the_operating_point"] \
        <= m["accepted_at_the_operating_point"]
    assert m["accepted_at_the_operating_point"] <= m["eval_pairs_touching_one"]
    # The share is a share, and it is of the false pairs accepted, which is the
    # quantity the promise is about.
    assert 0.0 <= m["share_of_all_accepted_false_they_account_for"] <= 1.0
    assert m["operating_threshold"] == \
        exp2["cost_optimal"][m["priced_at_ratio"]]["cost_optimal"]["threshold"]


def test_recall_is_capped_by_what_blocking_kept(exp2):
    # Every recall figure is bounded above by experiment 1. A true pair the
    # blocker dropped is a missed match, not an absent one, and counting
    # recall only over scored pairs would report a number no operator could
    # obtain.
    ceiling = exp2["recall_ceiling_from_blocking"]
    assert ceiling < 1.0
    assert all(row["recall"] <= ceiling + 1e-9 for row in exp2["curve"])


def test_false_negatives_include_the_pairs_blocking_never_emitted(exp2):
    for row in exp2["curve"]:
        assert row["tp"] + row["fn"] == exp2["eval_true_pairs_total"]


def test_the_weights_were_fitted_on_a_disjoint_half_of_the_providers(exp2):
    assert exp2["fit_matches"] > 0 and exp2["fit_non_matches"] > 0
    assert exp2["eval_true_pairs_scored"] > 0
    # Neither half may be empty, and the evaluation half must not be the whole
    # data set, or the split has silently stopped happening.
    assert exp2["eval_pairs_scored"] < exp2["pairs_scored"]


def test_an_agreeing_npi_is_the_strongest_evidence_any_field_carries(exp2):
    npi = exp2["weights"]["npi"]
    assert npi["agree"] > 0 and npi["disagree"] < 0
    assert all(npi["agree"] >= exp2["weights"][f]["agree"]
               for f in exp2["weights"])


def test_agreeing_on_a_surname_carries_almost_no_evidence_after_blocking(exp2):
    # Not a defect. Blocking already requires near agreement on the surname,
    # so nearly every candidate pair agrees on it and the agreement stops
    # discriminating. A weight near zero here is what a correctly conditioned
    # u probability looks like.
    assert abs(exp2["weights"]["family_name"]["agree"]) < 1.0
    assert exp2["weights"]["family_name"]["disagree"] < -1.0


def test_choosing_by_f1_costs_nothing_at_parity_and_costs_money_at_ten_to_one(
        exp2):
    # The headline. F1 weights the two errors equally by construction, so it
    # is a defensible choice only when they cost the same.
    assert exp2["cost_optimal"]["1"]["extra_cost_of_choosing_by_f1"] == 0
    assert exp2["cost_optimal"]["10"]["extra_cost_of_choosing_by_f1"] > 0
    assert exp2["cost_optimal"]["30"]["extra_cost_of_choosing_by_f1"] > \
        exp2["cost_optimal"]["10"]["extra_cost_of_choosing_by_f1"]


def test_the_cost_optimal_threshold_rises_with_the_price_of_a_false_match(
        exp2):
    thresholds = [exp2["cost_optimal"][str(r)]["cost_optimal"]["threshold"]
                  for r in exp2["cost_ratios"]]
    assert thresholds == sorted(thresholds)


def test_the_prediction_that_f1_is_not_cost_optimal_is_recorded(exp2):
    assert exp2["predictions"]["f1_is_not_cost_optimal"]["verdict"] == "held"


# ---------------------------------------------------------------------------
# CLUSTER DAMAGE
# ---------------------------------------------------------------------------

def test_the_transitive_closure_multiplies_a_pairwise_error(exp2):
    # One false pair is not one error. Connected components are transitive, so
    # a wrong link merges two whole providers and everything attached to
    # either of them.
    at_10 = [d for d in exp2["cluster_damage"]
             if "cost_optimal_10_to_1" in d["operating_point"]][0]
    assert at_10["welded_provider_share"] > \
        at_10["false_pair_share_of_accepted"]
    assert at_10["damage_amplification"] > 1.0


def test_welding_gets_worse_as_the_threshold_falls(exp2):
    curve = sorted(exp2["cluster_damage"], key=lambda d: d["threshold"])
    shares = [d["welded_provider_share"] for d in curve]
    assert shares[0] > shares[-1]
    # The cliff: at the loosest threshold measured a single cluster holds many
    # different providers; at the chosen one it holds two.
    assert curve[0]["most_providers_in_one_cluster"] > 10
    at_10 = [d for d in curve if "cost_optimal_10_to_1" in d["operating_point"]][0]
    assert at_10["most_providers_in_one_cluster"] <= 3


def test_a_cluster_never_holds_fewer_than_one_provider(exp2):
    for d in exp2["cluster_damage"]:
        assert d["most_providers_in_one_cluster"] >= 1
        assert d["providers_in_a_welded_cluster"] <= d["providers_present"]


# ---------------------------------------------------------------------------
# THE REVIEW BAND
# ---------------------------------------------------------------------------

def test_a_wider_review_band_never_shrinks_the_queue(exp2):
    bands = exp2["review_band"]["bands"]
    for a, b in zip(bands, bands[1:]):
        assert b["review_queue_pairs"] >= a["review_queue_pairs"]
        assert b["expected_cost"] <= a["expected_cost"]


def test_the_band_is_priced_as_a_break_even_and_not_as_a_verdict(exp2):
    # The repository does not know what a human review costs and must not
    # publish a number that assumes one.
    band = exp2["review_band"]
    assert band["reviewer_assumed_correct"] is True
    assert all("break_even_review_cost" in b for b in band["bands"])
    assert all(b["break_even_review_cost"] >= 0 for b in band["bands"])


def test_a_zero_width_band_reviews_nothing_and_removes_nothing(exp2):
    zero = exp2["review_band"]["bands"][0]
    assert zero["band_width_fraction_of_score_range"] == 0.0
    assert zero["review_queue_pairs"] == 0
    assert zero["cost_removed_vs_no_band"] == 0


# ---------------------------------------------------------------------------
# EXPERIMENT 3: SURVIVORSHIP
# ---------------------------------------------------------------------------

def test_every_accuracy_is_a_share(exp3):
    for strat, fields in exp3["field_accuracy"].items():
        for f, v in fields.items():
            assert v is None or 0.0 <= v <= 1.0


def test_per_field_priority_beats_every_other_strategy_on_the_mean(exp3):
    means = exp3["mean_accuracy"]
    assert max(means, key=means.get) == "source_priority"


def test_the_prediction_that_majority_vote_would_win_was_refuted(exp3):
    assert exp3["prediction"]["verdict"] == "REFUTED"


def test_majority_vote_loses_the_legal_first_name_to_the_nickname(exp3):
    # The sharpest case, and the one predicted. Three sources carry the
    # practice nickname and one carries the legal name, so the majority is
    # popular and wrong.
    acc = exp3["field_accuracy"]
    assert acc["majority_vote"]["first_name"] < 0.7
    assert acc["source_priority"]["first_name"] > 0.9


def test_majority_vote_still_wins_where_the_sources_differ_only_by_noise(exp3):
    # A real counter-example, kept. Every source is equally authoritative
    # about a surname and their typos are independent, so a vote outperforms
    # trusting one source. Priority wins where sources are SYSTEMATICALLY
    # different, not everywhere.
    assert "last_name" in exp3["single_site_majority_beats_priority"]


def test_a_provider_at_two_practice_sites_has_no_single_correct_address(exp3):
    # Restricting to single-site providers is what separates a survivorship
    # failure from a data model that cannot be right.
    allp = exp3["field_accuracy"]["source_priority"]
    single = exp3["field_accuracy_single_site_providers_only"]["source_priority"]
    assert single["street"] > allp["street"]
    assert single["zip"] > allp["zip"]
    assert exp3["providers_listed_twice_by_a_source"] > 0


def test_welded_clusters_are_excluded_from_survivorship_rather_than_scored(
        exp3):
    # A cluster about two providers has no correct golden record, and scoring
    # one against an arbitrary member would credit or blame a survivorship
    # rule for a matching decision.
    assert exp3["clusters_skipped_as_welded"] > 0
    assert (exp3["clusters_scored"] + exp3["clusters_skipped_as_welded"]
            == exp3["clusters_total"])


def test_no_golden_field_value_is_missing_its_lineage(exp3):
    assert exp3["lineage_violations"] == 0
    assert exp3["lineage_fields_checked"] == exp3["golden_fields_written"]


# ---------------------------------------------------------------------------
# EXPERIMENT 4: OVERRIDE STABILITY
# ---------------------------------------------------------------------------

def test_natural_keys_lose_no_override_and_misapply_none(exp4):
    nk = exp4["replay"]["natural_key"]
    assert nk["retained"] == exp4["overrides"]["total"]
    assert nk["lost"] == 0 and nk["misapplied"] == 0


def test_cluster_id_keying_misapplies_overrides_onto_other_providers(exp4):
    # The result worth leading with. Not lost: MISAPPLIED. A correct human
    # decision is still being enforced, on a record the operator never saw.
    ci = exp4["replay"]["cluster_id"]
    assert ci["misapplied"] > exp4["overrides"]["total"] * 0.4
    # Every misapplication lands somewhere unrelated. None of them merely
    # drifted within the cluster the operator was looking at.
    assert ci["misapplied_to_unrelated_cluster"] == ci["misapplied"]
    # The ones that survived did so by accident: nothing in the scheme
    # distinguishes them, and none were lost, so a reader cannot tell a
    # surviving override from a transplanted one without checking the rows.
    assert ci["lost"] == 0


def test_every_override_is_accounted_for_under_both_schemes(exp4):
    total = exp4["overrides"]["total"]
    for scheme in ("cluster_id", "natural_key"):
        r = exp4["replay"][scheme]
        assert r["retained"] + r["lost"] + r["misapplied"] == total


def test_a_small_change_in_the_data_renumbers_almost_every_cluster(exp4):
    # (mutation-checked: compare run1[cid] against run2[cid] instead of
    # comparing member sets and the changed-membership figure becomes the
    # renumbering, which destroys the contrast this result rests on)
    changed = exp4["run1_clusters_with_changed_membership"]
    renumbered = exp4["run1_cluster_ids_no_longer_holding_their_original_set"]
    total = exp4["ingest1"]["clusters"]
    assert changed < total * 0.25
    assert renumbered > total * 0.85
    assert renumbered > changed * 3
    # The headline is the sum of two different things, which the prose has to
    # keep apart. Run 2 holds fewer clusters than run 1, so some run-1 ids have
    # no counterpart at all, and calling those "a different member set at the
    # old id" would describe an id that holds nothing.
    different = exp4["run1_cluster_ids_pointing_at_a_different_set"]
    absent = exp4["run1_cluster_ids_with_no_cluster_at_that_id"]
    assert different + absent == renumbered
    assert absent == (exp4["ingest1"]["clusters"]
                      - exp4["ingest1_plus_2"]["clusters"])


def test_the_recorded_row_counts_of_the_two_ingests_agree(exp4):
    assert exp4["ingest1_plus_2"]["rows"] > exp4["ingest1"]["rows"]
    assert (exp4["ingest1_plus_2"]["rows"] - exp4["ingest1"]["rows"]
            == exp4["new_rows_in_second_ingest"])


def test_some_pins_are_now_contradicted_by_a_corrected_source_row(exp4):
    # A system that never revisits a human decision is as broken as one that
    # discards it. An honest middle is to report the count.
    assert 0 < exp4["pins_contradicted_by_a_corrected_source_row"] \
        <= exp4["overrides"]["pin"]


def test_the_prediction_that_overrides_survive_was_refuted(exp4):
    assert exp4["predictions"]["overrides_survive_reingest"]["verdict"] \
        == "REFUTED"
    assert exp4["predictions"]["cluster_id_keying_misapplies"]["verdict"] \
        == "held"


# ---------------------------------------------------------------------------
# Every result names the input it was measured on
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["exp1", "exp2", "exp3", "exp4"])
def test_every_result_carries_the_manifest_of_its_input(name, request):
    # The generated rows are not committed; they are a pure function of the
    # seed, so this hash is what lets a reader who regenerates prove they
    # hold the same input rather than take it on trust.
    data = request.getfixturevalue(name)
    assert len(data["input_manifest_sha256"]) == 64


def test_all_four_experiments_measured_the_same_input(exp1, exp2, exp3, exp4):
    shas = {d["input_manifest_sha256"] for d in (exp1, exp2, exp3, exp4)}
    assert len(shas) == 1


# ---------------------------------------------------------------------------
# The cost model itself
#
# The repository's central sentence is that a matching threshold is a COST
# DECISION. The arithmetic that turns a price into a threshold lives in one
# expression, `ratio * fp + fn`, and nothing executed it. Swapping the two
# terms so a missed match is the expensive one moved the 10:1 threshold from
# 8.382 to -0.281, more than doubled the false pairs accepted, and flipped a
# recorded prediction from held to REFUTED, with 107 tests green.
#
# These re-derive the optimum from the published curve instead of trusting the
# recorded one, which is the only way to notice that the pricing changed.
# ---------------------------------------------------------------------------

def _reprice(curve, ratio):
    """The optimum this ratio implies, computed here from the curve."""
    priced = [(ratio * r["fp"] + r["fn"], r["threshold"], r) for r in curve]
    best = min(priced, key=lambda t: (t[0], t[1]))
    return best[0], best[2]


def test_every_recorded_optimum_is_the_optimum_its_price_implies(exp2):
    curve = exp2["curve"]
    for ratio in exp2["cost_ratios"]:
        want_cost, want_row = _reprice(curve, ratio)
        got = exp2["cost_optimal"][str(ratio)]["cost_optimal"]
        assert got["cost"] == want_cost, (
            f"at {ratio}:1 the recorded optimum costs {got['cost']} but the "
            f"cheapest point on the published curve costs {want_cost}")
        assert got["threshold"] == want_row["threshold"]


def test_the_recorded_optima_are_what_the_pricing_code_computes(exp2):
    """exp2_threshold.price() replayed over the published curve. The tests
    around this one reprice the curve with their own helper, so an edit to
    the production pricing that re-derived the file would pass them; this
    one reads the code that priced the run."""
    import exp2_threshold
    for ratio in exp2["cost_ratios"]:
        best = min(exp2_threshold.price(exp2["curve"], ratio),
                   key=lambda r: r["cost"])
        assert best == exp2["cost_optimal"][str(ratio)]["cost_optimal"], (
            f"at {ratio}:1 the pricing code picks threshold "
            f"{best['threshold']}, the run recorded "
            f"{exp2['cost_optimal'][str(ratio)]['cost_optimal']['threshold']}")


def test_a_false_match_is_the_priced_error_and_a_miss_is_the_unit(exp2):
    """The direction of the price, asserted. If the two terms are swapped the
    thresholds still come out sorted, they collapse to one value, and a list
    of equal numbers is sorted, so the ordering test above cannot see it.

    Raising the price of a FALSE MATCH must make the matcher stricter, which
    means a HIGHER threshold and FEWER accepted pairs. Under the swap it makes
    the matcher looser, which is the opposite."""
    curve = exp2["curve"]
    cheap_cost, cheap = _reprice(curve, 1)
    dear_cost, dear = _reprice(curve, 30)
    assert dear["threshold"] > cheap["threshold"], (
        "pricing a false match 30x higher did not raise the threshold; the "
        "two error terms are the wrong way round")
    assert dear["fp"] <= cheap["fp"], (
        "the stricter price accepted at least as many false pairs")


def test_choosing_by_f1_really_does_cost_money_at_ten_to_one(exp2):
    """The claim the section is named for, re-derived from the curve."""
    curve = exp2["curve"]
    best_f1 = max(curve, key=lambda r: r["f1"])
    opt_cost, opt = _reprice(curve, 10)
    f1_cost = 10 * best_f1["fp"] + best_f1["fn"]
    assert f1_cost > opt_cost, (
        "choosing by F1 is free at 10:1, so the section's premise is gone")
    assert opt["threshold"] != best_f1["threshold"]


def test_the_recorded_penalty_for_choosing_by_f1_is_the_arithmetic_one(exp2):
    curve = exp2["curve"]
    for ratio in exp2["cost_ratios"]:
        opt_cost, _ = _reprice(curve, ratio)
        blob = exp2["cost_optimal"][str(ratio)]
        at_f1 = blob["cost_at_f1_optimal_threshold"]
        want = ratio * at_f1["fp"] + at_f1["fn"]
        assert at_f1["cost"] == want, (
            f"at {ratio}:1 the F1 point is recorded as costing "
            f"{at_f1['cost']}, arithmetic says {want}")


def test_the_cluster_id_replay_split_matches_the_recorded_ordering(exp4):
    """Cluster ids are an artifact of pair order.

    Union-find assigns ids in the order it sees pairs, so the replay's
    retained/misapplied split is a property of the ORDER BY in the pair query.
    Dropping that ordering can move the split away from 229/271, and the
    other tests assert relations, not the split itself, so this is the test
    that fails.

    exp2_threshold.py's own comment calls unordered union-find "the hardest
    kind of irreproducibility to notice". This is what notices it.
    """
    ck = exp4["replay"]["cluster_id"]
    total = ck["retained"] + ck["lost"] + ck["misapplied"]
    assert total == exp4["overrides"]["total"], (
        "the three outcomes do not sum to the overrides")
    assert ck["retained"] == 229, (
        f"cluster_id retained {ck['retained']}, recorded run says 229 -- the "
        "pair ordering changed, so the cluster ids did too")
    assert ck["misapplied"] == 271


def test_natural_key_misapplication_is_structurally_impossible_not_measured(exp4):
    """The zero in that column is a statement about the scheme.

    A natural key names a source row: on replay it resolves to that row or it
    does not resolve at all, and there is no outcome where it lands on a
    DIFFERENT provider. So the counter is never incremented, and reading its
    zero as a measured result would credit the scheme with surviving a test it
    was never subjected to. Asserted here so the reasoning is checked rather
    than the counter.
    """
    nk = exp4["replay"]["natural_key"]
    assert nk["misapplied"] == 0
    assert nk["retained"] + nk["lost"] == exp4["overrides"]["total"]
    # `lost` is zero by construction in this experiment: run 2 is clustered
    # over batches 1 and 2, so every batch-1 key is in its key set. The
    # identity below checks that the recorded counts agree with each other.
    # It is not evidence that the load was additive: all three numbers are
    # read from the same database in one run, so it holds for any load.
    assert exp4["new_rows_in_second_ingest"] > 0
    assert (exp4["ingest1_plus_2"]["rows"]
            == exp4["ingest1"]["rows"] + exp4["new_rows_in_second_ingest"]), (
        "the recorded row counts disagree -- %d + %d != %d"
        % (exp4["ingest1"]["rows"], exp4["new_rows_in_second_ingest"],
           exp4["ingest1_plus_2"]["rows"]))
