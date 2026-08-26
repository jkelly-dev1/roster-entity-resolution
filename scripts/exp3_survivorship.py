"""EXPERIMENT 3: survivorship, and the golden record.

    python3 scripts/exp3_survivorship.py

A cluster is agreed. Which value wins, field by field?

Four strategies, scored as FIELD-LEVEL ACCURACY against the answer key:

  first_non_null   the naive baseline. Included because it is what ships when
                   nobody decides anything.
  most_recent      the newest source row wins.
  majority_vote    the most common non-null value wins, ties to most recent.
  source_priority  a per-FIELD priority list, not a per-source one.

Per-field priority is what this experiment measures. No source is best at
everything. The license board is right about credentials and legal names and
knows nothing about addresses. The clearinghouse always has the NPI, pushes
daily, and is the ONLY source carrying a stale address. The payer feed owns
network status. A single ranked list of sources cannot express that, and the
accuracy cost of pretending it can is what this experiment measures.

The prediction, recorded before the run: majority vote is the best general
strategy. Expect it REFUTED, and expect the sharpest case to be the GIVEN
NAME, where three sources carry the practice nickname and one carries the
legal name, so the majority is popular and wrong.

Every value written here carries its lineage. Roster.golden_field records the
source system, the source row and the rule for each field of each golden
record, and tests/test_survivorship.py::test_every_shipped_lineage_row_names_a_source_row_that_holds_its_value asserts that the value actually appears in
the row it names. That is the only check that catches a survivorship rule
which invents a value or carries one from the wrong row.
"""

import os
import sys
import time
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import lab
import normalize

PREDICTION = {
    "claim": "majority vote is the best general survivorship strategy, "
             "measured as mean field-level accuracy across all fields",
}

# The threshold experiment 2 chose at a 10:1 cost ratio. Stated as a constant
# rather than recomputed, and asserted against the results file below, so that
# this experiment cannot silently drift onto a different operating point than
# the one the README describes.
OPERATING_POINT = "cost_optimal_10_to_1"

RUN_ID = "exp3"

# The fields a golden record carries, and what the answer key calls each one.
FIELDS = [
    ("npi", "npi"),
    ("first_name", "first_name"),
    ("last_name", "last_name"),
    ("credential", "credential"),
    ("street", "street"),
    ("suite", "suite"),
    ("city", "city"),
    ("state", "state"),
    ("zip", "zip"),
    ("phone", "phone"),
    ("specialty", "specialty"),
    ("network_status", "network_status"),
]

# Per-field source priority. Each list is ordered best-first FOR THAT FIELD,
# and the differences between the lists are the entire content of the
# strategy. Three of them put the clearinghouse first and three put it last.
PRIORITY = {
    # Always present and always correct here.
    "npi": ["clearinghouse", "payer_feed", "license_board", "site_scrape"],
    # The licensing board is the only source that carries a legal first name.
    # The other three carry whatever the practice uses, so a majority of three
    # is a majority for the nickname.
    "first_name": ["license_board", "payer_feed", "clearinghouse",
                   "site_scrape"],
    # A legal surname change is registered with the board and reflected on the
    # practice site; the payer feed and the clearinghouse lag.
    "last_name": ["license_board", "site_scrape", "payer_feed",
                  "clearinghouse"],
    "credential": ["license_board", "payer_feed", "clearinghouse"],
    # The clearinghouse is last on every address field and first on the NPI.
    # It is the freshest file in the data and the only one with a stale
    # address, which is exactly the case a single ranked source list cannot
    # express.
    "street": ["payer_feed", "site_scrape", "clearinghouse"],
    "suite": ["payer_feed", "site_scrape", "clearinghouse"],
    "city": ["payer_feed", "site_scrape", "clearinghouse"],
    "state": ["license_board", "site_scrape", "clearinghouse", "payer_feed"],
    "zip": ["payer_feed", "site_scrape", "clearinghouse"],
    "phone": ["payer_feed", "site_scrape", "clearinghouse"],
    "specialty": ["license_board", "payer_feed", "clearinghouse",
                  "site_scrape"],
    # Only one source carries it at all.
    "network_status": ["payer_feed"],
}


# ---------------------------------------------------------------------------
# What a source row offers for a field
# ---------------------------------------------------------------------------

def offered(row, field, parsed_name):
    """The value a source row offers for one golden field, or None.

    Names come from the normalized parse, not from name_raw, because the four
    sources format them three different ways and a survivorship rule comparing
    "SILVA, BARB" with "Barb Silva" would find every cluster unanimous in
    disagreement.
    """
    if field == "first_name":
        return parsed_name[0]
    if field == "last_name":
        return parsed_name[1]
    v = row.get(field)
    if v is None:
        return None
    v = str(v).strip()
    if not v:
        return None
    # Addresses are compared in the folded form, on both sides. The sources
    # write STREET, ST and St. For the same word and the answer key writes
    # only one of them, so comparing raw text measures the abbreviation table
    # rather than the survivorship rule, and scores every strategy equally
    # badly, which reads as a finding about survivorship and is not one.
    if field == "street":
        street, folded = normalize.split_suite(v)
        return " ".join(normalize.street_tokens(street)) or None
    if field == "suite":
        return normalize.normalize_suite(v)
    if field in ("city", "state", "specialty", "credential",
                 "network_status"):
        return v.upper()
    if field == "phone":
        d = "".join(c for c in v if c.isdigit())
        return d if len(d) == 10 else None
    if field == "zip":
        d = "".join(c for c in v if c.isdigit())
        return d[:5] if len(d) >= 5 else None
    return v


def truth_value(p, field):
    v = p.get(field)
    if v is None:
        return None
    v = str(v).strip()
    if not v:
        return None
    if field == "street":
        return " ".join(normalize.street_tokens(v)) or None
    if field == "suite":
        return normalize.normalize_suite(v)
    if field in ("city", "state", "specialty", "credential",
                 "network_status", "first_name", "last_name"):
        return v.upper()
    return v


# ---------------------------------------------------------------------------
# THE FOUR STRATEGIES
# ---------------------------------------------------------------------------

def pick_first_non_null(cands):
    """cands is [(value, source_system, source_row_id, observed_at), ...] in
    the order the rows were read. The naive baseline."""
    for c in cands:
        if c[0] is not None:
            return c
    return None


def pick_most_recent(cands):
    best = None
    for c in cands:
        if c[0] is None:
            continue
        # Ties broken by source system then row id, so the rule is a function
        # of the data and not of dictionary ordering.
        key = (c[3], c[1], c[2])
        if best is None or key > (best[3], best[1], best[2]):
            best = c
    return best


def pick_majority(cands):
    """Most common non-null value; ties broken by recency.

    The winner is attributed to the most recent row that carries it, so the
    lineage points at a row that genuinely contains the published value. A
    majority vote has no single origin, and recording one arbitrarily would
    make the lineage test pass while saying something false.
    """
    counts = Counter(c[0] for c in cands if c[0] is not None)
    if not counts:
        return None
    top = max(counts.values())
    winners = {v for v, n in counts.items() if n == top}
    return pick_most_recent([c for c in cands if c[0] in winners])


def pick_source_priority(cands, field):
    order = PRIORITY.get(field, [])
    rank = {s: i for i, s in enumerate(order)}
    best = None
    for c in cands:
        if c[0] is None or c[1] not in rank:
            continue
        key = (rank[c[1]], -_date_key(c[3]), c[2])
        if best is None or key < best[0]:
            best = (key, c)
    if best is not None:
        return best[1]
    # Nothing the priority list knows about offered a value. Falling through
    # to most-recent rather than returning nothing: an empty golden field is a
    # worse answer than a value from an unranked source, and pretending the
    # list is exhaustive is how a priority scheme quietly loses fields.
    return pick_most_recent(cands)


def _date_key(d):
    return int(str(d).replace("-", "")) if d else 0


STRATEGIES = ["first_non_null", "most_recent", "majority_vote",
              "source_priority"]


def resolve(cands, field, strategy):
    if strategy == "first_non_null":
        return pick_first_non_null(cands)
    if strategy == "most_recent":
        return pick_most_recent(cands)
    if strategy == "majority_vote":
        return pick_majority(cands)
    return pick_source_priority(cands, field)


# ---------------------------------------------------------------------------

def main():
    t0 = time.time()

    exp2 = lab.read_result("exp2_threshold")
    dmg = [d for d in exp2["cluster_damage"]
           if OPERATING_POINT in d["operating_point"]]
    if not dmg:
        print("exp2_threshold.json has no %s operating point. Run "
              "scripts/exp2_threshold.py first." % OPERATING_POINT,
              file=sys.stderr)
        return 1
    threshold = dmg[0]["threshold"]
    print("clustering at the %s threshold %.3f" % (OPERATING_POINT, threshold))

    # The clusters come from the same code path experiment 2 measured, by
    # importing it rather than restating it. A second implementation of
    # connected components would be a second thing to keep correct, and the
    # two drifting apart would make every number here describe a clustering
    # the published damage figures never applied to.
    import exp2_threshold as exp2mod

    index, provider_of, multi, fields = exp2mod.load_rows()
    n_rows = len(fields)
    uf = exp2mod.Union(n_rows)

    weights = {f: {lv: exp2["weights"][f][lv] for lv in exp2["weights"][f]}
               for f in exp2["weights"]}
    accepted = 0
    for a_sys, a_id, b_sys, b_id in exp2mod.stream_pairs():
        ia, ib = index[(a_sys, a_id)], index[(b_sys, b_id)]
        vec = exp2mod.compare_vector(fields[ia], fields[ib])
        if exp2mod.score_of(vec, weights) >= threshold:
            uf.union(ia, ib)
            accepted += 1
    print("  accepted %d pairs in %.0fs" % (accepted, time.time() - t0))

    clusters = {}
    for r in range(n_rows):
        clusters.setdefault(uf.find(r), []).append(r)
    print("  %d clusters" % len(clusters))

    # ---- the source rows, in full ------------------------------------------
    raw = lab.query_json("""
        SELECT s.source_system, s.source_row_id, s.observed_at::text AS observed_at,
               s.npi, s.credential, s.street, s.suite, s.city, s.state, s.zip,
               s.phone, s.specialty, s.network_status,
               n.given_name, n.family_name
          FROM roster.source_row s
          JOIN roster.normalized_row n
            ON n.source_system = s.source_system
           AND n.source_row_id = s.source_row_id
    """)
    by_key = {(r["source_system"], r["source_row_id"]): r for r in raw}
    key_of = {v: k for k, v in index.items()}

    truth = {p["provider_id"]: p for p in lab.query_json(
        "SELECT * FROM truth.canonical_provider")}
    moved = {pid for pid, p in truth.items() if p["has_moved"]}

    # Providers a source lists twice at two practice locations. A single
    # golden address is the wrong data model for them and address accuracy is
    # reported separately with and without them, rather than blaming a
    # survivorship rule for a question that has two right answers.
    two_site = {r["provider_id"] for r in lab.query_json("""
        SELECT provider_id FROM truth.source_row_link
         GROUP BY provider_id, source_system
        HAVING count(*) > 1
    """)}
    print("  %d providers are listed twice by some source" % len(two_site))

    # ---- resolve every cluster with every strategy --------------------------
    correct = {s: {f: 0 for f, _ in FIELDS} for s in STRATEGIES}
    scored = {s: {f: 0 for f, _ in FIELDS} for s in STRATEGIES}
    correct_single_site = {s: {f: 0 for f, _ in FIELDS} for s in STRATEGIES}
    scored_single_site = {s: {f: 0 for f, _ in FIELDS} for s in STRATEGIES}
    lineage_rows = []

    for cid, (root, rows) in enumerate(sorted(clusters.items()), start=1):
        pids = {provider_of[r] for r in rows}
        # A welded cluster has no correct golden record and scoring one
        # against an arbitrary member's truth would credit or blame a
        # survivorship rule for a matching decision. Counted and skipped.
        if len(pids) != 1:
            continue
        pid = pids.pop()
        p = truth[pid]

        cands_by_field = {f: [] for f, _ in FIELDS}
        for r in sorted(rows):
            k = key_of[r]
            row = by_key[k]
            parsed = (row["given_name"], row["family_name"])
            for f, _ in FIELDS:
                cands_by_field[f].append(
                    (offered(row, f, parsed), k[0], k[1], row["observed_at"]))

        for f, tfield in FIELDS:
            want = truth_value(p, tfield)
            for strat in STRATEGIES:
                got = resolve(cands_by_field[f], f, strat)
                value = got[0] if got else None
                scored[strat][f] += 1
                hit = (value == want)
                if hit:
                    correct[strat][f] += 1
                if pid not in two_site:
                    scored_single_site[strat][f] += 1
                    if hit:
                        correct_single_site[strat][f] += 1
                if strat == "source_priority" and got is not None:
                    lineage_rows.append(
                        (RUN_ID, cid, f, value, got[1], got[2],
                         "source_priority"))

    accuracy = {s: {f: round(correct[s][f] / scored[s][f], 6)
                    if scored[s][f] else None for f, _ in FIELDS}
                for s in STRATEGIES}
    accuracy_single_site = {
        s: {f: round(correct_single_site[s][f] / scored_single_site[s][f], 6)
            if scored_single_site[s][f] else None for f, _ in FIELDS}
        for s in STRATEGIES}
    mean_acc = {s: round(sum(accuracy[s][f] for f, _ in FIELDS) / len(FIELDS), 6)
                for s in STRATEGIES}

    print()
    print("%-16s %s" % ("field", "  ".join("%-16s" % s for s in STRATEGIES)))
    for f, _ in FIELDS:
        print("%-16s %s" % (f, "  ".join("%-16.4f" % accuracy[s][f]
                                         for s in STRATEGIES)))
    print("%-16s %s" % ("MEAN", "  ".join("%-16.4f" % mean_acc[s]
                                          for s in STRATEGIES)))

    best = max(STRATEGIES, key=lambda s: mean_acc[s])
    held = best == "majority_vote"

    # ---- write the lineage --------------------------------------------------
    lab.psql("DELETE FROM roster.golden_field WHERE run_id = '%s';" % RUN_ID)
    lab.psql("DELETE FROM roster.cluster_member WHERE run_id = '%s';" % RUN_ID)
    import subprocess
    lines = []
    for run_id, cid, f, value, sys_, rid, rule in lineage_rows:
        lines.append("\t".join([run_id, str(cid), f,
                                "\\N" if value is None else value,
                                sys_, str(rid), rule]))
    p = subprocess.run(
        ["docker", "exec", "-i", lab.CONTAINER, "psql", "-v",
         "ON_ERROR_STOP=1", "-U", lab.DB_USER, "-d", lab.DB_NAME, "-c",
         "\\copy roster.golden_field (run_id, cluster_id, field, value,"
         " source_system, source_row_id, rule) FROM STDIN"],
        input="\n".join(lines).encode("utf-8"), capture_output=True)
    if p.returncode != 0:
        print(p.stderr.decode(), file=sys.stderr)
        return 1
    print()
    print("lineage: %s" % p.stdout.decode().strip())

    # ---- THE LINEAGE INVARIANT ---------------------------------------------
    #
    # Every value in a golden record must appear in the source row it names.
    # This is the only check that catches a survivorship rule which invents a
    # value or attributes one to the wrong row, and neither of those failures
    # changes an accuracy figure: a rule that returns the right value with the
    # wrong provenance scores identically to a correct one.
    #
    # Checked over every field written, not a sample. The sample below exists
    # so the offline test suite can re-check the same invariant without a
    # database.
    violations, checked = [], 0
    for run_id, cid, f, value, sys_, rid, rule in lineage_rows:
        row = by_key[(sys_, rid)]
        parsed = (row["given_name"], row["family_name"])
        checked += 1
        if offered(row, f, parsed) != value:
            violations.append({"cluster_id": cid, "field": f,
                               "claimed": value, "source_system": sys_,
                               "source_row_id": rid,
                               "actual": offered(row, f, parsed)})
    print("lineage invariant: %d field values checked, %d violation(s)"
          % (checked, len(violations)))
    if violations:
        for v in violations[:5]:
            print("  %s" % v, file=sys.stderr)
        return 1

    # A SHIPPED SAMPLE, so tests/test_survivorship.py::test_every_shipped_lineage_row_names_a_source_row_that_holds_its_value can assert the same invariant
    # with pytest alone. Deterministic: every 500th field written.
    sample = []
    for i in range(0, len(lineage_rows), 500):
        run_id, cid, f, value, sys_, rid, rule = lineage_rows[i]
        row = by_key[(sys_, rid)]
        sample.append({
            "cluster_id": cid, "field": f, "value": value,
            "source_system": sys_, "source_row_id": rid, "rule": rule,
            "source_row": {k: row[k] for k in
                           ("npi", "credential", "street", "suite", "city",
                            "state", "zip", "phone", "specialty",
                            "network_status", "given_name", "family_name")},
        })
    lab.write_result("exp3_lineage_sample",
                     {"note": "every 500th golden field written by "
                              "source_priority, with the source row it names",
                      "fields_checked_in_full": checked,
                      "violations_in_full": len(violations),
                      "sample": sample})
    print("wrote results/exp3_lineage_sample.json (%d rows)" % len(sample))

    payload = {
        "operating_point": OPERATING_POINT,
        "threshold": threshold,
        "clusters_total": len(clusters),
        "clusters_scored": scored[STRATEGIES[0]][FIELDS[0][0]],
        "clusters_skipped_as_welded":
            len(clusters) - scored[STRATEGIES[0]][FIELDS[0][0]],
        "providers_listed_twice_by_a_source": len(two_site),
        "providers_who_moved": len(moved),
        "strategies": STRATEGIES,
        "field_accuracy": accuracy,
        "field_accuracy_single_site_providers_only": accuracy_single_site,
        "mean_accuracy": mean_acc,
        "per_field_priority": PRIORITY,
        "golden_fields_written": len(lineage_rows),
        "lineage_fields_checked": checked,
        "lineage_violations": len(violations),
        # Where each strategy actually wins, over single-site providers only,
        # because a provider a source lists at two practice locations has no
        # single correct address and scoring one blames the survivorship rule
        # for a data model that cannot be right.
        "single_site_priority_beats_majority": sorted(
            f for f, _ in FIELDS
            if accuracy_single_site["source_priority"][f]
            > accuracy_single_site["majority_vote"][f]),
        "single_site_majority_beats_priority": sorted(
            f for f, _ in FIELDS
            if accuracy_single_site["majority_vote"][f]
            > accuracy_single_site["source_priority"][f]),
        "mean_accuracy_single_site": {
            s2: round(sum(accuracy_single_site[s2][f] for f, _ in FIELDS)
                      / len(FIELDS), 6) for s2 in STRATEGIES},
        "prediction": dict(PREDICTION, best_strategy=best,
                           mean_accuracy=mean_acc,
                           verdict="held" if held else "REFUTED"),
    }
    lab.write_result("exp3_survivorship", payload)
    print("prediction: %s (best is %s)" % (payload["prediction"]["verdict"],
                                           best))
    print("wrote results/exp3_survivorship.json  (%.0fs)"
          % (time.time() - t0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
