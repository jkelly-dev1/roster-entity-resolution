# Sample run

Captured 2026-08-23 on one Linux machine: Postgres 17.6 in Docker, Python
3.13.7. Every command below was executed exactly as written, in this order,
after `cd stack && docker compose down -v` removed the container and its
volume.

The blocks for experiments 2 and 4, and the two closing gates, were
re-captured on 2026-09-14 against the current tree. Their elapsed times are
this machine's and are slower than the 2026-08-23 originals. Everything else is
the original capture. Every experiment figure was reproduced unchanged:
experiments 1 and 3 byte for byte, and experiments 2 and 4 in every value the
original capture carried.

Two alterations, both stated here and nowhere else. The `docker compose up`
banner is reduced to its final line, because compose reprints each step as it
works and the repetition says nothing. And the closing `check_readme_numbers.py`
block is its output AFTER the three query-plan timings in README.md were updated
to this run; the captured attempt named the previous run's three timings, which
is exactly what that script is for.

The three explain analyze timings are the only figures here that move between
runs. Everything else is identical run to run, which was checked by running the
whole sequence twice and diffing `results/*.json` with the timings excluded.

```
$ cd stack && docker compose up -d && cd ..
 Container reg-postgres  Started 

$ python3 scripts/load.py
schema ... ok
truth.canonical_provider     COPY 20000
roster.source_row            COPY 74926
truth.source_row_link        COPY 74926

providers    20000
source rows  74926
links        74926
manifest    7138eba2ffd9da7af6ee017edd029acd1ac298698ae1c74c5fac3dfc56317df4
load verified against the manifest

$ python3 scripts/normalize.py
read 74926 source rows
COPY 74926

normalized rows  74926
with a surname   74926
with an NPI      53588

$ python3 scripts/exp1_blocking.py
ingest batch(es)            1
source rows             74926
all possible pairs 2806915275
true pairs             107459

dropping blocking indexes ...
full batch, no index         21 ms   Finalize Aggregate / Gather / Partial Aggregate
incremental 50    no index    7.4 ms   Aggregate / Hash Join / Seq Scan
incremental 1000  no index   10.0 ms   Aggregate / Hash Join / Seq Scan

creating blocking indexes ...
full batch, indexed          20 ms   Finalize Aggregate / Gather / Partial Aggregate
incremental 50    indexed     0.7 ms   Aggregate / Merge Join / Index Only Scan using idx_blk_npi
incremental 1000  indexed    11.4 ms   Aggregate / Hash Join / Seq Scan

npi_exact      pairs      51013  true   51013  completeness 0.4747  reduction 0.999982
zip_surname4   pairs      48412  true   39670  completeness 0.3692  reduction 0.999983
soundex_state  pairs    3610478  true  102608  completeness 0.9549  reduction 0.998714
phone_exact    pairs      45926  true   45917  completeness 0.4273  reduction 0.999984
union          pairs    3614341  true  106150  completeness 0.9878  reduction 0.998712

clearinghouse  rows  19403  npi  19403  zip  19403  phone  19403  soundex  19403
license_board  rows  19617  npi  13771  zip      0  phone      0  soundex  19617
payer_feed     rows  20498  npi  17360  zip  20498  phone  20498  soundex  20498
site_scrape    rows  15408  npi   3054  zip  15408  phone  15408  soundex  15408

materializing the union into roster.candidate_pair as 'union' ...
stored 3614341 candidate pairs

prediction: REFUTED (measured 0.4747 against 0.95)
wrote results/exp1_blocking.json

$ python3 scripts/exp2_threshold.py
loading rows ...
  74926 normalized rows
scoring candidate pairs ...
  500000 pairs, 2s
  1000000 pairs, 4s
  1500000 pairs, 5s
  2000000 pairs, 7s
  2500000 pairs, 8s
  3000000 pairs, 10s
  3500000 pairs, 11s
  3614341 pairs scored in 12s
  fit set: 52712 matches, 1768615 non-matches
  evaluation half: 1793014 pairs scored, 53438 true; 54092 true pairs exist
  recall is capped at 0.9879 by blocking

F1-optimal threshold 0.385  precision 0.9876  recall 0.9856  F1 0.9866
cost  1:1  optimal threshold   0.385  cost     1448   F1 threshold costs     1448  (+0)
cost  3:1  optimal threshold   0.385  cost     2782   F1 threshold costs     2782  (+0)
cost 10:1  optimal threshold   8.382  cost     5919   F1 threshold costs     7451  (+1532)
cost 30:1  optimal threshold   9.715  cost    11924   F1 threshold costs    20791  (+8867)

review band, priced at 10:1
  width    0%  queue       0 (     0.0 per 10k providers)  cost    5919  break-even 0.0000
  width    2%  queue     286 (   286.0 per 10k providers)  cost    5803  break-even 0.4056
  width    5%  queue   13218 ( 13218.0 per 10k providers)  cost    2873  break-even 0.2304
  width   10%  queue   15635 ( 15635.0 per 10k providers)  cost     818  break-even 0.3263
  width   15%  queue   16065 ( 16065.0 per 10k providers)  cost     776  break-even 0.3201
  width   20%  queue   35348 ( 35348.0 per 10k providers)  cost     671  break-even 0.1485
  width   30%  queue   63188 ( 63188.0 per 10k providers)  cost     654  break-even 0.0833
  width   40%  queue  103181 (103181.0 per 10k providers)  cost     654  break-even 0.0510
  marginal break-even by width: 2%=0.4056, 5%=0.2266, 10%=0.8502, 15%=0.0977, 20%=0.0054, 30%=0.0006, 40%=0.0

cluster damage
  thr -20.000  accepted  125816  false  72378 (0.5753)  clusters   6316  welded  1802  providers welded  5560 (0.5560)  worst   213  
  thr -12.000  accepted   99058  false  45620 (0.4605)  clusters   6569  welded  1774  providers welded  5280 (0.5280)  worst   109  
  thr  -8.000  accepted   73466  false  20045 (0.2728)  clusters   7683  welded  1819  providers welded  4212 (0.4212)  worst    15  
  thr  -5.000  accepted   73439  false  20018 (0.2726)  clusters   7683  welded  1819  providers welded  4212 (0.4212)  worst    15  
  thr  -3.000  accepted   71356  false  17935 (0.2513)  clusters   7855  welded  1745  providers welded  3966 (0.3966)  worst     6  
  thr  -1.000  accepted   54081  false    768 (0.0142)  clusters  10019  welded    62  providers welded   124 (0.0124)  worst     2  
  thr   0.385  accepted   53978  false    667 (0.0124)  clusters  10034  welded    47  providers welded    94 (0.0094)  worst     2  f1_optimal cost_optimal_1_to_1 cost_optimal_3_to_1
  thr   2.000  accepted   53929  false    656 (0.0122)  clusters  10037  welded    47  providers welded    94 (0.0094)  worst     2  
  thr   5.000  accepted   51537  false    318 (0.0062)  clusters  10056  welded    47  providers welded    94 (0.0094)  worst     2  
  thr   8.382  accepted   51495  false    302 (0.0059)  clusters  10062  welded    44  providers welded    88 (0.0088)  worst     2  cost_optimal_10_to_1
  thr   9.715  accepted   51251  false    293 (0.0057)  clusters  10105  welded    42  providers welded    84 (0.0084)  worst     2  cost_optimal_30_to_1
  thr  12.000  accepted   38319  false      0 (0.0000)  clusters  13538  welded     0  providers welded     0 (0.0000)  worst     1  
  thr  20.000  accepted   38122  false      0 (0.0000)  clusters  13562  welded     0  providers welded     0 (0.0000)  worst     1  

multi-provider rows (one line, two doctors): 133
  evaluation pairs touching one: 7093 of 1793014
  accepted at the 10:1 operating point: 178, of which 2 are false
  they are 0.66% of the false pairs accepted there

prediction A (F1 is not cost-optimal): held
prediction B (cluster damage exceeds pair error): held
wrote results/exp2_threshold.json  (28s)

$ python3 scripts/exp3_survivorship.py
clustering at the cost_optimal_10_to_1 threshold 8.382
  accepted 102411 pairs in 9s
  20030 clusters
  2517 providers are listed twice by some source

field            first_non_null    most_recent       majority_vote     source_priority 
npi              0.9871            0.9871            0.9871            0.9871          
first_name       0.5540            0.5422            0.5834            0.9657          
last_name        0.9445            0.9447            0.9719            0.9653          
credential       0.9625            0.9562            0.9908            0.9955          
street           0.8733            0.8803            0.9572            0.9504          
suite            0.9160            0.9180            0.9301            0.9397          
city             0.9924            0.9924            0.9924            0.9924          
state            0.9998            0.9980            0.9997            0.9998          
zip              0.8748            0.8814            0.9576            0.9508          
phone            0.9885            0.9760            0.9883            0.9525          
specialty        1.0000            1.0000            1.0000            1.0000          
network_status   0.9402            0.9402            0.9402            0.9402          
MEAN             0.9194            0.9181            0.9416            0.9700          

lineage: COPY 227755
lineage invariant: 227755 field values checked, 0 violation(s)
wrote results/exp3_lineage_sample.json (456 rows)
prediction: REFUTED (best is source_priority)
wrote results/exp3_survivorship.json  (11s)

$ python3 scripts/load.py --batch2
COPY 4819
COPY 4819
clearinghouse     805 new rows
payer_feed       1154 new rows
site_scrape      2860 new rows
batch 2: 4819 new rows

$ python3 scripts/normalize.py --batch 2
read 4819 source rows
COPY 4819

normalized rows  79745
with a surname   79745
with an NPI      55923

$ python3 scripts/exp1_blocking.py --batches 1,2 --strategy union_b12 --no-result
ingest batch(es)          1,2
source rows             79745
all possible pairs 3179592640
true pairs             123736

dropping blocking indexes ...
full batch, no index         23 ms   Finalize Aggregate / Gather / Partial Aggregate
incremental 50    no index   10.9 ms   Aggregate / Hash Join / Seq Scan
incremental 1000  no index   12.0 ms   Aggregate / Hash Join / Seq Scan

creating blocking indexes ...
full batch, indexed          26 ms   Finalize Aggregate / Gather / Partial Aggregate
incremental 50    indexed     1.4 ms   Aggregate / Merge Join / Index Only Scan using idx_blk_npi
incremental 1000  indexed    13.4 ms   Aggregate / Hash Join / Seq Scan

npi_exact      pairs      57302  true   57302  completeness 0.4631  reduction 0.999982
zip_surname4   pairs      59289  true   48941  completeness 0.3955  reduction 0.999981
soundex_state  pairs    4094738  true  118210  completeness 0.9553  reduction 0.998712
phone_exact    pairs      57005  true   56996  completeness 0.4606  reduction 0.999982
union          pairs    4099232  true  122320  completeness 0.9886  reduction 0.998711

clearinghouse  rows  20208  npi  20208  zip  20208  phone  20208  soundex  20208
license_board  rows  19617  npi  13771  zip      0  phone      0  soundex  19617
payer_feed     rows  21652  npi  18334  zip  21652  phone  21652  soundex  21652
site_scrape    rows  18268  npi   3610  zip  18268  phone  18268  soundex  18268

materializing the union into roster.candidate_pair as 'union_b12' ...
stored 4099232 candidate pairs

--no-result: results/exp1_blocking.json left untouched

$ python3 scripts/exp4_override_stability.py
ingest 1 only ...
  74926 rows, 20030 clusters
building overrides from what run 1 got wrong ...
  200 merge, 100 pin, 200 split
ingest 1 + 2 ...
  79745 rows, 19997 clusters

scheme           retained       lost   misapplied
cluster_id            229          0          271
natural_key           500          0            0

run 1 clusters that genuinely gained or lost a row: 4527 of 20030
run 1 cluster IDS no longer holding their original set: 18005 of 20030
  a DIFFERENT set now sits at that id: 17972
  NO cluster exists at that id at all:  33
misapplied onto a cluster sharing no row with the original: 271
pins now contradicted by a corrected source row: 39 of 100
  a split meant for provider 1308 landed on provider 1307
  a split meant for provider 1564 landed on provider 1563
  a split meant for provider 1708 landed on provider 1707
  a split meant for provider 1737 landed on provider 1736
  a split meant for provider 1909 landed on provider 1908

prediction A (overrides survive): REFUTED
prediction B (cluster-id keying misapplies): held
wrote results/exp4_override_stability.json  (69s)

$ python -m pytest -q
........................................................................ [ 54%]
...........................................................              [100%]
131 passed in 0.10s

$ python3 scripts/check_readme_numbers.py
120 figures re-derived from results/*.json and checked against README.md
all present
```
