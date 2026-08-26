# roster-entity-resolution

[![CI](https://github.com/jkelly-dev1/roster-entity-resolution/actions/workflows/ci.yml/badge.svg)](https://github.com/jkelly-dev1/roster-entity-resolution/actions/workflows/ci.yml)

Four provider rosters disagree about the same 20,000 doctors. Which records are
the same provider, what does the canonical record look like afterward, and where
do you draw the line when a false match and a missed match do not cost the same?

The claim this repository makes in one line: a matching threshold is not a
tuning parameter, it is a cost decision, and the same data defends a different
threshold once you say what a wrong merge costs.

A personal learning project. Every number below is read out of a shipped results
file, never out of the prose, and every prediction was recorded before its run.
The refuted ones are still in the code.

What you need to run it: one Postgres container and Python 3.11 or later.
Nothing else. `docker compose up -d` starts a single Postgres 17 bound to
loopback, and the whole pipeline takes about two minutes. There is no corpus to
download and no cloud account: the rosters are a pure function of a seed, so a
clone reproduces the same 74,926 rows byte for byte. The test suite needs
neither Docker nor Postgres.

The four questions this repository answers:

1. What does blocking throw away before scoring ever runs?
2. Where is the threshold, once the two errors are priced differently, and
   what does the transitive closure do to a pairwise error?
3. Which survivorship rule produces the most accurate golden record?
4. Does a human override survive the next file?

The result in one paragraph. Blocking on NPI alone reaches 47 percent of the
true pairs, not the 95 percent predicted, and the four strategies together still
lose 1,309 pairs that no threshold downstream can recover. Pricing a false match
at 10 times a missed one moves the optimal threshold by 8.0 points and makes the
F1-optimal choice cost 26 percent more; at 30:1 it costs 74 percent more. A
per-field source priority beats majority vote, which gets the legal first name
wrong for 42 percent of providers because three of the four sources carry the
nickname. And 271 of 500 human overrides keyed on a cluster id were silently
transferred to a different provider after the second file arrived, usually the
one next door, while only 23 percent of clusters had actually changed.

## The data, and why it can be trusted

Generated, not downloaded. Every value is a pure function of a seed and a row
number, so a clone reproduces the rows and every number below without fetching
anything. Each results file records the sha256 of the input it was measured on.

The world holds 20,000 canonical providers and four partial, corrupted views of them:

| Source | Rows | Authoritative on | Wrong in its own way |
| --- | --- | --- | --- |
| `payer_feed` | 20,498 | network status | names as `LAST, FIRST`; NPI absent on 15% of rows; street types abbreviated inconsistently; state mistyped on 1.5% |
| `license_board` | 19,617 | credential, legal first name | NO ADDRESS AND NO PHONE AT ALL; NPI absent on 30% |
| `site_scrape` | 15,408 | nothing | suite sometimes folded into the street line and sometimes dropped; phone in four formats; NPI on 20%; some rows name two providers |
| `clearinghouse` | 19,403 | NPI | ADDRESS IS STALE for the 12% of providers who moved, and this is the freshest file in the data |

Across all four: 74,926 source rows, 107,459 true pairs, and 2,806,915,275
possible pairs.

The corruption is the design. A source that is merely a subset of the truth
teaches nothing, because every strategy scores the same on it. On top of the
per-source failures above, 3 percent of rows carry a surname typo, 2 percent a
given-name typo, and 2.5 percent of providers have had a legal surname change
that two of the four sources have not caught up with.

Ground truth ships with it, in its own `truth` schema that the resolver never
reads. That is the only reason precision and recall here are measured rather
than estimated, and it is also the biggest thing that does not generalize: see
"What this does not measure".

## 1. What blocking throws away before scoring runs

Comparing every pair of 74,926 rows is 2.8 billion comparisons. Blocking cuts
that down. The question nobody asks is what it discards, and a true pair dropped
by the blocker can never be recovered: it is never scored, so no threshold, no
model and no human reviewer downstream gets it back.

| Strategy | Candidate pairs | True pairs found | Pair completeness | Reduction ratio |
| --- | --- | --- | --- | --- |
| exact NPI | 51,013 | 51,013 | 0.4747 | 0.999982 |
| ZIP + first 4 of surname | 48,412 | 39,670 | 0.3692 | 0.999983 |
| surname soundex + state | 3,610,478 | 102,608 | 0.9549 | 0.998714 |
| phone digits | 45,926 | 45,917 | 0.4273 | 0.999984 |
| union of all four | 3,614,341 | 106,150 | 0.9878 | 0.998712 |

The prediction was that exact NPI blocking would be sufficient, meaning it would
keep at least 95 percent of true pairs. IT WAS REFUTED AT 0.4747, and the
prediction is still in the code. Every candidate pair it produces is a true
pair, because NPIs are unique in this data, so it looks perfect on precision
while missing more than half the problem.

The reason is visible in what each source can even be blocked on:

| Source | Rows | Can block on NPI | on ZIP | on phone | on soundex |
| --- | --- | --- | --- | --- | --- |
| `clearinghouse` | 19,403 | 19,403 | 19,403 | 19,403 | 19,403 |
| `license_board` | 19,617 | 13,771 | 0 | 0 | 19,617 |
| `payer_feed` | 20,498 | 17,360 | 20,498 | 20,498 | 20,498 |
| `site_scrape` | 15,408 | 3,054 | 15,408 | 15,408 | 15,408 |

The license board has no address and no phone, so surname soundex plus state
is the ONLY strategy any of its 19,617 rows can take part in. Only 3,054 of the
site scrape's 15,408 rows carry an NPI at all.

The number that matters most is the one the table does not show. The union
reaches 106,150 of 107,459 true pairs, so 1,309 true pairs are gone before
scoring begins. Recall in section 2 is capped at 0.9879 by that alone, and every
recall figure there is measured against all true pairs rather than against the
candidate list, so the loss is carried rather than hidden.

### What an index does to the blocking join, and what it does not

The blocking join reads both sides of the table once, so the planner hashes it
and a btree index changes nothing measurable:

| Query | Plan without an index | Plan with the index | Time |
| --- | --- | --- | --- |
| full batch, 74,926 rows | Gather / Partial Aggregate | unchanged | 20.536 ms to 20.140 ms |
| correction file, 50 rows | Hash Join / Seq Scan | Merge Join / Index Only Scan | 7.443 ms to 0.717 ms |
| correction file, 1,000 rows | Hash Join / Seq Scan | Hash Join / Seq Scan | 9.986 ms to 11.355 ms |

The index earns its keep on a small correction file and nowhere else, and the
planner is right about all three. At 50 probe rows it switches to an index only
scan. At 1,000 it declines the index and goes back to hashing the table, because
scanning 74,926 rows once is cheaper than 1,000 index descents. A system that
indexes for the nightly full rebuild has bought nothing; a system that indexes
for the intra-day delta has bought a real speedup.

Treat the milliseconds as the shape of the answer and not as the answer. They
are one machine, one warm cache, and a table that fits entirely in memory.
The PLAN CHANGE is the reproducible part.

## 2. The threshold, priced

This is the reason the repository exists.

Field comparators produce an agreement level per candidate pair: Jaro-Winkler on
given and family name with a nickname table, exact match on NPI, phone, ZIP,
state and specialty, and token overlap on the address after abbreviation
folding. Missing is its own level and is not folded into DISAGREE, because the
license board has no address at all and scoring that as an address disagreement
would push every one of its true pairs below any threshold. Fellegi-Sunter m and
u probabilities turn those into a log-odds weight.

Fit on one half of the providers, reported from the other. The truth is
available here, so it would be easy and wrong to fit and score on the same rows.
Both rows of a true pair always belong to the same provider and so to the same
half, which is what keeps the m probabilities out of the evaluation set. Every
number below comes from the evaluation half: 1,793,014 scored pairs covering
53,438 of the 54,092 true pairs those providers have.

### The weights are conditional on blocking, and two of them look wrong

| Field | Agree | Disagree |
| --- | --- | --- |
| NPI | +20.70 | -15.72 |
| street | +20.41 | -2.40 |
| phone | +16.30 | -3.05 |
| ZIP | +7.16 | -2.40 |
| given name | +5.99 | -6.66 |
| specialty | +4.33 | -16.61 |
| family name | +0.12 | -2.75 |
| state | -0.01 | +8.02 |

Agreeing on a surname is worth 0.12 bits and disagreeing on the state is
evidence for a match. Neither is a defect. Blocking already required near
agreement on the surname, so by the time a pair is scored almost every pair
agrees on it and the agreement has stopped discriminating. State is sharper: a
candidate pair can only disagree on state if it arrived through NPI or phone
blocking, and those two produce true pairs 100 and 99.98 percent of the time, so
a state disagreement in THIS candidate set really is evidence of a match.

That is correct Fellegi-Sunter behavior and it is also a warning. THE u
probabilities are conditional on the candidate set, not on the population.
Weights fitted after one blocking scheme do not transfer to another.

### Where the line goes, once the two errors are priced

A false match merges two different providers: a member is told an
out-of-network provider is covered, and is billed for it. A missed match leaves
a duplicate: the directory shows the same doctor twice, and coverage can be
denied that should have been approved. These are not the same cost, and this
repository does not claim to know the real ratio. It sweeps it.

| Cost of a false match | Optimal threshold | Expected cost | Cost at the F1-optimal threshold | Penalty for choosing by F1 |
| --- | --- | --- | --- | --- |
| 1:1 | 0.385 | 1,448 | 1,448 | none |
| 3:1 | 0.385 | 2,782 | 2,782 | none |
| 10:1 | 8.382 | 5,919 | 7,451 | +1,532, or 26% |
| 30:1 | 9.715 | 11,924 | 20,791 | +8,867, or 74% |

The F1-optimal threshold is 0.385, with precision 0.9876 and recall 0.9856. The
prediction was that F1 would not be cost-optimal, and it held, but not
everywhere, and the exception is the more useful half of the result: AT 1:1 AND
3:1 the F1 choice is exactly optimal and costs nothing. F1 weights the two
errors equally by construction, so it is a defensible choice precisely when they
cost about the same, and an expensive one as soon as they do not. The threshold
moves 8.0 points at 10:1 and 9.3 at 30:1.

### One false pair is not one error

A resolver does not ship pairwise decisions, it ships clusters, and connected
components are transitive. Measured over the evaluation half:

| Threshold | Accepted pairs | False | Share false | Clusters | Providers in a welded cluster | Most providers in one cluster |
| --- | --- | --- | --- | --- | --- | --- |
| -20.000 | 125,816 | 72,378 | 0.5753 | 6,316 | 5,560 | 213 |
| -8.000 | 73,466 | 20,045 | 0.2728 | 7,683 | 4,212 | 15 |
| -3.000 | 71,356 | 17,935 | 0.2513 | 7,855 | 3,966 | 6 |
| -1.000 | 54,081 | 768 | 0.0142 | 10,019 | 124 | 2 |
| 0.385 (F1) | 53,978 | 667 | 0.0124 | 10,034 | 94 | 2 |
| 8.382 (10:1) | 51,495 | 302 | 0.0059 | 10,062 | 88 | 2 |
| 12.000 | 38,319 | 0 | 0.0000 | 13,538 | 0 | 1 |

There is a cliff and the chosen threshold sits well clear of it. At the 10:1
operating point the worst cluster holds two providers, and it still holds two
four points lower. It first reaches six at -3.000, about eleven points below the
operating point, four rows down the table, and by -8.000 a single cluster is
about fifteen different doctors. The share of accepted pairs that are false
rises by a factor of 47 between the operating point and -8.000, while the worst
wrong merge grows from two providers to fifteen. At -20.000 a single cluster is
about 213 different doctors.

And at the operating point itself the two denominators disagree. Precision is
0.9941, so 0.59 percent of accepted pairs are wrong. But 88 of the 10,000
evaluation providers, 0.88 percent, sit in a cluster that is about more than one
doctor. A reader who takes precision 0.994 and infers that 0.6 percent of the
directory is affected has understated it by half. The prediction that cluster
damage would exceed the pairwise error rate held. The ratio between them is not
monotone across the sweep and is not offered as a constant.

### The third option, which is what an operations team actually runs

A single threshold is a false choice. Auto-merge above an upper bound,
auto-reject below a lower one, and send the band between them to a person.
Priced at 10:1, with the band centered on the cost-optimal threshold:

| Band width | Review queue | Reviews per 10,000 providers | Expected cost | Break-even review cost |
| --- | --- | --- | --- | --- |
| none | 0 | 0 | 5,919 | n/a |
| 2% | 286 | 286 | 5,803 | 0.4056 |
| 5% | 13,218 | 13,218 | 2,873 | 0.2304 |
| 10% | 15,635 | 15,635 | 818 | 0.3263 |
| 20% | 35,348 | 35,348 | 671 | 0.1485 |
| 40% | 103,181 | 103,181 | 654 | 0.0510 |

The last column is the only one an operator can act on, and it reports a
break-even: one human decision removes that much expected cost, so the band pays
exactly when a reviewer's time is worth less than that, in the same units the
cost ratio is stated in. This repository does not know what a review costs and
does not publish a number that assumes one.

What the table says plainly is that a review layer is not cheap here. Even the
narrowest band puts 286 pairs per 10,000 providers in front of a person, and
each of those looks is worth at most 0.41 of one missed match. Getting the cost
down to 818 takes 15,635 reviews per 10,000 providers, which is more than one
review per provider and is not an operations plan.

The reviewer is assumed correct, which is an idealization. Every figure in that
table is an upper bound on what a band buys, and a reviewer who is right 90
percent of the time buys roughly 90 percent of it. Nothing here measures human
accuracy.

## 3. Survivorship, and the golden record

A cluster is agreed. Which value wins, field by field? Scored as field-level
accuracy against the answer key over the 19,839 clusters that are about exactly
one provider. The 191 welded clusters are excluded rather than scored, because
a cluster about two providers has no correct golden record and scoring one
would blame a survivorship rule for a matching decision.

| Field | first_non_null | most_recent | majority_vote | source_priority |
| --- | --- | --- | --- | --- |
| NPI | 0.9871 | 0.9871 | 0.9871 | 0.9871 |
| first name | 0.5540 | 0.5422 | 0.5834 | 0.9657 |
| last name | 0.9445 | 0.9447 | 0.9719 | 0.9653 |
| credential | 0.9625 | 0.9562 | 0.9908 | 0.9955 |
| street | 0.8733 | 0.8803 | 0.9572 | 0.9504 |
| suite | 0.9160 | 0.9180 | 0.9301 | 0.9397 |
| city | 0.9924 | 0.9924 | 0.9924 | 0.9924 |
| state | 0.9998 | 0.9980 | 0.9997 | 0.9998 |
| ZIP | 0.8748 | 0.8814 | 0.9576 | 0.9508 |
| phone | 0.9885 | 0.9760 | 0.9883 | 0.9525 |
| specialty | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| network status | 0.9402 | 0.9402 | 0.9402 | 0.9402 |
| **mean** | **0.9194** | **0.9181** | **0.9416** | **0.9700** |

The prediction was that majority vote would be the best general strategy, and it
was refuted. Per-field source priority wins on the mean by 2.8 points.

The sharpest case is the one that was predicted. Majority vote gets the legal
first name right 58 percent of the time. The license board is the only source
carrying a legal first name; the other three carry whatever the practice uses,
so for every provider with a common short form the majority is popular and
wrong. A vote cannot express "one source is the authority on this field and
three are not", and that is the entire content of a per-field priority list.

Most recent is the worst strategy in the table, and that is the second finding.
The clearinghouse pushes daily and is the freshest file in the data. It is also
the only source with a stale address. Recency of the file is not recency of the
fact, and a rule that reads one as the other picks the wrong source every time.

### Where per-field priority loses, and why

Priority scores worse than majority vote on street, ZIP and phone in the table
above. It is not the rule that is wrong there.

Of the 20,000 providers, 2,517 are listed by some source at TWO PRACTICE
LOCATIONS. Both addresses are real and a single golden address cannot be
correct for them. Restricting to the providers with one site:

| Field | majority_vote | source_priority |
| --- | --- | --- |
| first name | 0.5903 | 0.9684 |
| last name | 0.9723 | 0.9660 |
| street | 0.9591 | 0.9895 |
| ZIP | 0.9595 | 0.9896 |
| phone | 0.9920 | 0.9920 |
| **mean over all 12 fields** | **0.9445** | **0.9824** |

The address gap reverses completely. That is a data model failure and not a
survivorship failure: one golden record per provider is the wrong shape for a
doctor who practices at two addresses, and no rule can be scored fairly on it.

One counter-example survives and is kept. Majority vote still beats priority on
the surname, 0.9723 to 0.9660, even among single-site providers. Every source is
equally authoritative about a surname and their typos are independent, so a vote
across four rows outperforms trusting one source that has a 3 percent typo rate
of its own. Priority wins where sources differ systematically; voting wins where
they differ only by noise. A strategy chosen without asking which case a field
is in will be wrong about some of them.

### Lineage

Every field of every golden record records the source system, the source row and
the rule that selected it. That is not a feature to demonstrate, it is an
invariant to test: every value must appear in the source row it names. 227,755
field values were checked and 0 violated it.

The check earns its place because no accuracy figure can replace it. A
survivorship rule that returns the right value with the wrong provenance scores
identically to a correct one, and a rule that invents a value fails here and
nowhere else. A majority vote has no single origin, so its winner is attributed
to the most recent row that actually holds that value rather than to an
arbitrary member of the cluster.

## 4. Does a human override survive the next file?

An operations specialist makes 500 decisions the pipeline could not: 200
SPLITS of pairs the resolver wrongly merged, 200 MERGES of pairs it wrongly
rejected, and 100 PINS fixing an address the clearinghouse had stale. Every one
of them is correct, taken from the answer key, so the experiment is about
whether a right decision survives rather than whether it was right.

Then a second roster file arrives: 4,819 new rows, taking 74,926 to 79,745. The
site scrape reaches providers it had never crawled, the payer feed reissues
rows, and the clearinghouse catches up on some of the movers.

| Keying scheme | Retained | Lost | Misapplied to another provider |
| --- | --- | --- | --- |
| on the derived cluster id | 229 | 0 | 271 |
| on (source_system, source_row_id) | 500 | 0 | 0 |

The prediction was that overrides would survive re-ingest. IT WAS REFUTED, and
the failure is worse than losing them. NOT ONE OF THE 500 WAS DROPPED. 271 of
them, 54 percent, were still being enforced against a different provider.

Every one of those 271 landed on a cluster sharing no row with the one the
operator looked at, and the wrong provider is usually the one next door. A split
meant for provider 1308 was applied to provider 1307; one meant for 1737 to
1736. That is what makes it quiet. An override that jumped to a random record
might be noticed; one that slides onto the adjacent cluster looks like an
ordinary decision about a plausible neighbor, and nothing in the pipeline flags
it.

The 229 that survived are the problem, not a consolation. Nothing in the scheme
distinguishes them from the 271: their cluster ids happened not to shift.
Nothing was lost, so there is no error to catch and no count that looks wrong,
and an operator cannot tell a surviving override from a transplanted one without
going back to the source rows. A mechanism that is right 46 percent of the time
by accident is harder to fix than one that fails outright.

The contrast is the result. Only 4,527 of the 20,030 clusters, 23 percent,
genuinely gained or lost a row. But 18,005 of them, 90 percent, now have a
different member set sitting at their old id. A cluster id is assigned by the
run: one new row early in the ordering renumbers everything after it. A 23
percent change in the data was enough to move four times as many ids.

### The overrides that are now stale

Of the 100 pins, 39 are contradicted by the second file. The operator pinned an
address because the clearinghouse was wrong about it, and the clearinghouse has
since issued a corrected row. The pin is still keyed correctly, still applied,
and no longer necessary; had the truth moved instead, it would now be wrong.

A system that never revisits a human decision is as broken as one that discards
it. Neither behavior is proposed here as the right one. The honest middle is to
count them and put the count in front of somebody, which is what this number is.

## Reproducing it

```
cd stack && docker compose up -d && cd ..
python3 scripts/load.py
python3 scripts/normalize.py
python3 scripts/exp1_blocking.py
python3 scripts/exp2_threshold.py
python3 scripts/exp3_survivorship.py
python3 scripts/load.py --batch2
python3 scripts/normalize.py --batch 2
python3 scripts/exp1_blocking.py --batches 1,2 --strategy union_b12 --no-result
python3 scripts/exp4_override_stability.py
```

About two minutes end to end. `SAMPLE_RUN.md` is the captured output of exactly
that sequence. The last blocking run materializes candidate pairs over both
ingests and deliberately writes no results file, so the published first-ingest
measurement cannot be overwritten by the preparation for experiment 4.

The test suite needs neither Docker nor Postgres:

```
pip install pytest
python -m pytest -q
python3 scripts/check_readme_numbers.py
```

Take the stack down with `cd stack && docker compose down -v`.

## Claims backed by tests

Rows carrying a published number are mutation-checked and say so.

| Claim | Test |
| --- | --- |
| Jaro-Winkler matches the values published for it, including on a transposition | `tests/test_comparators.py::test_jaro_winkler_matches_the_published_value_for_martha_and_marhta` |
| The prefix boost cannot push a similarity above 1 (mutation-checked: raise max_prefix to 8 and the guard fires) | `tests/test_comparators.py::test_jaro_winkler_never_exceeds_one_for_a_long_shared_prefix` |
| A missing field is MISSING and not a disagreement (mutation-checked: return DISAGREE in cmp_street and the license board's street weight collapses) | `tests/test_comparators.py::test_a_missing_field_is_missing_and_not_a_disagreement` |
| A nickname matches its legal name only because of the table (mutation-checked: drop the table and the pair scores DISAGREE) | `tests/test_comparators.py::test_a_nickname_agrees_with_its_legal_name_only_with_the_table` |
| Every spelling of a street type folds to one token (mutation-checked: remove PKWY and the scraped form fails) | `tests/test_normalization.py::test_every_spelling_of_a_street_type_folds_to_one_token` |
| The name format is chosen by source, not guessed from a comma | `tests/test_normalization.py::test_the_format_is_chosen_by_source_and_not_guessed_from_a_comma` |
| A row naming two providers resolves to the first of them | `tests/test_normalization.py::test_a_row_naming_two_providers_resolves_to_the_first_of_them` |
| A malformed identifier becomes absent rather than a key that means nothing (mutation-checked) | `tests/test_normalization.py::test_a_malformed_identifier_becomes_absent_rather_than_a_useless_key` |
| 20,000 providers hold 20,000 distinct NPIs (mutation-checked: hash the digits instead and it fails at 19,998) | `tests/test_generator.py::test_twenty_thousand_providers_hold_twenty_thousand_distinct_npis` |
| Every generated NPI is Luhn-valid over the 80840 prefix | `tests/test_generator.py::test_every_npi_is_luhn_valid_over_the_constant_prefix` |
| A typo never touches the first character, so soundex blocking is measured rather than assumed | `tests/test_generator.py::test_a_typo_never_touches_the_first_character` |
| The clearinghouse is the freshest file and carries the stalest address | `tests/test_generator.py::test_the_clearinghouse_is_the_freshest_file_and_the_stalest_address` |
| The license board ships no address and no phone at all | `tests/test_generator.py::test_the_license_board_ships_no_address_and_no_phone_at_all` |
| No blocking strategy finds more true pairs than exist (mutation-checked: unparenthesize the union clause and completeness reads 2.6973) | `tests/test_results_invariants.py::test_no_strategy_finds_more_true_pairs_than_exist` |
| The union is at least as complete as any strategy inside it | `tests/test_results_invariants.py::test_the_union_is_at_least_as_complete_as_any_strategy_in_it` |
| NPI blocking alone was predicted sufficient and was refuted | `tests/test_results_invariants.py::test_npi_blocking_alone_was_predicted_sufficient_and_was_refuted` |
| The license board can never block on an address or a phone | `tests/test_results_invariants.py::test_the_license_board_can_never_block_on_an_address_or_a_phone` |
| The index is measured against a genuinely unindexed plan (mutation-checked: unqualify the DROP and the unindexed probe reads 0.4 ms against a true 8.6 ms) | `tests/test_results_invariants.py::test_an_index_is_measured_against_a_genuinely_unindexed_plan` |
| The full-batch join is not helped by an index | `tests/test_results_invariants.py::test_the_full_batch_join_is_not_helped_by_an_index` |
| Recall never rises as the threshold rises (mutation-checked: walk the grid ascending and the whole curve collapses to one point) | `tests/test_results_invariants.py::test_recall_never_rises_as_the_threshold_rises` |
| Recall is capped by what blocking kept | `tests/test_results_invariants.py::test_recall_is_capped_by_what_blocking_kept` |
| False negatives include the pairs blocking never emitted | `tests/test_results_invariants.py::test_false_negatives_include_the_pairs_blocking_never_emitted` |
| The weights were fitted on a disjoint half of the providers | `tests/test_results_invariants.py::test_the_weights_were_fitted_on_a_disjoint_half_of_the_providers` |
| Agreeing on a surname carries almost no evidence after blocking | `tests/test_results_invariants.py::test_agreeing_on_a_surname_carries_almost_no_evidence_after_blocking` |
| Choosing by F1 costs nothing at parity and costs money at 10:1 | `tests/test_results_invariants.py::test_choosing_by_f1_costs_nothing_at_parity_and_costs_money_at_ten_to_one` |
| The cost-optimal threshold rises with the price of a false match | `tests/test_results_invariants.py::test_the_cost_optimal_threshold_rises_with_the_price_of_a_false_match` |
| Every recorded optimum is the optimum its price implies, re-derived from the published curve rather than read from the file | `tests/test_results_invariants.py::test_every_recorded_optimum_is_the_optimum_its_price_implies` |
| A false match is the priced error and a miss is the unit, so raising the price makes the matcher STRICTER. Swapping the two terms leaves the thresholds sorted -- they collapse to one value -- so the ordering row above cannot see it | `tests/test_results_invariants.py::test_a_false_match_is_the_priced_error_and_a_miss_is_the_unit` (mutation-checked: swap the two cost terms, or price a false match at zero, and it fails) |
| The transitive closure multiplies a pairwise error at the operating point | `tests/test_results_invariants.py::test_the_transitive_closure_multiplies_a_pairwise_error` |
| Welding gets worse as the threshold falls, and the cliff is real | `tests/test_results_invariants.py::test_welding_gets_worse_as_the_threshold_falls` |
| A wider review band never shrinks the queue and never raises the cost | `tests/test_results_invariants.py::test_a_wider_review_band_never_shrinks_the_queue` |
| The band is priced as a break-even and not as a verdict | `tests/test_results_invariants.py::test_the_band_is_priced_as_a_break_even_and_not_as_a_verdict` |
| Per-field priority beats every other strategy on the mean | `tests/test_results_invariants.py::test_per_field_priority_beats_every_other_strategy_on_the_mean` |
| The prediction that majority vote would win was refuted | `tests/test_results_invariants.py::test_the_prediction_that_majority_vote_would_win_was_refuted` |
| Majority vote loses the legal first name to the nickname | `tests/test_results_invariants.py::test_majority_vote_loses_the_legal_first_name_to_the_nickname` |
| Majority vote still wins where the sources differ only by noise | `tests/test_results_invariants.py::test_majority_vote_still_wins_where_the_sources_differ_only_by_noise` |
| A provider at two practice sites has no single correct address | `tests/test_results_invariants.py::test_a_provider_at_two_practice_sites_has_no_single_correct_address` |
| Welded clusters are excluded from survivorship rather than scored | `tests/test_results_invariants.py::test_welded_clusters_are_excluded_from_survivorship_rather_than_scored` |
| Natural keys lose no override here, and CANNOT misapply one by construction: a natural key names a source row, so it either resolves to that row or does not resolve at all. The zero in that column is a property of the scheme, not a measurement, and `lost 0` holds because this second ingest only ADDS rows | `tests/test_results_invariants.py::test_natural_keys_lose_no_override_and_misapply_none` |
| The cluster-id replay split is the one the recorded pair ordering produces, so a re-run that drops the ORDER BY is caught rather than published | `tests/test_results_invariants.py::test_the_cluster_id_replay_split_matches_the_recorded_ordering` |
| Cluster-id keying misapplies overrides onto unrelated providers | `tests/test_results_invariants.py::test_cluster_id_keying_misapplies_overrides_onto_other_providers` |
| A small change in the data renumbers almost every cluster (mutation-checked: compare by cluster id instead of member set and the contrast disappears) | `tests/test_results_invariants.py::test_a_small_change_in_the_data_renumbers_almost_every_cluster` |
| Some pins are now contradicted by a corrected source row | `tests/test_results_invariants.py::test_some_pins_are_now_contradicted_by_a_corrected_source_row` |
| All four experiments measured the same generated input | `tests/test_results_invariants.py::test_all_four_experiments_measured_the_same_input` |
| Most recent reads the freshness of the file and not of the fact | `tests/test_survivorship.py::test_most_recent_reads_the_freshness_of_the_file_not_of_the_fact` |
| A majority winner is attributed to a row that actually holds it | `tests/test_survivorship.py::test_a_majority_winner_is_attributed_to_a_row_that_actually_holds_it` |
| Per-field priority takes the legal name from the licensing board | `tests/test_survivorship.py::test_per_field_priority_takes_the_legal_name_from_the_licensing_board` |
| Per-field priority puts the clearinghouse last on an address and first on the NPI | `tests/test_survivorship.py::test_per_field_priority_puts_the_clearinghouse_last_on_an_address` |
| An address is compared folded on both sides (mutation-checked: compare raw text and every strategy scores about 0.21 on street) | `tests/test_survivorship.py::test_an_address_is_compared_folded_on_both_sides` |
| Every shipped lineage row names a source row that holds its value | `tests/test_survivorship.py::test_every_shipped_lineage_row_names_a_source_row_that_holds_its_value` |

## What this does not measure

- Synthetic truth. That answer key was invented here, and real entity resolution
  has no answer key. Every precision and recall figure above is measured against
  a truth this repository made up.
- One corruption model. Every threshold here is a function of how the errors
  were generated, and the generator is a guess at how rosters go wrong. The
  method transfers; the numbers do not. A reader who takes 8.382 away from this
  and applies it to a real roster has misread it.
- Weights conditional on one blocking scheme. The u probabilities are estimated
  over the candidate set, so the weights in section 2 do not transfer to a
  different blocker. Two of them are visibly shaped by it.
- One scale, one machine. 20,000 providers and 74,926 rows on local Postgres.
  Nothing here says what happens at fifty million, and the milliseconds in
  section 1 are one warm cache on one box.
- No learned model on real labels. Fellegi-Sunter weights fitted on generated
  data are not a trained matcher and calling them one would be a stretch.
- No measurement of human accuracy. The review band in section 2 and the
  overrides in section 4 both assume the person is right. Every figure that
  depends on that is an upper bound.
- Not a healthcare claim. Provider networks are the setting because the domain
  makes the cost asymmetry concrete. This repository is not evidence of
  healthcare domain experience and is not described as though it were.

## Related repositories

[roster-ingest-guarantees](https://github.com/jkelly-dev1/roster-ingest-guarantees)
is the one to read directly against this repository. It measures where a Kafka
to Iceberg pipeline stops being exactly-once, using a provider roster as its
payload: records arriving out of order, corrections landing after the row they
correct, and what a restart actually replays. It is the INGESTION half of the
same problem, and this repository is the RESOLUTION half. The two are
independent and share no code; that one needs Kafka, Flink, MinIO, an Iceberg
catalog and Trino, and this one needs a single Postgres container.

[coverage-decision-service](https://github.com/jkelly-dev1/coverage-decision-service)
makes the same move on a different axis. This repository prices a matching
threshold; that one prices fail-open against fail-closed when a real-time
coverage decision cannot reach its data in time, and ends in a crossover
for the same reason section 2 here does. It needs Postgres and a small
service, and none of this repository's code.

[connector-sync-guarantees](https://github.com/jkelly-dev1/connector-sync-guarantees)
is the step BEFORE this one. This repository takes four rosters that
already disagree; that one measures how much of the disagreement was
manufactured on the way out of the source systems, by running an
incremental connector against a world where every change is known and
counting what the watermark misses. It needs nothing but python3.

All four follow the same rules: no claim without a test, mutation checks on the
tests that matter, and predictions recorded before the run so that the refuted
ones survive. Three of the six predictions here were refuted and all three are
still in the code.

## License

MIT. See `LICENSE`.
