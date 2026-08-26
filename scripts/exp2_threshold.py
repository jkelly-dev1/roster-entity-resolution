"""EXPERIMENT 2: the threshold, priced.

    python3 scripts/exp2_threshold.py

This is the reason the repository exists. A matching threshold is not a tuning
parameter, it is a COST DECISION, and the same data defends a different
threshold once you say what a wrong merge costs.

  A FALSE MATCH merges two different providers. Members are told an
  out-of-network provider is covered, and are billed for it.
  A MISSED MATCH leaves a duplicate. The directory shows the same doctor
  twice, and coverage can be denied that should have been approved.

Those are not the same cost, and this repository does not claim to know the
real ratio. It sweeps it: 1:1, 3:1, 10:1 and 30:1, and reports how far the
best threshold moves.

Four things are measured here:
  1. Fellegi-Sunter weights, fit on one half of the providers and reported
     from the other.
  2. The cost-optimal threshold at each ratio, against the F1-optimal one.
  3. What a two-threshold review band buys, and where widening it stops paying.
  4. CLUSTER DAMAGE. A false pair does not cost one error: connected
     components weld two whole providers together, so one bad link can merge
     eleven rows about two different doctors. That is the number a pairwise
     precision figure hides.

Missed matches include the pairs blocking never emitted. A true pair that
experiment 1 dropped is a missed match, not an absent one, and counting recall
only over scored pairs would report a number no operator could ever obtain.

The predictions, recorded before the run:
  A. The F1-optimal threshold is NOT the cost-optimal one at 10:1; choosing by
     F1 costs measurably more.
  B. Cluster damage is worse than pairwise precision suggests: the share of
     providers caught up in a welded cluster exceeds the false pair rate.
Both are scored against the measurement and written out whichever way they go.
"""

import os
import sys
import time
from array import array

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import compare
import lab
import normalize

PREDICTIONS = {
    "f1_is_not_cost_optimal": {
        "claim": "at a 10:1 cost ratio the F1-optimal threshold is not the "
                 "cost-optimal one, and choosing by F1 costs more",
    },
    "cluster_damage_exceeds_pair_error": {
        "claim": "the share of providers caught up in a welded cluster is "
                 "larger than the share of accepted pairs that are false",
    },
}

COST_RATIOS = [1, 3, 10, 30]

# Laplace smoothing on the m and u counts. A level that never occurs among
# matches would otherwise give log(0) and make one field decide every pair.
SMOOTHING = 0.5


# ---------------------------------------------------------------------------
# LOADING
# ---------------------------------------------------------------------------

def load_rows():
    """Every normalized row, and the provider the answer key assigns it.

    The truth is loaded once, here, and only to label and to score. Nothing
    downstream passes a provider id into a comparator or a threshold.
    """
    rows = lab.query_json("""
        SELECT n.source_system, n.source_row_id, n.npi, n.given_name,
               n.family_name, n.street_tokens, n.phone, n.zip, n.state,
               n.specialty, l.provider_id, l.multi_provider
          FROM roster.normalized_row n
          JOIN truth.source_row_link l
            ON l.source_system = n.source_system
           AND l.source_row_id = n.source_row_id
         ORDER BY n.source_system, n.source_row_id
    """)
    index, provider_of, multi = {}, array("i"), bytearray()
    fields = []
    for i, r in enumerate(rows):
        index[(r["source_system"], r["source_row_id"])] = i
        provider_of.append(r["provider_id"])
        multi.append(1 if r["multi_provider"] else 0)
        fields.append({
            "npi": r["npi"], "given_name": r["given_name"],
            "family_name": r["family_name"],
            "street_tokens": r["street_tokens"] or [],
            "phone": r["phone"], "zip": r["zip"], "state": r["state"],
            "specialty": r["specialty"],
        })
    return index, provider_of, multi, fields


def stream_pairs(strategy="union"):
    """The union candidate pairs, streamed rather than materialized in Python.

    Three and a half million pairs as a list of dicts is several gigabytes of
    interpreter objects to answer a question that needs four integers per pair.
    """
    import subprocess
    # Ordered, and it has to be. Union-find membership does not depend on the
    # order pairs arrive in, but which node becomes the root does, and the
    # cluster ids assigned from those roots therefore do too. Without this
    # clause Postgres is free to return the pairs differently between runs and
    # every published cluster id becomes irreproducible while every count
    # stays identical, which is the hardest kind of irreproducibility to
    # notice.
    cmd = ("\\copy (SELECT a_system, a_row_id, b_system, b_row_id"
           " FROM roster.candidate_pair WHERE strategy = %s"
           " ORDER BY a_system, a_row_id, b_system, b_row_id)"
           " TO STDOUT WITH (FORMAT text)" % ("'" + strategy + "'"))
    p = subprocess.Popen(
        ["docker", "exec", "-i", lab.CONTAINER, "psql", "-v",
         "ON_ERROR_STOP=1", "-U", lab.DB_USER, "-d", lab.DB_NAME, "-c", cmd],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    for line in p.stdout:
        a_sys, a_id, b_sys, b_id = line.rstrip("\n").split("\t")
        yield a_sys, int(a_id), b_sys, int(b_id)
    p.stdout.close()
    err = p.stderr.read()
    if p.wait() != 0:
        raise lab.PsqlError(err.strip())


# ---------------------------------------------------------------------------
# SCORING
# ---------------------------------------------------------------------------

# MEMOIZED because the inputs repeat, not to cut a corner. Sixty-two given
# names and ninety-odd surnames generate the overwhelming majority of the
# string comparisons in three and a half million pairs, so the cache turns a
# quadratic string algorithm into a dictionary lookup on almost every call and
# changes no result.
_jw_cache = {}


def jw(a, b):
    key = (a, b)
    v = _jw_cache.get(key)
    if v is None:
        v = compare.jaro_winkler(a, b)
        _jw_cache[key] = v
    return v


def compare_vector(fa, fb):
    """compare.compare_pair, with the two string comparators memoized."""
    ga, gb = fa["given_name"], fb["given_name"]
    # Call the comparators rather than restating them. Tests/test_comparators.py
    # exercises compare.cmp_given and compare.cmp_family against published
    # Jaro-Winkler values, so the cut-offs are guarded there. A second copy of
    # the same rule written out here would be free to drift from the tested one,
    # and the copy the pipeline runs decides every published number: moving
    # these cut-offs shifts the 10:1 threshold and the count of false pairs
    # accepted.
    given = compare.cmp_given(ga, gb, canonical=normalize.canonical_given)
    family = compare.cmp_family(fa["family_name"], fb["family_name"])

    return {
        "npi": compare.cmp_npi(fa["npi"], fb["npi"]),
        "given_name": given,
        "family_name": family,
        "street": compare.cmp_street(fa["street_tokens"], fb["street_tokens"]),
        "phone": compare.cmp_exact(fa["phone"], fb["phone"]),
        "zip": compare.cmp_exact(fa["zip"], fb["zip"]),
        "state": compare.cmp_exact(fa["state"], fb["state"]),
        "specialty": compare.cmp_exact(fa["specialty"], fb["specialty"]),
    }


def fit_weights(counts_m, counts_u, n_m, n_u):
    """log2(m / u) for every field and level.

    Smoothed on both sides. An unsmoothed u of zero is the dangerous one: it
    makes a single field's agreement worth infinite evidence, and every pair
    showing it lands above any threshold no matter what the other seven fields
    say.
    """
    weights = {}
    for field in compare.FIELDS:
        weights[field] = {}
        k = len(compare.LEVELS)
        for level in compare.LEVELS:
            m = (counts_m[field].get(level, 0) + SMOOTHING) / (
                n_m + SMOOTHING * k)
            u = (counts_u[field].get(level, 0) + SMOOTHING) / (
                n_u + SMOOTHING * k)
            import math
            weights[field][level] = math.log(m / u, 2)
    return weights


def score_of(vec, weights):
    return sum(weights[f][vec[f]] for f in compare.FIELDS)


# ---------------------------------------------------------------------------
# CLUSTERING
# ---------------------------------------------------------------------------

class Union:
    """Union-find over source rows.

    Connected components are what this section computes. A resolver does not
    ship pairwise decisions, it ships clusters, and the transitive closure is
    where one wrong pair stops being one wrong answer.
    """

    def __init__(self, n):
        self.parent = list(range(n))
        self.rank = bytearray(n)

    def find(self, x):
        p = self.parent
        while p[x] != x:
            p[x] = p[p[x]]
            x = p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self.rank[ra] < self.rank[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        if self.rank[ra] == self.rank[rb]:
            self.rank[ra] += 1


def cluster_damage(a_idx, b_idx, scores, labels, threshold, provider_of,
                   n_rows, eval_row):
    """What the transitive closure does at one threshold.

    Reported over the EVALUATION half only, so it is comparable with every
    other figure in this experiment. The pairwise counts are recomputed here
    rather than looked up, so that this curve can be evaluated at thresholds
    the precision-recall grid does not happen to contain.
    """
    uf = Union(n_rows)
    tp = fp = 0
    for i in range(len(scores)):
        if scores[i] >= threshold:
            uf.union(a_idx[i], b_idx[i])
            if labels[i]:
                tp += 1
            else:
                fp += 1

    members = {}
    for r in range(n_rows):
        if not eval_row[r]:
            continue
        members.setdefault(uf.find(r), []).append(r)

    welded_clusters = 0
    providers_in_welded = set()
    rows_in_welded = 0
    provider_clusters = {}
    for root, rows in members.items():
        pids = {provider_of[r] for r in rows}
        if len(pids) > 1:
            welded_clusters += 1
            providers_in_welded |= pids
            rows_in_welded += len(rows)
        for pid in pids:
            provider_clusters.setdefault(pid, set()).add(root)

    fragmented = sum(1 for pid, cs in provider_clusters.items() if len(cs) > 1)
    largest = max((len({provider_of[r] for r in rows})
                   for rows in members.values()), default=0)

    return {
        "threshold": round(threshold, 3),
        "accepted_pairs": tp + fp,
        "accepted_true": tp,
        "accepted_false": fp,
        "false_pair_share_of_accepted": round(fp / (tp + fp), 6)
        if tp + fp else 0.0,
        "clusters": len(members),
        "providers_present": len(provider_clusters),
        "welded_clusters": welded_clusters,
        "providers_in_a_welded_cluster": len(providers_in_welded),
        "rows_in_a_welded_cluster": rows_in_welded,
        "most_providers_in_one_cluster": largest,
        "providers_split_across_clusters": fragmented,
    }


# ---------------------------------------------------------------------------
# THE SWEEP
# ---------------------------------------------------------------------------

def sweep(scores, labels, total_true_eval, grid):
    """precision, recall, F1 and the confusion counts at every threshold.

    False negatives include the true pairs blocking never emitted. Total_true_
    eval counts every true pair among evaluation providers, whether or not it
    reached a comparator, so recall here is recall against the data rather than
    against the candidate list.
    """
    # the grid is walked from the highest threshold downward, and that is not
    # a stylistic choice. Tp and fp are a running total of everything accepted
    # so far and can only grow, so a grid walked upward accepts every pair at
    # the first and lowest threshold and then reports those same counts for
    # every threshold after it. The result looks like a curve and is one flat
    # line at the accept-everything point.
    order = sorted(range(len(scores)), key=lambda i: -scores[i])
    out = []
    tp = fp = 0
    k = 0
    for t in sorted(grid, reverse=True):
        while k < len(order) and scores[order[k]] >= t:
            if labels[order[k]]:
                tp += 1
            else:
                fp += 1
            k += 1
        fn = total_true_eval - tp
        precision = tp / (tp + fp) if tp + fp else 1.0
        recall = tp / total_true_eval if total_true_eval else 0.0
        f1 = (2 * precision * recall / (precision + recall)
              if precision + recall else 0.0)
        out.append({"threshold": round(t, 3), "tp": tp, "fp": fp, "fn": fn,
                    "precision": round(precision, 6),
                    "recall": round(recall, 6), "f1": round(f1, 6)})
    out.reverse()                      # Ascending threshold, for reading
    # recall must not decrease as the threshold falls. If it does, the
    # accumulator was walked in the wrong direction and every row is the same
    # row, which still renders as a plausible table.
    for i in range(1, len(out)):
        if out[i]["recall"] > out[i - 1]["recall"] + 1e-9:
            raise AssertionError(
                "recall rose from %.6f to %.6f as the threshold rose from "
                "%.3f to %.3f" % (out[i - 1]["recall"], out[i]["recall"],
                                  out[i - 1]["threshold"], out[i]["threshold"]))
    return out


def main():
    t_start = time.time()
    print("loading rows ...", flush=True)
    index, provider_of, multi, fields = load_rows()
    n_rows = len(fields)
    print("  %d normalized rows" % n_rows)

    # The split is by provider, not by pair. The m probabilities are estimated
    # from true pairs, so a provider whose pairs appear in both halves leaks
    # the answer directly into the weights that are then scored against it.
    # Both rows of a true pair always belong to the same provider and
    # therefore to the same half; a false pair spanning the halves is assigned
    # by its lower provider id, which keeps every provider's true pairs in one
    # half only.
    is_eval_provider = {}
    for pid in set(provider_of):
        is_eval_provider[pid] = (pid % 2 == 0)
    eval_row = bytearray(is_eval_provider[provider_of[r]]
                         for r in range(n_rows))
    eval_providers = sum(1 for v in is_eval_provider.values() if v)

    print("scoring candidate pairs ...", flush=True)
    a_idx, b_idx = array("i"), array("i")
    labels = bytearray()
    vectors_fit_m = {f: {} for f in compare.FIELDS}
    vectors_fit_u = {f: {} for f in compare.FIELDS}
    n_fit_m = n_fit_u = 0
    pending = []

    n_pairs = 0
    for a_sys, a_id, b_sys, b_id in stream_pairs():
        ia, ib = index[(a_sys, a_id)], index[(b_sys, b_id)]
        vec = compare_vector(fields[ia], fields[ib])
        same = provider_of[ia] == provider_of[ib]
        pa, pb = provider_of[ia], provider_of[ib]
        in_eval = is_eval_provider[pa if pa <= pb else pb]

        a_idx.append(ia)
        b_idx.append(ib)
        labels.append(1 if same else 0)
        pending.append((compare.pattern(vec), in_eval))

        if not in_eval:
            bucket = vectors_fit_m if same else vectors_fit_u
            for f, lv in zip(compare.FIELDS, compare.pattern(vec)):
                bucket[f][lv] = bucket[f].get(lv, 0) + 1
            if same:
                n_fit_m += 1
            else:
                n_fit_u += 1

        n_pairs += 1
        if n_pairs % 500000 == 0:
            print("  %d pairs, %.0fs" % (n_pairs, time.time() - t_start),
                  flush=True)

    print("  %d pairs scored in %.0fs" % (n_pairs, time.time() - t_start))
    print("  fit set: %d matches, %d non-matches" % (n_fit_m, n_fit_u))

    weights = fit_weights(vectors_fit_m, vectors_fit_u, n_fit_m, n_fit_u)

    scores = array("f")
    eval_mask = bytearray()
    for pat, in_eval in pending:
        vec = dict(zip(compare.FIELDS, pat))
        scores.append(score_of(vec, weights))
        eval_mask.append(1 if in_eval else 0)
    del pending

    # ---- the evaluation half only -----------------------------------------
    ev_scores, ev_labels, ev_a, ev_b = array("f"), bytearray(), array("i"), array("i")
    ev_multi = 0
    for i in range(n_pairs):
        if eval_mask[i]:
            ev_scores.append(scores[i])
            ev_labels.append(labels[i])
            ev_a.append(a_idx[i])
            ev_b.append(b_idx[i])

    total_true_eval = int(lab.scalar("""
        SELECT coalesce(sum(k * (k - 1) / 2), 0) FROM (
            SELECT count(*) k FROM truth.source_row_link l
              JOIN truth.canonical_provider p ON p.provider_id = l.provider_id
             WHERE p.provider_id % 2 = 0
             GROUP BY l.provider_id) s;
    """))
    scored_true_eval = sum(ev_labels)
    print("  evaluation half: %d pairs scored, %d true; %d true pairs exist"
          % (len(ev_scores), scored_true_eval, total_true_eval))
    print("  recall is capped at %.4f by blocking"
          % (scored_true_eval / total_true_eval))

    lo, hi = min(ev_scores), max(ev_scores)
    grid = [lo + (hi - lo) * i / 200.0 for i in range(201)]
    curve = sweep(ev_scores, ev_labels, total_true_eval, grid)

    best_f1 = max(curve, key=lambda r: r["f1"])

    costs = {}
    for ratio in COST_RATIOS:
        priced = [dict(r, cost=ratio * r["fp"] + r["fn"]) for r in curve]
        best = min(priced, key=lambda r: r["cost"])
        at_f1 = [r for r in priced if r["threshold"] == best_f1["threshold"]][0]
        costs[str(ratio)] = {
            "cost_optimal": best,
            "cost_at_f1_optimal_threshold": at_f1,
            "extra_cost_of_choosing_by_f1": at_f1["cost"] - best["cost"],
            "threshold_moved_by": round(best["threshold"]
                                        - best_f1["threshold"], 3),
        }

    print()
    print("F1-optimal threshold %.3f  precision %.4f  recall %.4f  F1 %.4f"
          % (best_f1["threshold"], best_f1["precision"], best_f1["recall"],
             best_f1["f1"]))
    for ratio in COST_RATIOS:
        c = costs[str(ratio)]
        print("cost %2d:1  optimal threshold %7.3f  cost %8d   "
              "F1 threshold costs %8d  (+%d)"
              % (ratio, c["cost_optimal"]["threshold"],
                 c["cost_optimal"]["cost"],
                 c["cost_at_f1_optimal_threshold"]["cost"],
                 c["extra_cost_of_choosing_by_f1"]))

    # ---- the two-threshold review band -------------------------------------
    #
    # A single threshold is a false choice, the one the literature keeps
    # making. Auto-merge above an upper bound, auto-reject below a lower one,
    # and send the band between them to a person. What matters is not that the
    # band exists but what it BUYS: how many pairs a human has to look at, and
    # how much expected cost each of those decisions removes.
    #
    # The reviewer is assumed correct, which is an idealization and is stated
    # as one. A real queue is reviewed by people with an error rate of their
    # own, so every "cost removed" figure below is an upper bound, and a
    # reviewer who is right 90 percent of the time buys roughly 90 percent of
    # it. Nothing here measures human accuracy and nothing here should be read
    # as though it did.
    print()
    print("review band, priced at 10:1")
    ratio_for_band = 10
    best_single = costs[str(ratio_for_band)]["cost_optimal"]
    center = best_single["threshold"]
    bands = []
    span = (hi - lo)
    for width in [0.0, 0.02, 0.05, 0.10, 0.15, 0.20, 0.30, 0.40]:
        half = span * width / 2.0
        lower, upper = center - half, center + half
        auto_tp = auto_fp = band_true = band_false = 0
        for i in range(len(ev_scores)):
            sc = ev_scores[i]
            if sc >= upper:
                if ev_labels[i]:
                    auto_tp += 1
                else:
                    auto_fp += 1
            elif sc >= lower:
                if ev_labels[i]:
                    band_true += 1
                else:
                    band_false += 1
        # The reviewer resolves the band correctly, so its true pairs become
        # matches and its false pairs are rejected at no cost beyond the look.
        fn = total_true_eval - auto_tp - band_true
        cost = ratio_for_band * auto_fp + fn
        queue = band_true + band_false
        bands.append({
            "band_width_fraction_of_score_range": width,
            "lower": round(lower, 3), "upper": round(upper, 3),
            "review_queue_pairs": queue,
            "reviews_per_10000_providers": round(
                queue / float(eval_providers) * 10000.0, 1),
            "auto_merged_true": auto_tp, "auto_merged_false": auto_fp,
            "missed_after_review": fn,
            "expected_cost": cost,
            "cost_removed_vs_no_band": best_single["cost"] - cost,
            # The only number an operator can act on. Expressed as a
            # BREAK-EVEN rather than a verdict: one human decision removes
            # this much expected cost, so the band is worth having exactly
            # when a reviewer's time is worth less than this, in the same
            # units the cost ratio is stated in. The repository does not know
            # what a review costs and does not pretend to.
            "break_even_review_cost": round(
                (best_single["cost"] - cost) / queue, 4) if queue else 0.0,
        })
        print("  width %4.0f%%  queue %7d (%8.1f per 10k providers)  cost %7d"
              "  break-even %6.4f"
              % (width * 100, queue, bands[-1]["reviews_per_10000_providers"],
                 cost, bands[-1]["break_even_review_cost"]))

    # The marginal rate is what decides how wide to go, not the average. Each
    # widening adds pairs that are further from the decision boundary and
    # therefore worth less to look at, so the question is always whether the
    # NEXT slice of queue pays, not whether the whole queue did.
    for i in range(1, len(bands)):
        extra_q = (bands[i]["review_queue_pairs"]
                   - bands[i - 1]["review_queue_pairs"])
        extra_c = (bands[i]["cost_removed_vs_no_band"]
                   - bands[i - 1]["cost_removed_vs_no_band"])
        bands[i]["marginal_break_even_review_cost"] = round(
            extra_c / extra_q, 4) if extra_q else 0.0
    bands[0]["marginal_break_even_review_cost"] = None
    print("  marginal break-even by width: %s"
          % ", ".join("%.0f%%=%s" % (b["band_width_fraction_of_score_range"] * 100,
                                     b["marginal_break_even_review_cost"])
                      for b in bands[1:]))

    # ---- cluster damage ----------------------------------------------------
    #
    # One false pair is not one error. Connected components are transitive, so
    # a single wrong link merges two entire providers and everything already
    # attached to either of them. A pairwise precision of 0.999 can still put
    # a visible share of providers into a cluster that is about somebody else.
    print()
    print("cluster damage")
    # Swept, not sampled at the operating points. Welding is not linear in the
    # false pair count: below some threshold the accepted pairs start forming
    # chains, and a chain merges every provider it touches at once. A table
    # that only reports the chosen thresholds cannot show how close the chosen
    # threshold sits to that cliff, which is the thing worth knowing about it.
    named = {round(best_f1["threshold"], 3): "f1_optimal"}
    for r in COST_RATIOS:
        named.setdefault(
            round(costs[str(r)]["cost_optimal"]["threshold"], 3), ""
        )
        named[round(costs[str(r)]["cost_optimal"]["threshold"], 3)] = (
            (named[round(costs[str(r)]["cost_optimal"]["threshold"], 3)]
             + " cost_optimal_%d_to_1" % r).strip())

    probe = sorted(set(
        [round(x, 3) for x in (-20, -12, -8, -5, -3, -1, 2, 5, 12, 20)]
        + list(named)))
    damage = []
    for t in probe:
        d = cluster_damage(ev_a, ev_b, ev_scores, ev_labels, t, provider_of,
                           n_rows, eval_row)
        d["operating_point"] = named.get(t, "")
        d["welded_provider_share"] = round(
            d["providers_in_a_welded_cluster"] / d["providers_present"], 6) \
            if d["providers_present"] else 0.0
        # How much the transitive closure multiplies a pairwise error. Above
        # 1 means a reader who judged this operating point by its false pair
        # rate underestimated how many providers it actually damages.
        d["damage_amplification"] = round(
            d["welded_provider_share"] / d["false_pair_share_of_accepted"], 3
        ) if d["false_pair_share_of_accepted"] else None
        damage.append(d)
        print("  thr %7.3f  accepted %7d  false %6d (%.4f)  clusters %6d  "
              "welded %5d  providers welded %5d (%.4f)  worst %5d  %s"
              % (t, d["accepted_pairs"], d["accepted_false"],
                 d["false_pair_share_of_accepted"], d["clusters"],
                 d["welded_clusters"], d["providers_in_a_welded_cluster"],
                 d["welded_provider_share"],
                 d["most_providers_in_one_cluster"], d["operating_point"]))

    at_10 = [d for d in damage
             if "cost_optimal_10_to_1" in d["operating_point"]][0]
    pred_a_held = (costs["10"]["cost_optimal"]["threshold"]
                   != best_f1["threshold"]
                   and costs["10"]["extra_cost_of_choosing_by_f1"] > 0)
    pred_b_held = (at_10["welded_provider_share"]
                   > at_10.get("false_pair_share_of_accepted", 0.0))

    payload = {
        "pairs_scored": n_pairs,
        "eval_pairs_scored": len(ev_scores),
        "eval_true_pairs_scored": scored_true_eval,
        "eval_true_pairs_total": total_true_eval,
        "recall_ceiling_from_blocking": round(
            scored_true_eval / total_true_eval, 6),
        "fit_matches": n_fit_m,
        "fit_non_matches": n_fit_u,
        "weights": {f: {lv: round(weights[f][lv], 4)
                        for lv in compare.LEVELS} for f in compare.FIELDS},
        "score_range": [round(lo, 3), round(hi, 3)],
        "curve": curve,
        "f1_optimal": best_f1,
        "cost_optimal": costs,
        "cost_ratios": COST_RATIOS,
        "review_band": {
            "priced_at_ratio": ratio_for_band,
            "center_threshold": round(center, 3),
            "reviewer_assumed_correct": True,
            "bands": bands,
            "eval_providers": eval_providers,
        },
        "cluster_damage": damage,
        "predictions": {
            "f1_is_not_cost_optimal": dict(
                PREDICTIONS["f1_is_not_cost_optimal"],
                f1_threshold=best_f1["threshold"],
                cost_optimal_threshold_10_to_1=costs["10"]["cost_optimal"]["threshold"],
                extra_cost_of_choosing_by_f1=costs["10"]["extra_cost_of_choosing_by_f1"],
                verdict="held" if pred_a_held else "REFUTED"),
            "cluster_damage_exceeds_pair_error": dict(
                PREDICTIONS["cluster_damage_exceeds_pair_error"],
                welded_provider_share=at_10["welded_provider_share"],
                false_pair_share_of_accepted=at_10.get(
                    "false_pair_share_of_accepted"),
                verdict="held" if pred_b_held else "REFUTED"),
        },
    }
    lab.write_result("exp2_threshold", payload)
    print()
    print("prediction A (F1 is not cost-optimal): %s"
          % payload["predictions"]["f1_is_not_cost_optimal"]["verdict"])
    print("prediction B (cluster damage exceeds pair error): %s"
          % payload["predictions"]["cluster_damage_exceeds_pair_error"]["verdict"])
    print("wrote results/exp2_threshold.json  (%.0fs)" % (time.time() - t_start))
    return 0


if __name__ == "__main__":
    sys.exit(main())
