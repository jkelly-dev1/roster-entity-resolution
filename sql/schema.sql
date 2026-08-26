-- Schema for the roster entity resolution lab.
--
-- Ground truth lives in its own schema and the resolver never reads it.
-- Every table the pipeline is allowed to touch is in `roster`. Everything the
-- answer key needs is in `truth`. The separation is not decoration: an entity
-- resolution measurement that can see the labels it is being scored against
-- is worth nothing, and the cheapest way to guarantee it cannot is to make
-- the read a schema-qualified one that stands out in any diff.

DROP SCHEMA IF EXISTS roster CASCADE;
DROP SCHEMA IF EXISTS truth CASCADE;

CREATE SCHEMA roster;
CREATE SCHEMA truth;

-- soundex() and levenshtein() for the blocking strategies. Jaro-Winkler is
-- NOT in this extension and is computed in Python; see scripts/compare.py.
CREATE EXTENSION IF NOT EXISTS fuzzystrmatch;


-- ---------------------------------------------------------------------------
-- THE ANSWER KEY
-- ---------------------------------------------------------------------------

-- The 20,000 providers the four rosters are corrupted views of. Values here
-- are what a perfect golden record would contain.
CREATE TABLE truth.canonical_provider (
    provider_id     integer PRIMARY KEY,
    npi             char(10)     NOT NULL,
    first_name      text         NOT NULL,   -- the legal first name
    nickname        text,                    -- NULL when the provider has none
    last_name       text         NOT NULL,   -- the current surname
    -- The surname before a legal change, and which sources still carry it.
    -- NOT a typo: two of the four sources are correct about a name that is no
    -- longer current, which is a different problem from one being wrong.
    prior_last_name text,
    name_changed    boolean      NOT NULL,
    credential      text         NOT NULL,
    street          text         NOT NULL,
    suite           text,
    city            text         NOT NULL,
    state           char(2)      NOT NULL,
    zip             char(5)      NOT NULL,
    phone           char(10)     NOT NULL,   -- digits only
    specialty       text         NOT NULL,
    network_status  text         NOT NULL,
    -- TRUE for the providers who moved practice. The clearinghouse feed did
    -- not notice, so its address is the previous one; every other source and
    -- this row carry the current one.
    has_moved       boolean      NOT NULL
);

-- Which canonical provider each source row was generated from. This is the
-- only reason precision and recall are measurable here rather than estimated.
CREATE TABLE truth.source_row_link (
    source_system   text     NOT NULL,
    source_row_id   integer  NOT NULL,
    provider_id     integer  NOT NULL REFERENCES truth.canonical_provider,
    -- A site_scrape row that names two providers on one line. The row's
    -- address, phone and specialty belong to the provider named here; the
    -- second name is a passenger. Results report these separately rather than
    -- letting them move precision quietly, because no pairwise resolver can
    -- be right about a row that is about two people.
    multi_provider  boolean  NOT NULL DEFAULT false,
    PRIMARY KEY (source_system, source_row_id)
);

CREATE INDEX ON truth.source_row_link (provider_id);


-- ---------------------------------------------------------------------------
-- What the pipeline is allowed to see
-- ---------------------------------------------------------------------------

-- The four rosters, landed as they arrived. EVERY COLUMN IS text AND
-- NULLABLE, deliberately: a source that promises 10-digit NPIs and delivers
-- 15% nulls is the normal case, and a schema that refuses the file is a
-- schema that never sees the problem this repository is about.
CREATE TABLE roster.source_row (
    source_system   text    NOT NULL,
    source_row_id   integer NOT NULL,
    ingest_batch    integer NOT NULL,       -- Which file this row arrived in
    -- when the source observed the row, not when the fact became true. A
    -- most-recent-wins survivorship rule reads this column and is wrong
    -- exactly to the extent the two differ; experiment 3 measures by how much.
    observed_at     date    NOT NULL,
    npi             text,
    name_raw        text,                   -- as the source formats it
    credential      text,
    street          text,
    suite           text,
    city            text,
    state           text,
    zip             text,
    phone           text,                   -- as the source formats it
    specialty       text,
    network_status  text,
    license_state   text,
    PRIMARY KEY (source_system, source_row_id)
);

-- The normalized view the comparators actually run against. Written by
-- scripts/normalize.py, not by a trigger: the normalization rules are the
-- thing under measurement in experiment 1 and they have to be readable as
-- code rather than buried in DDL.
CREATE TABLE roster.normalized_row (
    source_system   text    NOT NULL,
    source_row_id   integer NOT NULL,
    npi             char(10),               -- NULL when absent or malformed
    given_name      text,                   -- first token, upper case
    family_name     text,                   -- surname, upper case
    given_soundex   text,
    family_soundex  text,
    street_tokens   text[],                 -- abbreviations folded
    suite           text,
    city            text,
    state           char(2),
    zip             char(5),
    phone           char(10),               -- digits only, NULL if not 10
    specialty       text,
    PRIMARY KEY (source_system, source_row_id),
    FOREIGN KEY (source_system, source_row_id)
        REFERENCES roster.source_row (source_system, source_row_id)
);

-- Candidate pairs surviving a blocking strategy. One row per (strategy, pair).
-- The pair is stored with the lexicographically smaller key first so that a
-- pair produced by two strategies is the same pair in both.
CREATE TABLE roster.candidate_pair (
    strategy        text    NOT NULL,
    a_system        text    NOT NULL,
    a_row_id        integer NOT NULL,
    b_system        text    NOT NULL,
    b_row_id        integer NOT NULL,
    PRIMARY KEY (strategy, a_system, a_row_id, b_system, b_row_id)
);

-- The clusters a threshold produced, and the golden record built from each.
CREATE TABLE roster.cluster_member (
    run_id          text    NOT NULL,
    cluster_id      integer NOT NULL,
    source_system   text    NOT NULL,
    source_row_id   integer NOT NULL,
    PRIMARY KEY (run_id, source_system, source_row_id)
);

CREATE INDEX ON roster.cluster_member (run_id, cluster_id);

-- Field-level lineage, one row per field of every golden record. Not a
-- feature to demonstrate: tests/test_survivorship.py::test_every_shipped_lineage_row_names_a_source_row_that_holds_its_value asserts that every value here
-- appears in the source row it names, which is the only check that catches a
-- survivorship rule that invents a value or carries one from the wrong row.
CREATE TABLE roster.golden_field (
    run_id          text    NOT NULL,
    cluster_id      integer NOT NULL,
    field           text    NOT NULL,
    value           text,
    -- where it came from
    source_system   text,
    source_row_id   integer,
    rule            text    NOT NULL,       -- the survivorship rule that chose it
    PRIMARY KEY (run_id, cluster_id, field)
);

-- The human override layer.
--
-- Keyed on natural keys, not on a cluster id. A cluster id is assigned by the
-- run: re-run with one new row and the numbering shifts, so an override keyed
-- on it is either dropped or applied to a provider it was never about.
-- Experiment 4 measures both schemes, so the naive column is present and is
-- populated alongside rather than instead.
CREATE TABLE roster.override (
    override_id     serial  PRIMARY KEY,
    kind            text    NOT NULL
        CHECK (kind IN ('split', 'merge', 'pin')),
    -- the stable key: which two source rows the decision is about
    a_system        text    NOT NULL,
    a_row_id        integer NOT NULL,
    b_system        text,                   -- NULL for a pin
    b_row_id        integer,
    field           text,                   -- Pin only
    value           text,                   -- pin only
    -- the naive key, recorded for comparison and never used to apply the
    -- override. Experiment 4 replays the same decisions through both schemes
    -- over two ingests and counts what each one loses and misapplies.
    cluster_id_at_creation  integer,
    created_in_run  text    NOT NULL
);
