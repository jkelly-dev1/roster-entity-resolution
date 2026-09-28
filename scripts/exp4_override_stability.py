"""EXPERIMENT 4: does a human override survive the next file?

    python3 scripts/exp4_override_stability.py

An operations specialist makes a decision the pipeline cannot:

  SPLIT   these two records are NOT the same provider, despite the score
  MERGE   these two ARE the same provider, despite the score
  PIN     this address is correct; ignore survivorship for this field

Then the next roster file arrives and the pipeline runs again.

The failure this measures: an override keyed on a DERIVED CLUSTER ID. Cluster
ids are assigned by the run. Re-run with new rows and the numbering shifts.
The override is then either silently dropped or, far worse, applied to the
wrong provider. A human decision, correctly made, now corrupting a record it
was never about. Nothing in the pipeline notices, and no test that only checks
match quality would ever catch it.

The comparison:
  keyed on cluster id                      the naive implementation
  keyed on (source_system, source_row_id)  stable natural keys

Both schemes are recorded for every override and both are replayed. What
matters is not that natural keys are better, that is obvious once stated, but
HOW MANY decisions each scheme loses and misapplies, because "a few would
shift" and "a third of them land on somebody else" are different engineering
problems.

The predictions, recorded before the run:
  A. Overrides survive re-ingest. Expect REFUTED for the cluster-id scheme.
  B. The misapplication count for the cluster-id scheme is non-zero.

Also measured: overrides that have gone stale. The operator pinned an address
because the clearinghouse was wrong about it; in the second file the
clearinghouse has caught up. A system that never revisits a human decision is
as broken as one that discards it, and the honest middle is to report how many
are now contradicted by the data rather than to pick a side.
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import lab

PREDICTIONS = {
    "overrides_survive_reingest": {
        "claim": "human overrides survive a re-ingest under both keying "
                 "schemes",
    },
    "cluster_id_keying_misapplies": {
        "claim": "keying an override on a cluster id applies at least one of "
                 "them to a provider it was never about",
    },
}

N_SPLITS = 200
N_MERGES = 200
N_PINS = 100


def cluster_run(threshold, weights, batches, strategy):
    """Cluster the rows from the given ingest batches. Returns the pieces the
    comparison needs: cluster id per row key, and members per cluster id.

    Cluster ids are assigned the way a pipeline would assign them; in order
    over the components found in this run. That is precisely what makes them
    unstable, and using a stable id here would measure a system nobody builds.
    """
    import exp2_threshold as exp2mod

    where = " AND s.ingest_batch IN (%s)" % ",".join(str(b) for b in batches)
    rows = lab.query_json("""
        SELECT n.source_system, n.source_row_id, n.npi, n.given_name,
               n.family_name, n.street_tokens, n.phone, n.zip, n.state,
               n.specialty, l.provider_id
          FROM roster.normalized_row n
          JOIN roster.source_row s
            ON s.source_system = n.source_system
           AND s.source_row_id = n.source_row_id
          JOIN truth.source_row_link l
            ON l.source_system = n.source_system
           AND l.source_row_id = n.source_row_id
         WHERE true""" + where + """
         ORDER BY n.source_system, n.source_row_id
    """)
    index, fields, provider_of, keys = {}, [], [], []
    for i, r in enumerate(rows):
        key = (r["source_system"], r["source_row_id"])
        index[key] = i
        keys.append(key)
        provider_of.append(r["provider_id"])
        fields.append({
            "npi": r["npi"], "given_name": r["given_name"],
            "family_name": r["family_name"],
            "street_tokens": r["street_tokens"] or [],
            "phone": r["phone"], "zip": r["zip"], "state": r["state"],
            "specialty": r["specialty"]})

    uf = exp2mod.Union(len(fields))
    pairs = lab.query_json("""
        SELECT c.a_system, c.a_row_id, c.b_system, c.b_row_id
          FROM roster.candidate_pair c
          JOIN roster.source_row sa
            ON sa.source_system = c.a_system AND sa.source_row_id = c.a_row_id
          JOIN roster.source_row sb
            ON sb.source_system = c.b_system AND sb.source_row_id = c.b_row_id
         WHERE c.strategy = '%s'
           AND sa.ingest_batch IN (%s) AND sb.ingest_batch IN (%s)
         ORDER BY c.a_system, c.a_row_id, c.b_system, c.b_row_id
         -- THE ORDERING DECIDES THE CLUSTER IDS AND THEREFORE THE HEADLINE.
         -- Without it Postgres may return the pairs in any order, union-find
         -- assigns different ids, and the cluster_id replay moves away from
         -- the recorded 229 retained / 271 misapplied, which is the
         -- section's headline. test_results_invariants.py pins that split,
         -- so a re-run that changed it fails there.
    """ % (strategy, ",".join(str(b) for b in batches),
           ",".join(str(b) for b in batches)))

    accepted = []
    for p in pairs:
        ia = index[(p["a_system"], p["a_row_id"])]
        ib = index[(p["b_system"], p["b_row_id"])]
        vec = exp2mod.compare_vector(fields[ia], fields[ib])
        score = exp2mod.score_of(vec, weights)
        if score >= threshold:
            uf.union(ia, ib)
            accepted.append((keys[ia], keys[ib], score))

    roots = {}
    for i in range(len(fields)):
        roots.setdefault(uf.find(i), []).append(i)
    cluster_of, members = {}, {}
    for cid, (_, rows_i) in enumerate(sorted(roots.items()), start=1):
        members[cid] = frozenset(keys[i] for i in rows_i)
        for i in rows_i:
            cluster_of[keys[i]] = cid

    scored = {}
    for ka, kb, sc in accepted:
        scored[(ka, kb)] = sc
    return {"cluster_of": cluster_of, "members": members,
            "provider_of": {keys[i]: provider_of[i]
                            for i in range(len(fields))},
            "index": index, "fields": fields, "keys": keys,
            "accepted": scored, "n_rows": len(fields)}


def build_overrides(run1, weights, threshold):
    """The decisions an operator makes after looking at run 1.

    The operator is right. Splits are taken from pairs the resolver accepted
    that the answer key says are different providers, and merges from true
    pairs it rejected, so every override here is a correction rather than a
    preference. That is deliberate: the experiment is about whether a CORRECT
    human decision survives, and mixing in wrong ones would confound losing a
    decision with the decision having been bad.
    """
    prov = run1["provider_of"]
    splits, merges, pins = [], [], []

    for (ka, kb), score in sorted(run1["accepted"].items()):
        if len(splits) >= N_SPLITS:
            break
        if prov[ka] != prov[kb]:
            splits.append({"kind": "split", "a": ka, "b": kb,
                           "score": round(score, 3)})

    # Merges: true pairs among the candidates that scored BELOW the threshold.
    import exp2_threshold as exp2mod
    cand = lab.query_json("""
        SELECT c.a_system, c.a_row_id, c.b_system, c.b_row_id
          FROM roster.candidate_pair c
          JOIN roster.source_row sa
            ON sa.source_system = c.a_system AND sa.source_row_id = c.a_row_id
          JOIN roster.source_row sb
            ON sb.source_system = c.b_system AND sb.source_row_id = c.b_row_id
         WHERE c.strategy = 'union'
           AND sa.ingest_batch = 1 AND sb.ingest_batch = 1
         ORDER BY c.a_system, c.a_row_id, c.b_system, c.b_row_id
    """)
    idx, fields = run1["index"], run1["fields"]
    for p in cand:
        if len(merges) >= N_MERGES:
            break
        ka = (p["a_system"], p["a_row_id"])
        kb = (p["b_system"], p["b_row_id"])
        if prov[ka] != prov[kb]:
            continue
        if (ka, kb) in run1["accepted"]:
            continue
        vec = exp2mod.compare_vector(fields[idx[ka]], fields[idx[kb]])
        merges.append({"kind": "merge", "a": ka, "b": kb,
                       "score": round(exp2mod.score_of(vec, weights), 3)})

    # Pins: the operator fixes the address on a provider the clearinghouse has
    # stale. These are the ones that can go STALE when the source catches up.
    movers = lab.query_json("""
        SELECT l.source_system, l.source_row_id, p.provider_id, p.street
          FROM truth.source_row_link l
          JOIN truth.canonical_provider p ON p.provider_id = l.provider_id
          JOIN roster.source_row s
            ON s.source_system = l.source_system
           AND s.source_row_id = l.source_row_id
         WHERE p.has_moved AND l.source_system = 'clearinghouse'
           AND s.ingest_batch = 1
         ORDER BY l.source_row_id
         LIMIT %d
    """ % N_PINS)
    for m in movers:
        pins.append({"kind": "pin", "a": (m["source_system"],
                                          m["source_row_id"]),
                     "b": None, "field": "street", "value": m["street"],
                     "provider_id": m["provider_id"]})

    overrides = splits + merges + pins
    for o in overrides:
        # Both keys are recorded at creation. The cluster id is what the naive
        # implementation stores; the row key is what the stable one stores.
        # Recording both is the only way to replay the same decisions through
        # both schemes instead of comparing two different sets of decisions.
        o["cluster_id_at_creation"] = run1["cluster_of"][o["a"]]
    return overrides


def replay(overrides, run1, run2):
    """Apply every override to run 2 under both keying schemes."""
    # natural-key misapplication is structurally impossible, not measured zero.
    # A natural key names a specific source row, so on replay it either
    # resolves to that row or does not resolve at all; there is no third
    # outcome where it lands on a DIFFERENT provider, which is what
    # "misapplied" counts. The counter below is therefore never incremented
    # for natural_key, and its zero is a statement about the scheme rather
    # than a result from this run. It is kept so both schemes have the same
    # shape in the payload, and named here so the zero is not read as
    # evidence.
    #
    # `lost` is structural too, in this experiment. Run 2 is clustered over
    # batches 1 AND 2, so every batch-1 row is in its key set by the query
    # that loads it, and a natural key cannot fail to resolve. A feed that
    # retired batch-1 rows is not modeled here, so nothing in this run says
    # what natural keys would lose against one.
    out = {"cluster_id": {"retained": 0, "lost": 0, "misapplied": 0,
                          "misapplied_to_unrelated_cluster": 0},
           "natural_key": {"retained": 0, "lost": 0, "misapplied": 0,
                           "misapplied_to_unrelated_cluster": 0}}
    misapplied_examples = []

    for o in overrides:
        ka = o["a"]
        cid = o["cluster_id_at_creation"]

        # ---- scheme A: the override names a cluster id -----------------
        target = run2["members"].get(cid)
        if target is None:
            out["cluster_id"]["lost"] += 1
        elif ka in target:
            out["cluster_id"]["retained"] += 1
        else:
            # The number that matters. The cluster with that id still exists
            # and is about a DIFFERENT PROVIDER, so the operator's decision is
            # now being applied to a record they never saw.
            out["cluster_id"]["misapplied"] += 1
            # Unrelated, as opposed to shifted. If the cluster now sitting at
            # that id shares no row at all with the one the operator looked
            # at, the decision has not drifted; it has been transplanted
            # onto a different provider entirely.
            original = run1["members"][cid]
            if not (target & original):
                out["cluster_id"]["misapplied_to_unrelated_cluster"] += 1
            if len(misapplied_examples) < 5:
                landed = sorted(target)[0]
                misapplied_examples.append({
                    "kind": o["kind"],
                    "cluster_id": cid,
                    "intended_provider": run1["provider_of"][ka],
                    "landed_on_provider": run2["provider_of"][landed],
                    "shares_no_row_with_the_original": not (target & original),
                })

        # ---- scheme B: the override names source rows ------------------
        if ka not in run2["cluster_of"]:
            out["natural_key"]["lost"] += 1
        else:
            out["natural_key"]["retained"] += 1

    return out, misapplied_examples


def main():
    t0 = time.time()
    exp2 = lab.read_result("exp2_threshold")
    weights = exp2["weights"]
    dmg = [d for d in exp2["cluster_damage"]
           if "cost_optimal_10_to_1" in d["operating_point"]]
    threshold = dmg[0]["threshold"]

    n2 = int(lab.scalar("SELECT count(*) FROM roster.source_row"
                        " WHERE ingest_batch = 2;"))
    b12 = int(lab.scalar("SELECT count(*) FROM roster.candidate_pair"
                         " WHERE strategy = 'union_b12';"))
    if n2 == 0 or b12 == 0:
        print("The second ingest is not prepared. Run, in order:\n"
              "    python3 scripts/load.py --batch2\n"
              "    python3 scripts/normalize.py --batch 2\n"
              "    python3 scripts/exp1_blocking.py --batches 1,2"
              " --strategy union_b12 --no-result\n"
              "The last one materializes the candidate pairs over both\n"
              "ingests WITHOUT overwriting the published first-ingest\n"
              "measurement in results/exp1_blocking.json.",
              file=sys.stderr)
        return 1

    print("ingest 1 only ...", flush=True)
    run1 = cluster_run(threshold, weights, [1], "union")
    print("  %d rows, %d clusters" % (run1["n_rows"], len(run1["members"])))

    print("building overrides from what run 1 got wrong ...")
    overrides = build_overrides(run1, weights, threshold)
    kinds = {}
    for o in overrides:
        kinds[o["kind"]] = kinds.get(o["kind"], 0) + 1
    print("  %s" % ", ".join("%d %s" % (v, k) for k, v in sorted(kinds.items())))

    print("ingest 1 + 2 ...", flush=True)
    run2 = cluster_run(threshold, weights, [1, 2], "union_b12")
    print("  %d rows, %d clusters" % (run2["n_rows"], len(run2["members"])))

    # How much the clustering actually moved, compared by MEMBER SET and not
    # by cluster id. Comparing run1[cid] against run2[cid] measures the id
    # renumbering, which is the thing under test, and would report almost
    # every cluster as changed no matter what happened to the data. The
    # question here is the other one: how many clusters genuinely gained or
    # lost a row.
    run2_sets = set(run2["members"].values())
    unchanged = sum(1 for mem in run1["members"].values() if mem in run2_sets)
    shifted = len(run1["members"]) - unchanged

    # How many cluster ids no longer hold their original set is the
    # renumbering itself, stated separately so the two cannot be confused for
    # each other.
    #
    # Split in two, because "a different set sits at the old id" and "nothing
    # sits at the old id" are not the same sentence. The second run has fewer
    # clusters than the first, so the highest ids of run 1 have no counterpart
    # at all: `run2["members"].get(cid)` is None for those, which is != mem
    # and would otherwise count as a different member set. The total is the
    # headline (the id no longer holds what it held), and the two parts are
    # what the prose may say.
    id_different = id_absent = 0
    for cid, mem in run1["members"].items():
        other = run2["members"].get(cid)
        if other is None:
            id_absent += 1
        elif other != mem:
            id_different += 1
    id_moved = id_different + id_absent

    result, examples = replay(overrides, run1, run2)

    # ---- overrides that have gone stale -------------------------------------
    # The operator pinned an address the clearinghouse had wrong. In the second
    # file the clearinghouse issued a corrected row. The pin is still applied,
    # still keyed correctly, and NO LONGER NECESSARY, and if the truth had
    # moved on instead, it would now be wrong.
    stale = 0
    for o in overrides:
        if o["kind"] != "pin":
            continue
        n = int(lab.scalar("""
            SELECT count(*) FROM roster.source_row s
              JOIN truth.source_row_link l
                ON l.source_system = s.source_system
               AND l.source_row_id = s.source_row_id
             WHERE s.ingest_batch = 2 AND s.source_system = 'clearinghouse'
               AND l.provider_id = %d;""" % o["provider_id"]))
        if n:
            stale += 1

    print()
    print("%-14s %10s %10s %12s" % ("scheme", "retained", "lost", "misapplied"))
    for scheme in ("cluster_id", "natural_key"):
        r = result[scheme]
        print("%-14s %10d %10d %12d"
              % (scheme, r["retained"], r["lost"], r["misapplied"]))
    print()
    print("run 1 clusters that genuinely gained or lost a row: %d of %d"
          % (shifted, len(run1["members"])))
    print("run 1 cluster IDS no longer holding their original set: %d of %d"
          % (id_moved, len(run1["members"])))
    print("  a DIFFERENT set now sits at that id: %d" % id_different)
    print("  NO cluster exists at that id at all:  %d" % id_absent)
    print("misapplied onto a cluster sharing no row with the original: %d"
          % result["cluster_id"]["misapplied_to_unrelated_cluster"])
    print("pins now contradicted by a corrected source row: %d of %d"
          % (stale, kinds.get("pin", 0)))
    for e in examples:
        print("  a %s meant for provider %d landed on provider %d"
              % (e["kind"], e["intended_provider"], e["landed_on_provider"]))

    pred_a_held = (result["cluster_id"]["lost"] == 0
                   and result["cluster_id"]["misapplied"] == 0
                   and result["natural_key"]["lost"] == 0)
    pred_b_held = result["cluster_id"]["misapplied"] > 0

    payload = {
        "threshold": threshold,
        "overrides": {"split": kinds.get("split", 0),
                      "merge": kinds.get("merge", 0),
                      "pin": kinds.get("pin", 0),
                      "total": len(overrides)},
        "ingest1": {"rows": run1["n_rows"], "clusters": len(run1["members"])},
        "ingest1_plus_2": {"rows": run2["n_rows"],
                           "clusters": len(run2["members"])},
        "new_rows_in_second_ingest": n2,
        "run1_clusters_with_changed_membership": shifted,
        "run1_cluster_ids_no_longer_holding_their_original_set": id_moved,
        "run1_cluster_ids_pointing_at_a_different_set": id_different,
        "run1_cluster_ids_with_no_cluster_at_that_id": id_absent,
        "replay": result,
        "misapplied_examples": examples,
        "pins_contradicted_by_a_corrected_source_row": stale,
        "predictions": {
            "overrides_survive_reingest": dict(
                PREDICTIONS["overrides_survive_reingest"],
                verdict="held" if pred_a_held else "REFUTED"),
            "cluster_id_keying_misapplies": dict(
                PREDICTIONS["cluster_id_keying_misapplies"],
                misapplied=result["cluster_id"]["misapplied"],
                verdict="held" if pred_b_held else "REFUTED"),
        },
    }
    lab.write_result("exp4_override_stability", payload)
    print()
    print("prediction A (overrides survive): %s"
          % payload["predictions"]["overrides_survive_reingest"]["verdict"])
    print("prediction B (cluster-id keying misapplies): %s"
          % payload["predictions"]["cluster_id_keying_misapplies"]["verdict"])
    print("wrote results/exp4_override_stability.json  (%.0fs)"
          % (time.time() - t0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
