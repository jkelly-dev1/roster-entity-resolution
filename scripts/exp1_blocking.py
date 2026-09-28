"""EXPERIMENT 1: what blocking costs before any scoring runs.

    python3 scripts/exp1_blocking.py

Comparing every pair of 74,926 source rows is 2.8 billion comparisons.
Blocking cuts that down. The question nobody asks is what it throws away, and
a true pair dropped by the blocker can never be recovered. No threshold, no
model and no human reviewer downstream gets it back, because the pair is never
scored at all. Every recall figure in experiment 2 is bounded above by the
pair completeness measured here.

Three numbers per strategy:
  pair completeness   the share of TRUE pairs that survive blocking
  reduction ratio     the share of all possible pairs eliminated
  candidate pairs     the absolute number that then has to be scored

The prediction, recorded before the run: exact NPI blocking is sufficient on
its own, meaning it keeps at least 95 percent of true pairs. It is scored
against the measurement below and the verdict is written into the results file
whichever way it goes.
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import lab

PREDICTION = {
    "claim": "exact NPI blocking alone retains at least 95 percent of true "
             "pairs, so the other strategies are not needed",
    "threshold": 0.95,
}

# Each strategy is the ON clause of a self-join over roster.normalized_row.
# The ordering predicate is part of every one of them: without it each pair is
# emitted twice and joined to itself once, which inflates the candidate count
# by slightly more than a factor of two and silently changes every ratio.
#
# Every caller parenthesizes the strategy clause before appending this one.
# AND binds tighter than OR in SQL, so a strategy that is itself a
# disjunction, the union is, otherwise attaches the ordering predicate to its
# last branch alone and leaves the rest emitting both orderings of every pair.
ORDER_PRED = "(a.source_system, a.source_row_id) < (b.source_system, b.source_row_id)"

STRATEGIES = [
    ("npi_exact",
     "the strongest identifier in the data, where it is present at all",
     "a.npi = b.npi AND a.npi IS NOT NULL"),
    ("zip_surname4",
     "same ZIP and the first four characters of the surname",
     "a.zip = b.zip AND left(a.family_name, 4) = left(b.family_name, 4)"
     " AND a.zip IS NOT NULL AND a.family_name IS NOT NULL"),
    ("soundex_state",
     "surname soundex and state, which is the only strategy a row with no"
     " address can take part in",
     "a.family_soundex = b.family_soundex AND a.state = b.state"
     " AND a.family_soundex IS NOT NULL AND a.state IS NOT NULL"),
    ("phone_exact",
     "the practice telephone number, digits only",
     "a.phone = b.phone AND a.phone IS NOT NULL"),
]

UNION_OF = ["npi_exact", "zip_surname4", "soundex_state", "phone_exact"]

# Index names are schema-qualified everywhere. An index is created in the
# schema of its table, so `drop index if exists idx_norm_npi` resolves against
# the search path, does not find roster.idx_norm_npi, and does nothing while
# exiting 0. The before-and-after comparison below then measures the indexed
# plan twice and reports that the index changed nothing.
# Every query below runs against a working table, not against normalized_row.
# Experiments 1 to 3 measure the FIRST INGEST; experiment 4 needs the same
# blocking over the first and second together. Filtering by ingest batch
# inside each join would put the same predicate in six places and leave the
# published figures depending on which script ran last, which is exactly how
# results/exp1_blocking.json briefly came to describe 79,745 rows while the
# README described 74,926.
WORK = "roster.blocking_input"

INDEXES = [
    ("idx_blk_npi", WORK + " (npi)"),
    ("idx_blk_zip_fam", WORK + " (zip, left(family_name, 4))"),
    ("idx_blk_sdx_state", WORK + " (family_soundex, state)"),
    ("idx_blk_phone", WORK + " (phone)"),
]

# Create index refuses a schema-qualified name and DROP INDEX requires one
# here, so the two are not symmetrical. A new index is created in the
# schema of the table it indexes, so these all land in `roster`.
INDEX_SCHEMA = "roster"


def measure(name, on_clause):
    """Candidate pairs and how many of them are true, in one pass.

    Counted rather than materialized. Four strategies plus their union would
    write tens of millions of rows to measure four numbers, and the union is
    the only one experiment 2 actually needs on disk.
    """
    sql = """
        SELECT count(*) AS candidate_pairs,
               count(*) FILTER (WHERE la.provider_id = lb.provider_id)
                   AS true_pairs_found
          FROM roster.blocking_input a
          JOIN roster.blocking_input b
            ON (%s) AND %s
          JOIN truth.source_row_link la
            ON la.source_system = a.source_system
           AND la.source_row_id = a.source_row_id
          JOIN truth.source_row_link lb
            ON lb.source_system = b.source_system
           AND lb.source_row_id = b.source_row_id
    """ % (on_clause, ORDER_PRED)
    t0 = time.time()
    row = lab.query_json(sql)[0]
    row["seconds"] = round(time.time() - t0, 1)
    row["strategy"] = name
    # A strategy cannot find more true pairs than exist. It is arithmetically
    # impossible and therefore means the join emitted a pair more than once,
    # which no ratio downstream would look wrong enough to catch on its own.
    if row["true_pairs_found"] > row["candidate_pairs"]:
        raise AssertionError(
            "%s found %d true pairs among %d candidates"
            % (name, row["true_pairs_found"], row["candidate_pairs"]))
    return row


def explain(sql):
    """The plan text as psql prints it, header and row count stripped."""
    out = lab.psql("EXPLAIN (ANALYZE, BUFFERS, TIMING ON, COSTS ON, FORMAT TEXT)\n"
                   + sql, quiet=False)
    lines = []
    for l in out.split("\n"):
        s = l.rstrip()
        if not s.strip() or s.strip() == "QUERY PLAN" \
                or set(s.strip()) == {"-"} or s.strip().startswith("("):
            continue
        lines.append(s)
    return lines


def plan_summary(lines):
    """The plan's NODES, top down, and its execution time.

    A node is the first line or a line beginning with an arrow. Everything
    else in text format is detail attached to the node above it, Hash Cond,
    Buffers, I/O Timings, and a summary that reads those as nodes reports a
    plan shape that Postgres never produced. Matching on a list of known
    detail prefixes cannot work, because the list of them is not closed.
    """
    nodes, exec_ms = [], None
    for i, l in enumerate(lines):
        s = l.strip()
        if s.startswith("Execution Time:"):
            exec_ms = float(s.split(":", 1)[1].strip().split()[0])
            continue
        if s.startswith("->"):
            s = s[2:].strip()
        elif i != 0:
            continue
        if s.startswith(("Planning", "Execution", "Trigger")):
            continue
        nodes.append(s.split("  (")[0].split(" on ")[0].strip())
    return nodes, exec_ms


def count_blocking_indexes():
    return int(lab.scalar(
        "SELECT count(*) FROM pg_indexes WHERE schemaname = 'roster'"
        " AND indexname LIKE 'idx_blk_%';"))


def drop_indexes():
    for name, _ in INDEXES:
        lab.psql("DROP INDEX IF EXISTS %s.%s;" % (INDEX_SCHEMA, name))
    # Checked afterward. `drop index if exists` on a name it cannot
    # resolve exits 0 having done nothing, which is indistinguishable from
    # success and turns the whole before-and-after comparison into two
    # measurements of the same plan.
    left = count_blocking_indexes()
    if left:
        raise AssertionError(
            "%d blocking index(es) survived the drop; the un-indexed plans "
            "would be measured with an index in place" % left)


def create_indexes():
    for name, target in INDEXES:
        lab.psql("CREATE INDEX %s ON %s;" % (name, target))
    lab.psql("ANALYZE " + WORK + ";")
    made = count_blocking_indexes()
    if made != len(INDEXES):
        raise AssertionError("expected %d blocking indexes, found %d"
                             % (len(INDEXES), made))


# The incremental case is where an index actually earns its keep, and saying
# so requires measuring the case where it does not. A full-batch blocking join
# reads both sides of the table once whatever indexes exist, so the planner
# hashes it and a btree index changes nothing. A CORRECTION FILE is the other
# shape: fifty new rows looking for their candidates among 74,926 existing
# ones is a probe workload, and that is the plan the index changes.
INCREMENTAL_SIZES = [50, 1000]


def incremental_plan(n):
    sql = """
        SELECT count(*)
          FROM roster.incoming_row p
          JOIN roster.blocking_input n
            ON n.npi = p.npi
         WHERE p.npi IS NOT NULL
    """
    lab.psql("""
        DROP TABLE IF EXISTS roster.incoming_row;
        CREATE TABLE roster.incoming_row AS
        SELECT * FROM roster.blocking_input
         WHERE source_system = 'clearinghouse' AND source_row_id <= %d;
        ANALYZE roster.incoming_row;
    """ % n)
    return sql


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--batches", default="1",
                    help="comma-separated ingest batches to block over")
    ap.add_argument("--strategy", default="union",
                    help="name to store the materialized union pairs under")
    ap.add_argument("--no-result", action="store_true",
                    help="materialize the pairs but write no results file; "
                         "used to prepare experiment 4 without overwriting "
                         "the published first-ingest measurement")
    a = ap.parse_args()
    batch_list = ",".join(str(int(b)) for b in a.batches.split(","))

    lab.psql("""
        DROP TABLE IF EXISTS %s CASCADE;
        CREATE TABLE %s AS
        SELECT n.* FROM roster.normalized_row n
          JOIN roster.source_row s
            ON s.source_system = n.source_system
           AND s.source_row_id = n.source_row_id
         WHERE s.ingest_batch IN (%s);
        ANALYZE %s;
    """ % (WORK, WORK, batch_list, WORK))

    n_rows = int(lab.scalar("SELECT count(*) FROM %s;" % WORK))
    if n_rows == 0:
        print("No normalized rows for ingest batch(es) %s. Run "
              "scripts/normalize.py." % batch_list, file=sys.stderr)
        return 1
    print("ingest batch(es)   %10s" % batch_list)

    all_possible = n_rows * (n_rows - 1) // 2
    total_true = int(lab.scalar(
        "SELECT sum(k * (k - 1) / 2) FROM ("
        "  SELECT count(*) k FROM truth.source_row_link GROUP BY provider_id"
        ") s;"))

    print("source rows        %10d" % n_rows)
    print("all possible pairs %10d" % all_possible)
    print("true pairs         %10d" % total_true)
    print()

    print("dropping blocking indexes ...")
    drop_indexes()

    # ---- the plans, before and after the indexes exist ---------------------
    plans = {}
    full_sql = ("SELECT count(*) FROM roster.blocking_input a"
                " JOIN roster.blocking_input b ON a.npi = b.npi"
                " AND a.npi IS NOT NULL AND " + ORDER_PRED)

    lines = explain(full_sql)
    nodes, ms = plan_summary(lines)
    plans["full_batch_no_index"] = {"nodes": nodes, "exec_ms": ms,
                                    "plan": lines}
    print("full batch, no index   %8.0f ms   %s" % (ms, " / ".join(nodes[:3])))

    inc_plans_before = {}
    for size in INCREMENTAL_SIZES:
        sql = incremental_plan(size)
        lines = explain(sql)
        nodes, ms = plan_summary(lines)
        inc_plans_before[size] = {"nodes": nodes, "exec_ms": ms, "plan": lines}
        print("incremental %-5d no index %6.1f ms   %s"
              % (size, ms, " / ".join(nodes[:3])))

    print()
    print("creating blocking indexes ...")
    create_indexes()

    lines = explain(full_sql)
    nodes, ms = plan_summary(lines)
    plans["full_batch_with_index"] = {"nodes": nodes, "exec_ms": ms,
                                      "plan": lines}
    print("full batch, indexed    %8.0f ms   %s" % (ms, " / ".join(nodes[:3])))

    inc_plans_after = {}
    for size in INCREMENTAL_SIZES:
        sql = incremental_plan(size)
        lines = explain(sql)
        nodes, ms = plan_summary(lines)
        inc_plans_after[size] = {"nodes": nodes, "exec_ms": ms, "plan": lines}
        print("incremental %-5d indexed  %6.1f ms   %s"
              % (size, ms, " / ".join(nodes[:3])))
    print()

    # ---- the strategies ----------------------------------------------------
    def ratios(r, note):
        r["note"] = note
        # Pair completeness above 1 is not a bad score, it is a broken join,
        # the only symptom a duplicated pair produces that a reader cannot
        # rationalize.
        if r["true_pairs_found"] > total_true:
            raise AssertionError(
                "%s found %d true pairs; only %d exist"
                % (r["strategy"], r["true_pairs_found"], total_true))
        r["pair_completeness"] = round(r["true_pairs_found"] / total_true, 4)
        r["reduction_ratio"] = round(
            1.0 - r["candidate_pairs"] / all_possible, 6)
        r["precision_of_blocking"] = round(
            r["true_pairs_found"] / r["candidate_pairs"], 6) \
            if r["candidate_pairs"] else 0.0
        return r

    results = []
    for name, note, on_clause in STRATEGIES:
        r = ratios(measure(name, on_clause), note)
        results.append(r)
        print("%-14s pairs %10d  true %7d  completeness %.4f  reduction %.6f"
              % (name, r["candidate_pairs"], r["true_pairs_found"],
                 r["pair_completeness"], r["reduction_ratio"]))

    union_clause = " OR ".join(
        "(%s)" % c for n, _, c in STRATEGIES if n in UNION_OF)
    r = ratios(measure("union", union_clause), "any of the four above")
    results.append(r)
    print("%-14s pairs %10d  true %7d  completeness %.4f  reduction %.6f"
          % ("union", r["candidate_pairs"], r["true_pairs_found"],
             r["pair_completeness"], r["reduction_ratio"]))
    print()

    # ---- what each strategy can even see -----------------------------------
    reach = lab.query_json("""
        SELECT source_system,
               count(*)                                    AS rows,
               count(npi)                                  AS can_block_on_npi,
               count(zip)                                  AS can_block_on_zip,
               count(phone)                                AS can_block_on_phone,
               count(family_soundex)                       AS can_block_on_soundex
          FROM roster.blocking_input
         GROUP BY source_system
         ORDER BY source_system
    """)
    for row in reach:
        print("%-14s rows %6d  npi %6d  zip %6d  phone %6d  soundex %6d"
              % (row["source_system"], row["rows"], row["can_block_on_npi"],
                 row["can_block_on_zip"], row["can_block_on_phone"],
                 row["can_block_on_soundex"]))
    print()

    # ---- materialize the union, which experiment 2 scores ------------------
    print("materializing the union into roster.candidate_pair as '%s' ..."
          % a.strategy)
    lab.psql("DELETE FROM roster.candidate_pair WHERE strategy = '%s';"
             % a.strategy)
    lab.psql("""
        INSERT INTO roster.candidate_pair
             (strategy, a_system, a_row_id, b_system, b_row_id)
        SELECT '""" + a.strategy + """', a.source_system, a.source_row_id,
                        b.source_system, b.source_row_id
          FROM roster.blocking_input a
          JOIN roster.blocking_input b
            ON (%s) AND %s;
        ANALYZE roster.candidate_pair;
    """ % (union_clause, ORDER_PRED))
    stored = int(lab.scalar("SELECT count(*) FROM roster.candidate_pair"
                            " WHERE strategy = '%s';" % a.strategy))
    print("stored %d candidate pairs" % stored)

    npi_only = [r for r in results if r["strategy"] == "npi_exact"][0]
    held = npi_only["pair_completeness"] >= PREDICTION["threshold"]

    if a.no_result:
        print()
        print("--no-result: results/exp1_blocking.json left untouched")
        return 0

    payload = {
        "ingest_batches": batch_list,
        "source_rows": n_rows,
        "all_possible_pairs": all_possible,
        "true_pairs": total_true,
        "strategies": results,
        "blockable_by_source": reach,
        "stored_union_pairs": stored,
        "prediction": dict(PREDICTION,
                           measured=npi_only["pair_completeness"],
                           verdict="held" if held else "REFUTED"),
        "query_plans": {
            "full_batch_no_index": plans["full_batch_no_index"],
            "full_batch_with_index": plans["full_batch_with_index"],
            "incremental_no_index": {str(k): v
                                     for k, v in inc_plans_before.items()},
            "incremental_with_index": {str(k): v
                                       for k, v in inc_plans_after.items()},
        },
    }
    path = lab.write_result("exp1_blocking", payload)
    print()
    print("prediction: %s (measured %.4f against %.2f)"
          % (payload["prediction"]["verdict"], npi_only["pair_completeness"],
             PREDICTION["threshold"]))
    print("wrote %s" % os.path.relpath(path, lab.REPO))
    return 0


if __name__ == "__main__":
    sys.exit(main())
