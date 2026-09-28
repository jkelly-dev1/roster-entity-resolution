"""Shared helpers: reaching Postgres, and writing a result file.

The database is reached through `docker exec`, not through a driver. Nothing
in this repository needs a Python Postgres driver, so CI installs pytest and
nothing else and a reader can run the offline suite with a bare interpreter.
The cost is that every query goes through psql's text output, so
`query_json` asks Postgres to do the serializing.
"""

import json
import os
import subprocess

CONTAINER = "reg-postgres"
DB_USER = "roster-local"
DB_NAME = "roster"

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
RESULTS = os.path.join(REPO, "results")
DATA = os.path.join(REPO, "data")


class PsqlError(RuntimeError):
    pass


def _run(args, stdin=None):
    p = subprocess.run(args, input=stdin, capture_output=True, text=True)
    if p.returncode != 0:
        raise PsqlError((p.stderr or p.stdout).strip())
    # psql exits 0 on a failed statement unless told otherwise, so ON_ERROR_STOP
    # is set on every call below. Anything on stderr is still worth surfacing.
    if "ERROR:" in p.stderr:
        raise PsqlError(p.stderr.strip())
    return p.stdout


def psql(sql, quiet=True):
    """Run SQL. Returns psql's stdout."""
    args = ["docker", "exec", "-i", CONTAINER, "psql",
            "-v", "ON_ERROR_STOP=1", "-U", DB_USER, "-d", DB_NAME]
    if quiet:
        args += ["-q"]
    return _run(args + ["-f", "-"], stdin=sql)


def psql_file(path):
    with open(path, encoding="utf-8") as fh:
        return psql(fh.read())


def scalar(sql):
    """One value from a one-row, one-column query."""
    out = _run(["docker", "exec", "-i", CONTAINER, "psql",
                "-v", "ON_ERROR_STOP=1", "-U", DB_USER, "-d", DB_NAME,
                "-t", "-A", "-f", "-"], stdin=sql)
    return out.strip()


def require_first_ingest_only(experiment):
    """Refuse when the second ingest is loaded.

    Experiments 2 and 3 measure the first ingest, and their queries read every
    loaded row. After `load.py --batch2` those queries take in batch 2 as
    well, which moves the recall denominator and the two-site count, and the
    input manifest covers batch 1 only, so nothing else would notice.
    """
    loaded = int(scalar(
        "SELECT count(*) FROM roster.source_row WHERE ingest_batch <> 1;"))
    if loaded:
        raise PsqlError(
            "%s measures the first ingest, and %d rows from a later ingest "
            "are loaded. Run scripts/load.py and scripts/normalize.py again "
            "to reload batch 1 alone." % (experiment, loaded))


def query_json(sql):
    """Rows as a list of dicts.

    Postgres serializes, not psql: a text-mode parse would guess at NULL
    against the empty string, and this repository has columns where the
    difference between "absent" and "blank" is the measurement.

    The newline before `) t;` is required. Without it the closing paren
    and semicolon would be appended directly after the caller's last
    character. A `--` line comment runs to the end of its line, and the most
    carefully commented queries in this repository end in one (the comment
    explaining why an ORDER BY must never be removed goes under the ORDER BY),
    so the comment would swallow the wrapper's closing paren and Postgres
    would report "syntax error at end of input". The tests and the README
    checker read the committed results, not the script, so
    tests/test_query_wrapping.py tests the wrapper itself.
    """
    wrapped = ("SELECT coalesce(json_agg(t), '[]'::json)::text "
               "FROM (%s\n) t;" % sql.rstrip().rstrip(";"))
    return json.loads(scalar(wrapped))


def copy_csv(path, table, columns):
    """Load a CSV through psql's \\copy, which reads the file on THIS side.

    The container cannot see the repository, so a server-side COPY would need
    the file mounted in and would silently read a stale one if the mount were
    forgotten.
    """
    cmd = "\\copy %s (%s) FROM STDIN WITH (FORMAT csv, HEADER true)" % (
        table, ", ".join(columns))
    with open(path, "rb") as fh:
        p = subprocess.run(
            ["docker", "exec", "-i", CONTAINER, "psql", "-v",
             "ON_ERROR_STOP=1", "-U", DB_USER, "-d", DB_NAME, "-c", cmd],
            input=fh.read(), capture_output=True)
    if p.returncode != 0:
        raise PsqlError(p.stderr.decode().strip())
    return p.stdout.decode().strip()


def input_manifest():
    """The sha256 of the generated input, or None if it has not been written.

    Stamped into every results file. The generated rows are not committed;
    they are a pure function of the seed, so this hash is what lets a reader
    who regenerates prove they hold the same input these numbers came from,
    rather than take it on trust.
    """
    try:
        with open(os.path.join(DATA, "manifest.json"), encoding="utf-8") as fh:
            return json.load(fh)["sha256"]
    except (OSError, KeyError, ValueError):
        return None


def write_result(name, payload):
    """Write results/<name>.json, which is the evidence the README cites.

    Sorted keys and a trailing newline so a re-run produces a diff only where
    a MEASUREMENT changed, rather than wherever a dict happened to iterate.
    """
    payload = dict(payload, input_manifest_sha256=input_manifest())
    os.makedirs(RESULTS, exist_ok=True)
    path = os.path.join(RESULTS, name + ".json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
        fh.write("\n")
    return path


def read_result(name):
    with open(os.path.join(RESULTS, name + ".json"), encoding="utf-8") as fh:
        return json.load(fh)
