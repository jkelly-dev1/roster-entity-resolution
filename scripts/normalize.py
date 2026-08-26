"""Turn four differently-broken rosters into one comparable shape.

    python3 scripts/normalize.py           # fill roster.normalized_row

Normalization is a matching decision, not plumbing. Every rule here decides
which pairs a comparator can still see: folding ST and STREET together makes
two addresses comparable, and splitting a name on the wrong character makes
two rows for the same doctor look like two doctors. The rules live in this
file as pure functions so the test suite can exercise them without a database
and so a reader can disagree with one of them specifically.

This file does not import the generator. A normalizer that knows how the data
was corrupted is a normalizer that cannot be wrong, and every recall figure it
produced would be a measurement of nothing. Its abbreviation table is written
independently, the way a real one is, and it is allowed to be incomplete.
"""

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import lab


# ---------------------------------------------------------------------------
# NAMES
# ---------------------------------------------------------------------------

# The credential suffix is part of the name field on a scraped page, and
# leaving it in makes "Barb Silva, DO" and "Barb Silva" different strings on
# every character after the surname.
# A trailing word boundary cannot be used here. "m.d." Ends in a period, and
# \b after a period requires a word character that is not there, so a pattern
# written the obvious way matches "MD" and silently fails on every dotted
# form. The credential is instead required to be the FINAL TOKEN, preceded by
# a comma or whitespace, which is how all four sources write it.
CREDENTIAL_SUFFIX = re.compile(
    r"(?:,\s*|\s+)(?:M\.?\s?D\.?|D\.?\s?O\.?|N\.?\s?P\.?"
    r"|P\.?\s?A\.?|Ph\.?\s?D\.?)\s*$", re.I)

# Honorifics a practice website adds and a payer feed does not.
HONORIFIC = re.compile(r"^\s*(Dr\.?|Doctor|Prof\.?)\s+", re.I)


def split_persons(name_raw):
    """A scraped row that names two providers, split into the names it holds.

    The first name on the row is the one the row is about. The address, phone
    and specialty belong to that provider; the second is a passenger. Nothing
    downstream can be right about the passenger, and the results report those
    rows separately rather than letting them move precision quietly.
    """
    if not name_raw:
        return []
    return [p.strip() for p in re.split(r"\s+and\s+", name_raw) if p.strip()]


def parse_name(source_system, name_raw):
    """(given, family), upper case, or (None, None).

    Four sources, three formats. The payer feed writes "LAST, FIRST"; the
    others write "First Last" with varying decoration. Guessing the format
    from the presence of a comma would be one rule instead of three, and it
    would silently mis-split any surname that legitimately contains one.
    """
    if not name_raw:
        return None, None
    name = split_persons(name_raw)[0]
    name = CREDENTIAL_SUFFIX.sub("", name)
    name = HONORIFIC.sub("", name).strip()
    if not name:
        return None, None

    if source_system == "payer_feed":
        if "," not in name:
            return None, None
        family, _, given = name.partition(",")
        return given.strip().upper() or None, family.strip().upper() or None

    parts = name.split()
    if len(parts) < 2:
        return None, None
    return parts[0].upper(), parts[-1].upper()


# A short nickname table, and it is deliberately short. The license board
# carries legal first names and the other three carry whatever the practice
# uses, so without this table every Robert/Bob pair scores as two different
# people on the given name. Section 1 of README.md reports what it buys, which
# is the only reason to have it rather than an assumption that it helps.
#
# It maps the short form to the legal one, never the reverse: several legal
# names share a short form and a table that expanded them would have to guess.
NICKNAMES = {
    "BOB": "ROBERT", "BILL": "WILLIAM", "MIKE": "MICHAEL", "RICK": "RICHARD",
    "TOM": "THOMAS", "JOE": "JOSEPH", "DAN": "DANIEL", "MATT": "MATTHEW",
    "TONY": "ANTHONY", "BEN": "BENJAMIN", "NICK": "NICHOLAS", "ALEX":
    "ALEXANDER", "GREG": "GREGORY", "TIM": "TIMOTHY", "TED": "THEODORE",
    "FRED": "FREDERICK", "JON": "JONATHAN", "CHARLIE": "CHARLES",
    "CHRIS": "CHRISTOPHER", "KATE": "KATHERINE", "LIZ": "ELIZABETH",
    "PEGGY": "MARGARET", "JEN": "JENNIFER", "PAT": "PATRICIA",
    "DEBBIE": "DEBORAH", "BARB": "BARBARA", "SUE": "SUSAN",
    "BECKY": "REBECCA", "KIM": "KIMBERLY", "STEPH": "STEPHANIE",
    "VICKY": "VICTORIA", "JESS": "JESSICA", "CINDY": "CYNTHIA",
    "SAM": "SAMANTHA", "RONNIE": "VERONICA", "CILLA": "PRISCILLA",
}


def canonical_given(given):
    """The legal first name a short form stands for, or the input unchanged."""
    if not given:
        return given
    return NICKNAMES.get(given, given)


# ---------------------------------------------------------------------------
# ADDRESSES
# ---------------------------------------------------------------------------

# Written independently of the generator and allowed to be incomplete, because
# a real abbreviation table always is. Anything not in here survives as
# whatever the source wrote, which costs a token overlap rather than crashing.
STREET_TYPE_FOLD = {
    "ST": "STREET", "STR": "STREET", "STREET": "STREET",
    "AVE": "AVENUE", "AV": "AVENUE", "AVENUE": "AVENUE",
    "RD": "ROAD", "ROAD": "ROAD",
    "BLVD": "BOULEVARD", "BOUL": "BOULEVARD", "BOULEVARD": "BOULEVARD",
    "DR": "DRIVE", "DRV": "DRIVE", "DRIVE": "DRIVE",
    "LN": "LANE", "LANE": "LANE",
    "PKWY": "PARKWAY", "PKY": "PARKWAY", "PARKWAY": "PARKWAY",
    "CT": "COURT", "CRT": "COURT", "COURT": "COURT",
    "PL": "PLACE", "PLACE": "PLACE",
    "TER": "TERRACE", "TERRACE": "TERRACE",
    "CIR": "CIRCLE", "CIRCLE": "CIRCLE",
    "HWY": "HIGHWAY", "HIGHWAY": "HIGHWAY",
    "N": "NORTH", "S": "SOUTH", "E": "EAST", "W": "WEST",
    "NORTH": "NORTH", "SOUTH": "SOUTH", "EAST": "EAST", "WEST": "WEST",
}

# A suite that a scraped page folded into the street line. Pulling it back out
# is what stops "8864 PARKSIDE PARKWAY SUITE 203" and "8864 PARKSIDE PARKWAY"
# from disagreeing on a token that is not part of the street at all.
SUITE_IN_STREET = re.compile(
    r"\s*\b(?:SUITE|STE|APT|UNIT|#)\s*\.?\s*([0-9A-Z-]+)\s*$", re.I)

PUNCT = re.compile(r"[^A-Z0-9 ]")


def split_suite(street):
    """(street without the suite, the suite or None)."""
    if not street:
        return street, None
    m = SUITE_IN_STREET.search(street)
    if not m:
        return street, None
    return street[:m.start()].rstrip(), "SUITE " + m.group(1).upper()


def street_tokens(street):
    """Upper case, punctuation dropped, street types folded, order kept.

    Order is kept because the comparator is a set overlap and does not use it,
    and a later comparator that wants sequence should not have to regenerate
    this column.
    """
    if not street:
        return []
    s = PUNCT.sub(" ", street.upper())
    return [STREET_TYPE_FOLD.get(t, t) for t in s.split() if t]


def normalize_suite(suite):
    if not suite:
        return None
    s = PUNCT.sub(" ", suite.upper())
    s = re.sub(r"\b(STE|APT|UNIT)\b", "SUITE", s)
    s = " ".join(s.split())
    return s or None


# ---------------------------------------------------------------------------
# IDENTIFIERS
# ---------------------------------------------------------------------------

def clean_npi(npi):
    """Ten digits, or None.

    None and wrong are not the same thing and this is where the difference is
    decided. A malformed NPI becomes absent rather than becoming a key that
    blocks with nothing, which keeps "how many rows carry a usable NPI"
    answerable from this column alone.
    """
    if not npi:
        return None
    d = re.sub(r"\D", "", npi)
    return d if len(d) == 10 else None


def clean_phone(phone):
    """Ten digits, or None. Four source formats collapse to one here."""
    if not phone:
        return None
    d = re.sub(r"\D", "", phone)
    if len(d) == 11 and d.startswith("1"):
        d = d[1:]
    return d if len(d) == 10 else None


def clean_zip(z):
    if not z:
        return None
    d = re.sub(r"\D", "", z)
    return d[:5] if len(d) >= 5 else None


def clean_state(s):
    if not s:
        return None
    s = s.strip().upper()
    return s if len(s) == 2 and s.isalpha() else None


def normalize_row(row):
    """One source row, in the shape roster.normalized_row wants."""
    given, family = parse_name(row["source_system"], row.get("name_raw"))
    street, folded_suite = split_suite(row.get("street"))
    suite = normalize_suite(row.get("suite")) or folded_suite
    return {
        "source_system": row["source_system"],
        "source_row_id": row["source_row_id"],
        "npi": clean_npi(row.get("npi")),
        "given_name": given,
        "family_name": family,
        "street_tokens": street_tokens(street),
        "suite": suite,
        "city": (row.get("city") or "").upper().strip() or None,
        "state": clean_state(row.get("state")),
        "zip": clean_zip(row.get("zip")),
        "phone": clean_phone(row.get("phone")),
        "specialty": (row.get("specialty") or "").strip() or None,
    }


# ---------------------------------------------------------------------------
# LOADING
# ---------------------------------------------------------------------------

def pg_array(tokens):
    """A text[] literal. Tokens here are A-Z0-9 only, and the escape is still
    written out: a normalizer that later stops stripping punctuation would
    otherwise start producing a literal Postgres silently mis-parses."""
    return "{" + ",".join('"%s"' % t.replace("\\", "\\\\").replace('"', '\\"')
                          for t in tokens) + "}"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--batch", type=int, default=None,
                    help="normalize only rows from this ingest batch")
    a = ap.parse_args()

    where = "" if a.batch is None else " WHERE ingest_batch = %d" % a.batch
    rows = lab.query_json(
        "SELECT source_system, source_row_id, npi, name_raw, street, suite,"
        " city, state, zip, phone, specialty FROM roster.source_row" + where)
    print("read %d source rows" % len(rows))

    out = [normalize_row(r) for r in rows]

    # Soundex comes from POSTGRES, not from Python. It is a blocking key, and
    # a key computed one way on load and another way in the join is a bug that
    # presents as a blocking strategy with mysteriously poor completeness.
    lines = []
    for r in out:
        lines.append("\t".join([
            r["source_system"], str(r["source_row_id"]),
            r["npi"] or "\\N", r["given_name"] or "\\N",
            r["family_name"] or "\\N", pg_array(r["street_tokens"]),
            r["suite"] or "\\N", r["city"] or "\\N", r["state"] or "\\N",
            r["zip"] or "\\N", r["phone"] or "\\N", r["specialty"] or "\\N"]))

    if a.batch is None:
        lab.psql("TRUNCATE roster.normalized_row;")
    cols = ("source_system, source_row_id, npi, given_name, family_name,"
            " street_tokens, suite, city, state, zip, phone, specialty")
    import subprocess
    p = subprocess.run(
        ["docker", "exec", "-i", lab.CONTAINER, "psql", "-v",
         "ON_ERROR_STOP=1", "-U", lab.DB_USER, "-d", lab.DB_NAME,
         "-c", "\\copy roster.normalized_row (%s) FROM STDIN" % cols],
        input="\n".join(lines).encode("utf-8"), capture_output=True)
    if p.returncode != 0:
        print(p.stderr.decode(), file=sys.stderr)
        return 1
    print(p.stdout.decode().strip())

    lab.psql("""
        UPDATE roster.normalized_row
           SET given_soundex  = soundex(given_name),
               family_soundex = soundex(family_name)
         WHERE family_name IS NOT NULL;
        ANALYZE roster.normalized_row;
    """)

    n = int(lab.scalar("SELECT count(*) FROM roster.normalized_row;"))
    named = int(lab.scalar("SELECT count(*) FROM roster.normalized_row"
                           " WHERE family_name IS NOT NULL;"))
    with_npi = int(lab.scalar("SELECT count(npi) FROM roster.normalized_row;"))
    print()
    print("normalized rows %6d" % n)
    print("with a surname  %6d" % named)
    print("with an NPI     %6d" % with_npi)
    if named != n:
        print("A ROW WITHOUT A SURNAME CANNOT BE BLOCKED BY ANY NAME"
              " STRATEGY. %d rows." % (n - named))
    return 0


if __name__ == "__main__":
    sys.exit(main())
