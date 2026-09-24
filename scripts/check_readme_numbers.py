"""Re-derive every published figure from results/*.json and require it verbatim
in README.md.

    python3 scripts/check_readme_numbers.py

Why this exists. A number in a document has no owner. The results files are
rewritten by every run; the prose is rewritten by hand, sometimes, when
somebody remembers. This script makes the prose fail instead of drift.

It covers sentences, not only table rows. A percentage inside a paragraph does
not look like a figure to a reader or to whoever writes a deriver, so it is
the one most likely to go stale. Roughly a third of the checks below are prose.

It prints how many figures it checked whether or not any are missing, so a
version of this file that has quietly stopped deriving half of them is visible
rather than clean.

What it does not do. It compares the README against the COMMITTED evidence, not
against a fresh run. If the experiments are re-run and the results change, this
script goes red and the README is what has to be updated. It says nothing about
whether the results themselves are right; that is what tests/ is for.
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import lab

README = os.path.join(lab.REPO, "README.md")


def n(x):
    """1234567 -> "1,234,567", the way the README writes it."""
    return "{:,}".format(int(x))


def f(x, places):
    return "%.*f" % (places, float(x))


def pct(x, places=0):
    return "%.*f" % (places, float(x) * 100.0)


def published_table_rows(readme, header_cell):
    """The first cell of every data row of the README table whose first HEADER
    cell is `header_cell`, in the order the README prints them.

    The README, not a list in this file. A hand-written collection of the
    values a derivation is willing to check would skip anything outside it in
    silence, and a checker like that cannot judge a row the README publishes
    later, because the list decides and the list is written by hand. Reading
    the published labels out of the README inverts it:
    a row added to the README is checked because it is there, and a row the
    README does not publish is not checked because it is not.
    """
    lines = readme.splitlines()
    head = "| " + header_cell + " |"
    out = []
    for i, ln in enumerate(lines):
        if not ln.startswith(head):
            continue
        j = i + 1
        # the | --- | --- | separator markdown requires between head and body
        if j < len(lines) and set(lines[j].replace("|", "").strip()) <= set("- :"):
            j += 1
        while j < len(lines) and lines[j].startswith("|"):
            cells = [c.strip() for c in lines[j].strip().strip("|").split("|")]
            if cells and cells[0]:
                out.append(cells[0])
            j += 1
        return out
    return out


def width_label(w):
    """The README's label for a band width: 0.0 -> "none", 0.02 -> "2%".

    Derived, so a label cannot fall behind the widths the results file
    carries.

    `%g` because 0.05 * 100.0 is 5.000000000000001 in binary floating point.
    """
    return "none" if not w else "%g%%" % (w * 100.0)


NUMBER_WORD = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five",
               6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten"}


def build(readme):
    """Return the checks and the orphans, as two lists.

    Each check is a pair of a label and a string that must appear in README.md.

    The second list holds README table rows with no results row behind them:
    a published figure whose evidence is missing, which is the failure the
    first list cannot express because it only ever asks whether a derived
    string is PRESENT.
    """
    e1 = lab.read_result("exp1_blocking")
    e2 = lab.read_result("exp2_threshold")
    e3 = lab.read_result("exp3_survivorship")
    e4 = lab.read_result("exp4_override_stability")
    want = []
    orphans = []

    def add(label, s):
        want.append((label, s))

    # ---- the data ----------------------------------------------------------
    add("source rows", n(e1["source_rows"]))
    add("true pairs", n(e1["true_pairs"]))
    add("all possible pairs", n(e1["all_possible_pairs"]))
    for row in e1["blockable_by_source"]:
        s = row["source_system"]
        add("%s rows" % s, n(row["rows"]))
        add("%s row/blocking row" % s,
            "| `%s` | %s | %s | %s | %s | %s |"
            % (s, n(row["rows"]), n(row["can_block_on_npi"]),
               n(row["can_block_on_zip"]), n(row["can_block_on_phone"]),
               n(row["can_block_on_soundex"])))

    # ---- experiment 1 ------------------------------------------------------
    label_of = {"npi_exact": "exact NPI",
                "zip_surname4": "ZIP + first 4 of surname",
                "soundex_state": "surname soundex + state",
                "phone_exact": "phone digits",
                "union": "union of all four"}
    union = None
    for st in e1["strategies"]:
        if st["strategy"] == "union":
            union = st
        add("blocking row %s" % st["strategy"],
            "| %s | %s | %s | %s | %s |"
            % (label_of[st["strategy"]], n(st["candidate_pairs"]),
               n(st["true_pairs_found"]), f(st["pair_completeness"], 4),
               f(st["reduction_ratio"], 6)))
    npi = [s for s in e1["strategies"] if s["strategy"] == "npi_exact"][0]
    add("npi completeness in prose", "REFUTED AT %s" % f(npi["pair_completeness"], 4))
    add("npi completeness as a percentage",
        "reaches %s percent of the true" % pct(npi["pair_completeness"]))
    add("prediction threshold", "at least %s percent"
        % pct(e1["prediction"]["threshold"]))
    add("true pairs found by the union", n(union["true_pairs_found"]))
    lost = e1["true_pairs"] - union["true_pairs_found"]
    add("true pairs lost to blocking", "%s true pairs are gone" % n(lost))
    add("true pairs lost, in the summary", "lose %s pairs" % n(lost))

    qp = e1["query_plans"]
    add("full batch timings", "%s ms to %s ms"
        % (f(qp["full_batch_no_index"]["exec_ms"], 3),
           f(qp["full_batch_with_index"]["exec_ms"], 3)))
    for size in ("50", "1000"):
        add("incremental %s timings" % size, "%s ms to %s ms"
            % (f(qp["incremental_no_index"][size]["exec_ms"], 3),
               f(qp["incremental_with_index"][size]["exec_ms"], 3)))
    # The mutation row in the claims table carries two of these figures. A
    # figure quoted inside a parenthesis in a table cell is still a figure, and
    # nothing but a deriver keeps it matching the results file.
    add("unqualified-drop mutation figures",
        "%s ms where the true unindexed plan reads %s ms"
        % (f(qp["incremental_with_index"]["50"]["exec_ms"], 3),
           f(qp["incremental_no_index"]["50"]["exec_ms"], 3)))

    # ---- experiment 2 ------------------------------------------------------
    add("recall ceiling", f(e2["recall_ceiling_from_blocking"], 4))
    add("eval pairs scored", n(e2["eval_pairs_scored"]))
    add("eval true pairs scored", n(e2["eval_true_pairs_scored"]))
    add("eval true pairs total", n(e2["eval_true_pairs_total"]))

    for field, label in [("npi", "NPI"), ("street", "street"),
                         ("phone", "phone"), ("zip", "ZIP"),
                         ("given_name", "given name"),
                         ("specialty", "specialty"),
                         ("family_name", "family name"), ("state", "state")]:
        w = e2["weights"][field]
        add("weight row %s" % field, "| %s | %+.2f | %+.2f |"
            % (label, w["agree"], w["disagree"]))

    f1 = e2["f1_optimal"]
    add("f1 threshold", f(f1["threshold"], 3))
    add("f1 precision and recall",
        "precision %s and recall %s" % (f(f1["precision"], 4),
                                        f(f1["recall"], 4)))
    ratio_label = {"1": "1:1", "3": "3:1", "10": "10:1", "30": "30:1"}
    for r in ("1", "3", "10", "30"):
        c = e2["cost_optimal"][r]
        extra = c["extra_cost_of_choosing_by_f1"]
        if extra:
            tail = "+%s, or %s%%" % (
                n(extra), pct(extra / float(c["cost_optimal"]["cost"])))
        else:
            tail = "none"
        add("cost row %s" % r, "| %s | %s | %s | %s | %s |"
            % (ratio_label[r], f(c["cost_optimal"]["threshold"], 3),
               n(c["cost_optimal"]["cost"]),
               n(c["cost_at_f1_optimal_threshold"]["cost"]), tail))
    add("threshold movement at 10:1",
        "moves the optimal threshold by %s points"
        % f(e2["cost_optimal"]["10"]["threshold_moved_by"], 1))
    add("threshold movement in section 2",
        "The\nthreshold moves %s points at 10:1 and %s at 30:1"
        % (f(e2["cost_optimal"]["10"]["threshold_moved_by"], 1),
           f(e2["cost_optimal"]["30"]["threshold_moved_by"], 1)))
    for r in ("10", "30"):
        c = e2["cost_optimal"][r]
        add("f1 penalty percentage at %s:1" % r, "cost %s percent\nmore"
            % pct(c["extra_cost_of_choosing_by_f1"]
                  / float(c["cost_optimal"]["cost"]))
            if r == "10" else "costs %s percent\nmore"
            % pct(c["extra_cost_of_choosing_by_f1"]
                  / float(c["cost_optimal"]["cost"])))

    # cluster damage. WHICH rows are published is read out of the README
    # (see published_table_rows); every one of the 13 result rows gets a label,
    # and a row is checked when the README carries it.
    published_damage = published_table_rows(readme, "Threshold")
    damage_labels = {}
    for d in e2["cluster_damage"]:
        label = f(d["threshold"], 3)
        if "f1_optimal" in d["operating_point"]:
            label += " (F1)"
        elif "cost_optimal_10_to_1" in d["operating_point"]:
            label += " (10:1)"
        damage_labels[label] = d
        if label not in published_damage:
            continue
        add("damage row %s" % d["threshold"], "| %s | %s | %s | %s | %s | %s | %s |"
            % (label, n(d["accepted_pairs"]), n(d["accepted_false"]),
               f(d["false_pair_share_of_accepted"], 4), n(d["clusters"]),
               n(d["providers_in_a_welded_cluster"]),
               n(d["most_providers_in_one_cluster"])))
    for lab_ in published_damage:
        if lab_ not in damage_labels:
            orphans.append(
                "the cluster-damage table publishes a row for %r and "
                "results/exp2_threshold.json has no cluster_damage entry with "
                "that threshold" % lab_)

    # The distance in rows is derived. A direction word and a small integer
    # are exactly the kind of figure a reader cannot check and a writer cannot
    # remember, so nothing but a deriver keeps them true.
    op_label = [lab_ for lab_ in published_damage
                if lab_ in damage_labels
                and "cost_optimal_10_to_1" in damage_labels[lab_]["operating_point"]]
    six = [lab_ for lab_ in published_damage
           if lab_ in damage_labels
           and damage_labels[lab_]["most_providers_in_one_cluster"] >= 6]
    if op_label and six:
        i_op = published_damage.index(op_label[0])
        # The table is ascending in threshold and the damage grows as the
        # threshold falls, so "where it first reaches six" walking down from
        # the operating point is the highest-threshold row at or above six,
        # the largest index below i_op.
        below = [published_damage.index(x) for x in six
                 if published_damage.index(x) < i_op]
        if below:
            i_six = max(below)
            gap = abs(i_op - i_six)
            add("threshold at which the worst cluster first reaches six",
                "It first reaches six at %s"
                % f(damage_labels[published_damage[i_six]]["threshold"], 3))
            add("rows between the operating point and the first six",
                "%s rows %s the table"
                % (NUMBER_WORD.get(gap, str(gap)),
                   "up" if i_six < i_op else "down"))

    at10 = [d for d in e2["cluster_damage"]
            if "cost_optimal_10_to_1" in d["operating_point"]][0]
    c10 = e2["cost_optimal"]["10"]["cost_optimal"]
    add("precision at the operating point", "Precision is\n%s"
        % f(c10["precision"], 4))
    add("false share as a percentage in prose", "so %s percent of accepted"
        % pct(at10["false_pair_share_of_accepted"], 2))
    add("welded providers in prose", "But %s of the %s"
        % (n(at10["providers_in_a_welded_cluster"]),
           n(at10["providers_present"])))
    add("welded share as a percentage", "%s percent, sit in a cluster"
        % pct(at10["welded_provider_share"], 2))
    worst_loose = [d for d in e2["cluster_damage"] if d["threshold"] == -8.0][0]
    add("error factor between the operating point and -8",
        "factor of %.0f between the" % (worst_loose["false_pair_share_of_accepted"]
                                        / at10["false_pair_share_of_accepted"]))
    worst_20 = [d for d in e2["cluster_damage"] if d["threshold"] == -20.0][0]
    add("worst cluster at -20", "about %s different"
        % n(worst_20["most_providers_in_one_cluster"]))

    # the review band
    # The label is derived from the width (see width_label), not looked up in
    # a hand-written dict that could skip a band without saying so.
    published_bands = published_table_rows(readme, "Band width")
    band_labels = set()
    for b in e2["review_band"]["bands"]:
        w = b["band_width_fraction_of_score_range"]
        lab_ = width_label(w)
        band_labels.add(lab_)
        if lab_ not in published_bands:
            continue
        be = "n/a" if w == 0.0 else f(b["break_even_review_cost"], 4)
        add("band row %s" % lab_, "| %s | %s | %s | %s | %s |"
            % (lab_, n(b["review_queue_pairs"]),
               n(round(b["reviews_per_10000_providers"])),
               n(b["expected_cost"]), be))
    for lab_ in published_bands:
        if lab_ not in band_labels:
            orphans.append(
                "the review-band table publishes a row for %r and "
                "results/exp2_threshold.json has no band of that width" % lab_)
    narrow = [b for b in e2["review_band"]["bands"]
              if b["band_width_fraction_of_score_range"] == 0.02][0]
    ten = [b for b in e2["review_band"]["bands"]
           if b["band_width_fraction_of_score_range"] == 0.1][0]
    add("narrow band queue in prose", "puts %s pairs per 10,000"
        % n(narrow["review_queue_pairs"]))
    add("narrow band break-even in prose", "at most %s of one missed match"
        % f(narrow["break_even_review_cost"], 2))
    add("ten percent band in prose", "cost down to %s takes %s reviews"
        % (n(ten["expected_cost"]), n(ten["review_queue_pairs"])))

    # ---- experiment 3 ------------------------------------------------------
    field_label = [("npi", "NPI"), ("first_name", "first name"),
                   ("last_name", "last name"), ("credential", "credential"),
                   ("street", "street"), ("suite", "suite"),
                   ("city", "city"), ("state", "state"), ("zip", "ZIP"),
                   ("phone", "phone"), ("specialty", "specialty"),
                   ("network_status", "network status")]
    order = ["first_non_null", "most_recent", "majority_vote",
             "source_priority"]
    for key, label in field_label:
        add("survivorship row %s" % key, "| %s | %s |"
            % (label, " | ".join(f(e3["field_accuracy"][s][key], 4)
                                 for s in order)))
    add("survivorship mean row", "| **mean** | %s |"
        % " | ".join("**%s**" % f(e3["mean_accuracy"][s], 4) for s in order))
    add("clusters scored", n(e3["clusters_scored"]))
    add("welded clusters excluded", "The %s welded"
        % n(e3["clusters_skipped_as_welded"]))
    add("two-site providers", "Of the 20,000 providers, %s"
        % n(e3["providers_listed_twice_by_a_source"]))
    add("lineage fields checked", "%s\nfield values were checked and %s violated"
        % (n(e3["lineage_fields_checked"]), n(e3["lineage_violations"])))
    add("majority first name as a percentage",
        "right %s percent of the time"
        % pct(e3["field_accuracy"]["majority_vote"]["first_name"]))
    add("majority first name error in the summary", "wrong for %s percent"
        % pct(1 - e3["field_accuracy"]["majority_vote"]["first_name"]))
    add("priority beats majority on the mean", "on the mean by %s points"
        % f((e3["mean_accuracy"]["source_priority"]
             - e3["mean_accuracy"]["majority_vote"]) * 100, 1))
    ss = e3["field_accuracy_single_site_providers_only"]
    for key, label in [("first_name", "first name"), ("last_name", "last name"),
                       ("street", "street"), ("zip", "ZIP"),
                       ("phone", "phone")]:
        add("single-site row %s" % key, "| %s | %s | %s |"
            % (label, f(ss["majority_vote"][key], 4),
               f(ss["source_priority"][key], 4)))
    add("single-site mean row", "| **mean over all 12 fields** | **%s** | **%s** |"
        % (f(e3["mean_accuracy_single_site"]["majority_vote"], 4),
           f(e3["mean_accuracy_single_site"]["source_priority"], 4)))
    add("surname counter-example", "%s to %s, even among single-site"
        % (f(ss["majority_vote"]["last_name"], 4),
           f(ss["source_priority"]["last_name"], 4)))

    # ---- experiment 4 ------------------------------------------------------
    o = e4["overrides"]
    add("override counts", "%s decisions the pipeline could not: %s"
        % (n(o["total"]), n(o["split"])))
    add("merge and pin counts", "%s\nMERGES of pairs it wrongly rejected, and %s PINS"
        % (n(o["merge"]), n(o["pin"])))
    add("new rows", "%s new rows, taking %s to %s"
        % (n(e4["new_rows_in_second_ingest"]), n(e4["ingest1"]["rows"]),
           n(e4["ingest1_plus_2"]["rows"])))
    ci, nk = e4["replay"]["cluster_id"], e4["replay"]["natural_key"]
    add("cluster id replay row", "| on the derived cluster id | %s | %s | %s |"
        % (n(ci["retained"]), n(ci["lost"]), n(ci["misapplied"])))
    add("natural key replay row",
        "| on (source_system, source_row_id) | %s | %s | %s |"
        % (n(nk["retained"]), n(nk["lost"]), n(nk["misapplied"])))
    add("none dropped", "NOT ONE OF THE %s WAS DROPPED" % n(o["total"]))
    add("misapplied count in prose", "%s of\nthem, %s percent, were still being enforced"
        % (n(ci["misapplied"]), pct(ci["misapplied"] / float(o["total"]))))
    add("misapplied count repeated", "Every one of those %s landed"
        % n(ci["misapplied"]))
    add("retained count in prose", "The %s that survived" % n(ci["retained"]))
    add("retained share in prose", "right %s percent\nof the time by accident"
        % pct(ci["retained"] / float(o["total"])))
    add("misapplied in the summary", "And %s of %s human overrides"
        % (n(ci["misapplied"]), n(o["total"])))
    changed = e4["run1_clusters_with_changed_membership"]
    total_c = e4["ingest1"]["clusters"]
    renum = e4["run1_cluster_ids_no_longer_holding_their_original_set"]
    add("clusters that changed", "Only %s of the %s clusters, %s percent"
        % (n(changed), n(total_c), pct(changed / float(total_c))))
    add("clusters renumbered", "But %s of them, %s percent"
        % (n(renum), pct(renum / float(total_c))))
    # Both halves of that total, because some of those ids hold a different
    # member set and some hold no cluster at all, and the sentence says which.
    add("ids holding a different set",
        "%s of them hold a different member set"
        % n(e4["run1_cluster_ids_pointing_at_a_different_set"]))
    add("ids holding nothing",
        "%s hold no cluster at all"
        % n(e4["run1_cluster_ids_with_no_cluster_at_that_id"]))
    add("renumbering factor", "move %s times as many ids"
        % {2: "two", 3: "three", 4: "four", 5: "five"}[round(renum / changed)])
    add("change percentage in the summary", "only %s\npercent of clusters"
        % pct(changed / float(total_c)))
    # The worked examples are derived too. They are the most vivid thing in
    # section 4 and they are the only figures in the README that come from
    # cluster ids, which is exactly the quantity that stops being reproducible
    # the moment a query loses its ORDER BY.
    ex = e4["misapplied_examples"]
    # Provider ids are identifiers, not quantities, and are written without
    # thousands separators on both sides.
    # The leading article is left out: whether it is "A" or "a" depends on
    # where the sentence lands after reflow, and a checker that fails on line
    # wrapping is one a reader learns to ignore.
    add("first misapplied example", "split meant for provider %d was applied"
        % ex[0]["intended_provider"])
    add("first misapplied target", "to provider %d"
        % ex[0]["landed_on_provider"])
    add("second misapplied example", "one meant for %d\nto %d"
        % (ex[3]["intended_provider"], ex[3]["landed_on_provider"]))

    add("stale pins", "Of the %s pins, %s are contradicted"
        % (n(o["pin"]), n(e4["pins_contradicted_by_a_corrected_source_row"])))

    return want, orphans


def main():
    with open(README, encoding="utf-8") as fh:
        readme = fh.read()
    # Normalized on both sides so a reflowed paragraph is not a false alarm.
    # A checker that cries wolf on line wrapping is a checker a reader learns
    # to ignore, which is worse than not having one.
    flat = re.sub(r"\s+", " ", readme)

    want, orphans = build(readme)
    missing = []
    for label, s in want:
        if re.sub(r"\s+", " ", s) not in flat:
            missing.append((label, s))

    print("%d figures re-derived from results/*.json and checked against "
          "README.md" % len(want))
    if orphans:
        print()
        for o in orphans:
            print("NO EVIDENCE: %s" % o)
        print()
        print("%d published table row(s) have no results row behind them."
              % len(orphans))
        return 1
    if missing:
        print()
        for label, s in missing:
            print("MISSING (%s):" % label)
            print("    %s" % s)
        print()
        print("%d of %d figures are not in README.md verbatim."
              % (len(missing), len(want)))
        return 1
    print("all present")
    return 0


if __name__ == "__main__":
    sys.exit(main())
