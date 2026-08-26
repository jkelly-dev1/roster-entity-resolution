"""Create the schema and load the generated rosters into Postgres.

    python3 scripts/load.py            # generate if needed, then load
    python3 scripts/load.py --regen    # regenerate the CSVs first

Refuses rather than loading something else. If data/manifest.json does not
match what the generator produces right now, the CSVs on disk came from a
different generator and loading them would put a measurement in results/ that
no clone can reproduce. Section 5A of this repository's own discipline: a
check that cannot run must refuse, never pass quietly.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import generate_roster as gen
import lab

SQL_SCHEMA = os.path.join(lab.REPO, "sql", "schema.sql")


def current_manifest():
    providers, rows, links = gen.generate()
    return gen.manifest(providers, rows, links), providers, rows, links


def load_batch2():
    """Append the second ingest. Refuses if it is already there, because
    loading it twice would double every cluster and the experiment that reads
    it measures cluster membership."""
    already = int(lab.scalar(
        "SELECT count(*) FROM roster.source_row WHERE ingest_batch = 2;"))
    if already:
        print("REFUSING: %d batch 2 rows are already loaded. Re-run "
              "scripts/load.py to start from a clean schema." % already,
              file=sys.stderr)
        return 1
    providers, rows1, _ = gen.generate()
    rows2, links2 = gen.generate_batch2(providers, rows1)
    gen.write_csv(os.path.join(lab.DATA, "source_row_batch2.csv"),
                  gen.ROW_COLS, rows2)
    gen.write_csv(os.path.join(lab.DATA, "source_row_link_batch2.csv"),
                  gen.LINK_COLS, links2)
    print(lab.copy_csv(os.path.join(lab.DATA, "source_row_batch2.csv"),
                       "roster.source_row", gen.ROW_COLS))
    print(lab.copy_csv(os.path.join(lab.DATA, "source_row_link_batch2.csv"),
                       "truth.source_row_link", gen.LINK_COLS))
    lab.psql("ANALYZE roster.source_row; ANALYZE truth.source_row_link;")
    by_src = {}
    for r in rows2:
        by_src[r["source_system"]] = by_src.get(r["source_system"], 0) + 1
    for s in sorted(by_src):
        print("%-14s %6d new rows" % (s, by_src[s]))
    print("batch 2: %d new rows" % len(rows2))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--regen", action="store_true",
                    help="rewrite the CSVs before loading")
    ap.add_argument("--batch2", action="store_true",
                    help="APPEND the second ingest to an already-loaded "
                         "database; does not recreate the schema")
    a = ap.parse_args()

    if a.batch2:
        return load_batch2()

    man_path = os.path.join(lab.DATA, "manifest.json")
    if a.regen or not os.path.isfile(man_path):
        man, providers, rows, links = current_manifest()
        os.makedirs(lab.DATA, exist_ok=True)
        gen.write_csv(os.path.join(lab.DATA, "canonical_provider.csv"),
                      gen.PROVIDER_COLS, providers)
        gen.write_csv(os.path.join(lab.DATA, "source_row.csv"),
                      gen.ROW_COLS, rows)
        gen.write_csv(os.path.join(lab.DATA, "source_row_link.csv"),
                      gen.LINK_COLS, links)
        with open(man_path, "w", encoding="utf-8") as fh:
            json.dump(man, fh, indent=2, sort_keys=True)
            fh.write("\n")
        print("generated %d providers, %d source rows"
              % (man["providers"], man["source_rows"]))
    else:
        with open(man_path, encoding="utf-8") as fh:
            on_disk = json.load(fh)
        man = current_manifest()[0]
        if on_disk["sha256"] != man["sha256"]:
            print("REFUSING TO LOAD. data/manifest.json does not match what "
                  "the generator produces now.", file=sys.stderr)
            print("  on disk  %s" % on_disk["sha256"], file=sys.stderr)
            print("  expected %s" % man["sha256"], file=sys.stderr)
            print("  run with --regen once you know why they differ.",
                  file=sys.stderr)
            return 1
        man = on_disk

    print("schema ...", end=" ", flush=True)
    lab.psql_file(SQL_SCHEMA)
    print("ok")

    for csv_name, table, cols in (
            ("canonical_provider.csv", "truth.canonical_provider",
             gen.PROVIDER_COLS),
            ("source_row.csv", "roster.source_row", gen.ROW_COLS),
            ("source_row_link.csv", "truth.source_row_link", gen.LINK_COLS)):
        out = lab.copy_csv(os.path.join(lab.DATA, csv_name), table, cols)
        print("%-28s %s" % (table, out))

    lab.psql("ANALYZE truth.canonical_provider; ANALYZE truth.source_row_link;"
             " ANALYZE roster.source_row;")

    # The counts are asserted, not printed and trusted. A \copy that loaded
    # 74,925 of 74,926 rows exits 0 and prints the count in a line that is
    # easy to miss.
    loaded = int(lab.scalar("SELECT count(*) FROM roster.source_row;"))
    linked = int(lab.scalar("SELECT count(*) FROM truth.source_row_link;"))
    people = int(lab.scalar("SELECT count(*) FROM truth.canonical_provider;"))
    ok = (loaded == man["source_rows"] and linked == man["source_rows"]
          and people == man["providers"])
    print()
    print("providers   %6d" % people)
    print("source rows %6d" % loaded)
    print("links       %6d" % linked)
    print("manifest    %s" % man["sha256"])
    if not ok:
        print("LOAD IS SHORT. Expected %d providers and %d source rows."
              % (man["providers"], man["source_rows"]), file=sys.stderr)
        return 1
    print("load verified against the manifest")
    return 0


if __name__ == "__main__":
    sys.exit(main())
