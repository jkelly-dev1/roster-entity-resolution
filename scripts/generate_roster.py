"""Deterministically generate 20,000 providers and the four rosters that
disagree about them.

    python3 scripts/generate_roster.py --out data/      # write the CSVs
    python3 scripts/generate_roster.py --manifest       # print the hash only

Every value is a pure function of a seed and a row number. Nothing is drawn
from a global random stream, so a clone reproduces the same bytes, and any
single row can be regenerated without generating the ones before it. That is
what makes the numbers in README.md checkable rather than merely reported.

The corruption is the design. A source that is only a subset of the truth
teaches nothing: every strategy scores the same on it. Each of the four
sources here is wrong in a different way and authoritative about a different
field, which is what makes per-field survivorship a real question and a single
ranked source list an inadequate answer to it.

What this is not. The answer key was invented here, and the corruption model
is a guess at how provider rosters actually go wrong. What transfers to a real
roster is the method and the shape of the tradeoff. No threshold measured
against this generator transfers to anything.
"""

import argparse
import csv
import hashlib
import json
import os
import sys

SEED = "roster-entity-resolution-2026"
N_PROVIDERS = 20000

# Fraction of providers who moved practice. The clearinghouse feed did not
# notice, so it carries the previous address while every other source and the
# answer key carry the current one.
MOVED_FRACTION = 0.12

# How much of the provider population each source knows about, and how often a
# source lists the same provider twice at two practice locations. Both are
# ordinary roster behavior and both change what blocking has to survive.
COVERAGE = {
    "payer_feed": 0.95,
    "license_board": 0.98,
    "site_scrape": 0.72,
    "clearinghouse": 0.97,
}
SECOND_LOCATION = {"payer_feed": 0.08, "site_scrape": 0.08}

# Names and states are corrupted too, and without that the whole of
# experiment 1 is vacuous. Every source carries a surname and a state, so a
# generator that never damages either leaves surname-soundex-plus-state
# blocking at a pair completeness of exactly 1: blocking then costs nothing,
# there is no tradeoff to measure, and the strategy comparison has no content.
# Typos and name changes are also the ordinary case in a real roster, which is
# the reason they belong here rather than a convenience.
SURNAME_TYPO_RATE = 0.03      # Per row, every source
GIVEN_TYPO_RATE = 0.02        # per row, every source
NAME_CHANGE_FRACTION = 0.025  # providers whose surname changed
WRONG_STATE_RATE = 0.015      # payer_feed rows only, plain data entry

# Which sources caught up with a surname change. The licensing board registers
# the legal change and the practice website is edited by the practice, so both
# carry the new name; the payer feed and the clearinghouse are still on the
# old one. That splits the four sources two against two, which is exactly the
# case a single ranked source priority list cannot express.
SOURCES_WITH_CURRENT_SURNAME = ("license_board", "site_scrape")

# How old each source's rows are, in days before the reference date. This is
# the freshness of the FILE, which is not the freshness of the FACT, and
# experiment 3 exists partly to show that they come apart. The clearinghouse
# pushes daily and is therefore the most recently observed source in the
# data, while carrying an address that is twelve percent wrong. Any
# survivorship rule that reads recency as correctness picks it every time.
REFERENCE_DATE = "2026-08-01"
OBSERVED_WITHIN_DAYS = {
    "payer_feed": 30,        # monthly file
    "license_board": 1095,   # renewal cycle, up to three years
    "site_scrape": 90,       # crawled quarterly
    "clearinghouse": 7,      # daily push, and the freshest thing here
}


# ---------------------------------------------------------------------------
# THE DETERMINISTIC STREAM
# ---------------------------------------------------------------------------

def _bits(*parts):
    """64 bits keyed by SEED and by every part of the coordinate.

    Keyed rather than concatenated so that ("a", "bc") and ("ab", "c") cannot
    collide, which is the failure that makes a generator look random while
    silently correlating two fields.
    """
    msg = "|".join(str(p) for p in parts).encode("utf-8")
    return int.from_bytes(
        hashlib.blake2b(msg, digest_size=8, key=SEED.encode()).digest(), "big")


def unit(*parts):
    """A float in [0, 1)."""
    return _bits(*parts) / 2.0 ** 64


def below(p, *parts):
    """True with probability p, decided by the coordinate alone."""
    return unit(*parts) < p


def pick(seq, *parts):
    return seq[_bits(*parts) % len(seq)]


def digits(n, *parts):
    return str(_bits(*parts) % (10 ** n)).zfill(n)


# ---------------------------------------------------------------------------
# POOLS
# ---------------------------------------------------------------------------

# (Legal first name, the nickname it is commonly shortened to or None).
# The nicknames are the point. The license board carries legal names and the
# other three carry whatever the practice uses, so a comparator that treats
# Katherine and Kate as unrelated strings loses those pairs entirely.
FIRST_NAMES = [
    ("Robert", "Bob"), ("Katherine", "Kate"), ("William", "Bill"),
    ("Elizabeth", "Liz"), ("Michael", "Mike"), ("Margaret", "Peggy"),
    ("Richard", "Rick"), ("Jennifer", "Jen"), ("Christopher", "Chris"),
    ("Patricia", "Pat"), ("Thomas", "Tom"), ("Deborah", "Debbie"),
    ("Charles", "Charlie"), ("Barbara", "Barb"), ("Joseph", "Joe"),
    ("Susan", "Sue"), ("Daniel", "Dan"), ("Rebecca", "Becky"),
    ("Matthew", "Matt"), ("Kimberly", "Kim"), ("Anthony", "Tony"),
    ("Stephanie", "Steph"), ("Benjamin", "Ben"), ("Victoria", "Vicky"),
    ("Nicholas", "Nick"), ("Samantha", "Sam"), ("Alexander", "Alex"),
    ("Jessica", "Jess"), ("Gregory", "Greg"), ("Cynthia", "Cindy"),
    ("Timothy", "Tim"), ("Theodore", "Ted"), ("Frederick", "Fred"),
    ("Veronica", "Ronnie"), ("Jonathan", "Jon"), ("Priscilla", "Cilla"),
    # No common short form. A comparator must not invent one.
    ("Amara", None), ("Chidi", None), ("Priya", None), ("Rahul", None),
    ("Mei", None), ("Hiroshi", None), ("Sofia", None), ("Mateo", None),
    ("Aisha", None), ("Omar", None), ("Ingrid", None), ("Lars", None),
    ("Nadia", None), ("Emeka", None), ("Yuki", None), ("Ravi", None),
    ("Elena", None), ("Dmitri", None), ("Farah", None), ("Tariq", None),
    ("Anika", None), ("Kofi", None), ("Leila", None), ("Sanjay", None),
    ("Marisol", None), ("Bjorn", None), ("Zara", None), ("Idris", None),
]

LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez",
    "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin",
    "Lee", "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark",
    "Ramirez", "Lewis", "Robinson", "Walker", "Young", "Allen", "King",
    "Wright", "Scott", "Torres", "Nguyen", "Hill", "Flores", "Green",
    "Adams", "Nelson", "Baker", "Hall", "Rivera", "Campbell", "Mitchell",
    "Carter", "Roberts", "Patel", "Shah", "Okafor", "Adeyemi", "Kimura",
    "Tanaka", "Chen", "Wang", "Liu", "Kowalski", "Novak", "Petrov",
    "Ivanov", "Hassan", "Rahman", "Aziz", "Khan", "Singh", "Kaur",
    "Andersson", "Larsen", "Virtanen", "Kelly", "Murphy", "O'Brien",
    "Callahan", "Fitzgerald", "MacLeod", "Vandenberg", "DeLuca", "Russo",
    "Esposito", "Moreau", "Lefebvre", "Dubois", "Schneider", "Fischer",
    "Weber", "Bauer", "Hoffmann", "Silva", "Santos", "Oliveira", "Costa",
]

CREDENTIALS = ["MD", "DO", "NP", "PA"]

SPECIALTIES = [
    "Family Medicine", "Internal Medicine", "Pediatrics", "Cardiology",
    "Dermatology", "Endocrinology", "Gastroenterology", "Neurology",
    "Obstetrics and Gynecology", "Oncology", "Ophthalmology", "Orthopedics",
    "Otolaryngology", "Psychiatry", "Pulmonology", "Radiology", "Rheumatology",
    "Urology", "Nephrology", "Emergency Medicine",
]

NETWORK_STATUS = ["in-network", "out-of-network", "pending"]

# (city, state, first three digits of the ZIP, area code)
PLACES = [
    ("Austin", "TX", "787", "512"), ("Houston", "TX", "770", "713"),
    ("Dallas", "TX", "752", "214"), ("San Antonio", "TX", "782", "210"),
    ("Phoenix", "AZ", "850", "602"), ("Tucson", "AZ", "857", "520"),
    ("Denver", "CO", "802", "303"), ("Boulder", "CO", "803", "720"),
    ("Portland", "OR", "972", "503"), ("Seattle", "WA", "981", "206"),
    ("Boise", "ID", "837", "208"), ("Omaha", "NE", "681", "402"),
    ("Columbus", "OH", "432", "614"), ("Cleveland", "OH", "441", "216"),
    ("Raleigh", "NC", "276", "919"), ("Charlotte", "NC", "282", "704"),
    ("Nashville", "TN", "372", "615"), ("Atlanta", "GA", "303", "404"),
    ("Tampa", "FL", "336", "813"), ("Orlando", "FL", "328", "407"),
]

STREET_NAMES = [
    "Maple", "Oak", "Cedar", "Pine", "Elm", "Willow", "Birch", "Aspen",
    "Juniper", "Magnolia", "Sycamore", "Cypress", "Hawthorn", "Laurel",
    "Bluebonnet", "Mesquite", "Sagebrush", "Ridgeline", "Fairview",
    "Riverbend", "Stonegate", "Highland", "Lakeview", "Parkside",
    "Northgate", "Southfork", "Westbrook", "Eastwood", "Meridian", "Summit",
]

# (canonical word, the abbreviations sources actually use for it)
STREET_TYPES = [
    ("Street", ["Street", "St", "ST", "St."]),
    ("Avenue", ["Avenue", "Ave", "AVE", "Ave."]),
    ("Road", ["Road", "Rd", "RD", "Rd."]),
    ("Boulevard", ["Boulevard", "Blvd", "BLVD", "Blvd."]),
    ("Drive", ["Drive", "Dr", "DR", "Dr."]),
    ("Lane", ["Lane", "Ln", "LN", "Ln."]),
    ("Parkway", ["Parkway", "Pkwy", "PKWY", "Pkwy."]),
    ("Court", ["Court", "Ct", "CT", "Ct."]),
]


# ---------------------------------------------------------------------------
# NPI
# ---------------------------------------------------------------------------

def npi_check_digit(base9):
    """The Luhn check digit an NPI carries, computed over 80840 + base9.

    Real NPIs are Luhn-valid over that constant prefix, so generating valid
    ones costs nothing and buys a test that catches a generator which has
    started producing plausible-looking garbage.
    """
    total = 0
    for i, ch in enumerate(reversed("80840" + base9)):
        d = int(ch)
        if i % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return str((10 - total % 10) % 10)


# A bijection over the eight-digit space, not a hash. Hashing the provider id
# into 10^8 values collides about twice at 20,000 providers, by the birthday
# bound, and two providers sharing an NPI silently corrupts the answer key:
# NPI blocking then produces a pair that looks true by identifier and is
# false in fact. The multiplier is odd and not divisible by five, so it is
# coprime to 10^8 and the map is one-to-one. Uniqueness is a property of the
# arithmetic here instead of something the generator has to check for.
NPI_MULTIPLIER = 48271
NPI_OFFSET = 3141593


def make_npi(provider_id):
    # NPIs allocated to individuals begin with 1.
    base9 = "1" + str(
        (NPI_MULTIPLIER * provider_id + NPI_OFFSET) % 10 ** 8).zfill(8)
    return base9 + npi_check_digit(base9)


# ---------------------------------------------------------------------------
# THE CANONICAL PROVIDERS
# ---------------------------------------------------------------------------

def canonical_provider(pid):
    """One provider, as a perfect golden record would hold them."""
    first, nick = pick(FIRST_NAMES, "first", pid)
    last = pick(LAST_NAMES, "last", pid)
    city, state, zip3, area = pick(PLACES, "place", pid)
    canon_type, _ = pick(STREET_TYPES, "stype", pid)
    moved = below(MOVED_FRACTION, "moved", pid)

    # A surname change is not a typo and the answer key holds both. The
    # current surname is what a golden record should say; the previous one is
    # what two of the four sources still carry, and a resolver that treats it
    # as a mismatch loses the provider entirely rather than merely scoring
    # them lower.
    changed = below(NAME_CHANGE_FRACTION, "namechange", pid)
    prior = pick(LAST_NAMES, "priorlast", pid) if changed else None
    if prior == last:                      # a change to the same name is none
        prior, changed = None, False

    row = {
        "provider_id": pid,
        "npi": make_npi(pid),
        "first_name": first,
        "nickname": nick,
        "last_name": last,
        "prior_last_name": prior,
        "name_changed": changed,
        "credential": pick(CREDENTIALS, "cred", pid),
        "street": "%d %s %s" % (
            100 + _bits("stnum", pid) % 9900,
            pick(STREET_NAMES, "stname", pid),
            canon_type),
        "suite": ("Suite %d" % (100 + _bits("suite", pid) % 899)
                  if below(0.55, "hassuite", pid) else None),
        "city": city,
        "state": state,
        "zip": zip3 + digits(2, "zip", pid),
        "phone": area + digits(7, "phone", pid),
        "specialty": pick(SPECIALTIES, "spec", pid),
        "network_status": pick(NETWORK_STATUS, "net", pid),
        "has_moved": moved,
    }
    return row


def previous_address(p):
    """Where a provider who moved used to practice.

    Same city and state: a practice that relocates usually relocates locally,
    and an old address in a different state would be separable by a check no
    real roster gets to make.
    """
    pid = p["provider_id"]
    canon_type, _ = pick(STREET_TYPES, "old-stype", pid)
    return {
        "street": "%d %s %s" % (
            100 + _bits("old-stnum", pid) % 9900,
            pick(STREET_NAMES, "old-stname", pid),
            canon_type),
        "suite": ("Suite %d" % (100 + _bits("old-suite", pid) % 899)
                  if below(0.55, "old-hassuite", pid) else None),
        "zip": p["zip"][:3] + digits(2, "old-zip", pid),
    }


def second_location(p, tag):
    """A second practice site for a provider a source lists twice.

    Same city, different street and phone. The provider is the same person and
    the answer key says so, which is what makes intra-source duplication a
    resolution problem rather than a deduplication of identical rows.
    """
    pid = p["provider_id"]
    canon_type, _ = pick(STREET_TYPES, tag + "-stype", pid)
    area = p["phone"][:3]
    return {
        "street": "%d %s %s" % (
            100 + _bits(tag + "-stnum", pid) % 9900,
            pick(STREET_NAMES, tag + "-stname", pid),
            canon_type),
        "suite": ("Suite %d" % (100 + _bits(tag + "-suite", pid) % 899)
                  if below(0.4, tag + "-hassuite", pid) else None),
        "zip": p["zip"][:3] + digits(2, tag + "-zip", pid),
        "phone": area + digits(7, tag + "-phone", pid),
    }


# ---------------------------------------------------------------------------
# CORRUPTION HELPERS
# ---------------------------------------------------------------------------

LOWER = "abcdefghijklmnopqrstuvwxyz"


def typo(s, *parts):
    """One character transposed, substituted or dropped.

    The first character is never touched, and that is a decision with a
    consequence rather than a simplification. Soundex keys on the first
    letter, so damaging it would put every typo beyond the reach of soundex
    blocking and turn one corruption into a guaranteed miss. Leaving it alone
    means a typo breaks soundex only when it changes a coded consonant, which
    is what makes the completeness figure in experiment 1 a measurement rather
    than a restatement of this rate.
    """
    if len(s) < 3:
        return s
    kind = _bits("typo-kind", *parts) % 3
    i = 1 + _bits("typo-pos", *parts) % (len(s) - 2)
    if kind == 0:
        return s[:i] + s[i + 1] + s[i] + s[i + 2:]
    if kind == 1:
        return s[:i] + pick(LOWER, "typo-ch", *parts) + s[i + 1:]
    return s[:i] + s[i + 1:]


def source_family(p, source, *parts):
    """The surname a source carries, name change and typo applied."""
    pid = p["provider_id"]
    name = p["last_name"]
    if p["name_changed"] and source not in SOURCES_WITH_CURRENT_SURNAME:
        name = p["prior_last_name"]
    if below(SURNAME_TYPO_RATE, "fam-typo", source, pid, *parts):
        name = typo(name, "fam-typo-at", source, pid, *parts)
    return name


def source_given(p, given, source, *parts):
    """A given name a source carries, typo applied."""
    if below(GIVEN_TYPO_RATE, "giv-typo", source, p["provider_id"], *parts):
        return typo(given, "giv-typo-at", source, p["provider_id"], *parts)
    return given


def abbreviate_street(street, *parts):
    """Rewrite the street type the way one source happens to write it.

    Inconsistently, and per row rather than per source, because that is how it
    arrives: the same feed carries STREET, ST and St. in the same file.
    """
    words = street.split()
    for canon, forms in STREET_TYPES:
        if words[-1] == canon:
            words[-1] = pick(forms, *parts)
            break
    return " ".join(words)


def display_first(p, *parts):
    """The first name a practice-facing source carries.

    A nickname most of the time, when the provider has one. The license board
    never uses it; everything else usually does.
    """
    if p["nickname"] and below(0.8, *parts):
        return p["nickname"]
    return p["first_name"]


PHONE_FORMATS = [
    lambda d: "(%s) %s-%s" % (d[:3], d[3:6], d[6:]),
    lambda d: "%s-%s-%s" % (d[:3], d[3:6], d[6:]),
    lambda d: "%s.%s.%s" % (d[:3], d[3:6], d[6:]),
    lambda d: d,
]


# ---------------------------------------------------------------------------
# THE FOUR SOURCES
# ---------------------------------------------------------------------------
#
# Each returns a list of dicts in roster.source_row's shape. A field a source
# does not carry is None, and None is not the same as wrong: a missing address
# costs recall, a stale one costs precision, and the two sources chosen to
# demonstrate that are the license board and the clearinghouse.

def observed_at(system, row_id, *parts):
    """The date a source row was observed, as YYYY-MM-DD.

    Computed from a fixed reference date rather than from the clock, because a
    generator that reads the clock produces different data on every run and
    nothing downstream is reproducible.
    """
    import datetime
    ref = datetime.date.fromisoformat(REFERENCE_DATE)
    back = _bits("obs", system, row_id, *parts) % (
        OBSERVED_WITHIN_DAYS[system] + 1)
    return (ref - datetime.timedelta(days=back)).isoformat()


def _blank_row(system, row_id, batch):
    return {"source_system": system, "source_row_id": row_id,
            "ingest_batch": batch, "observed_at": observed_at(system, row_id),
            "npi": None, "name_raw": None,
            "credential": None, "street": None, "suite": None, "city": None,
            "state": None, "zip": None, "phone": None, "specialty": None,
            "network_status": None, "license_state": None}


def payer_feed_row(p, row_id, batch, loc=None, tag="payer"):
    """Authoritative on network status. Names as "LAST, FIRST". NPI missing on
    15% of rows. Street types abbreviated inconsistently. Credential is carried
    but is stale on some rows, so the license board exists."""
    pid = p["provider_id"]
    r = _blank_row("payer_feed", row_id, batch)
    addr = loc or p
    if not below(0.15, tag + "-nonpi", pid, row_id):
        r["npi"] = p["npi"]
    fam = source_family(p, "payer_feed", tag, row_id)
    giv = source_given(p, display_first(p, tag + "-nick", pid, row_id),
                       "payer_feed", tag, row_id)
    r["name_raw"] = "%s, %s" % (fam.upper(), giv.upper())
    r["credential"] = (p["credential"]
                       if not below(0.08, tag + "-badcred", pid, row_id)
                       else pick(CREDENTIALS, tag + "-cred", pid, row_id))
    r["street"] = abbreviate_street(addr["street"], tag + "-abbr", pid, row_id).upper()
    r["suite"] = (addr.get("suite") or "").upper() or None
    r["city"] = p["city"].upper()
    # Plain data entry. A state typed wrong puts the row outside every
    # state-scoped blocking key, and no amount of scoring reaches it after.
    r["state"] = (p["state"] if not below(WRONG_STATE_RATE, tag + "-badstate",
                                          pid, row_id)
                  else pick([q[1] for q in PLACES], tag + "-state", pid, row_id))
    r["zip"] = addr.get("zip", p["zip"])
    r["phone"] = addr.get("phone", p["phone"])
    r["specialty"] = p["specialty"]
    r["network_status"] = p["network_status"]      # the authoritative field
    return r


def license_board_row(p, row_id, batch):
    """Authoritative on credential and license state. No address at all, no
    phone, and the LEGAL first name where the other sources carry a nickname.
    NPI is absent on 30% of rows: a licensing record is keyed by license
    number and the NPI is a later, optional addition to it."""
    pid = p["provider_id"]
    r = _blank_row("license_board", row_id, batch)
    if not below(0.30, "lic-nonpi", pid):
        r["npi"] = p["npi"]
    r["name_raw"] = "%s %s" % (
        source_given(p, p["first_name"], "license_board", row_id),
        source_family(p, "license_board", row_id))
    r["credential"] = p["credential"]              # the authoritative field
    r["state"] = p["state"]
    r["license_state"] = p["state"]
    r["specialty"] = p["specialty"]
    return r


def site_scrape_row(p, row_id, batch, loc=None, passenger=None, tag="scrape"):
    """A PRACTICE WEBSITE. Suite numbers sometimes folded into the street line
    and sometimes dropped. Phone in four formats. NPI present on 20% of rows.
    Some rows name two providers, and the address on such a row belongs to the
    first of them."""
    pid = p["provider_id"]
    r = _blank_row("site_scrape", row_id, batch)
    addr = loc or p
    if below(0.20, tag + "-npi", pid, row_id):
        r["npi"] = p["npi"]

    name = "%s %s, %s" % (
        source_given(p, display_first(p, tag + "-nick", pid, row_id),
                     "site_scrape", tag, row_id),
        source_family(p, "site_scrape", tag, row_id), p["credential"])
    if passenger is not None:
        name += " and %s %s, %s" % (
            display_first(passenger, tag + "-nick2", pid, row_id),
            passenger["last_name"], passenger["credential"])
    r["name_raw"] = name

    street = abbreviate_street(addr["street"], tag + "-abbr", pid, row_id)
    suite = addr.get("suite")
    if suite and below(0.25, tag + "-fold", pid, row_id):
        street = street + " " + suite            # folded into the street line
        suite = None
    elif suite and below(0.30, tag + "-drop", pid, row_id):
        suite = None                             # dropped entirely
    r["street"] = street
    r["suite"] = suite
    r["city"] = p["city"]
    r["state"] = p["state"]
    r["zip"] = addr.get("zip", p["zip"])
    fmt = pick(PHONE_FORMATS, tag + "-phfmt", pid, row_id)
    r["phone"] = fmt(addr.get("phone", p["phone"]))
    r["specialty"] = p["specialty"]
    return r


def clearinghouse_row(p, row_id, batch):
    """NPI always present and correct. The address is STALE: a provider
    who moved is still carried at the previous practice, and this source did
    not notice. That is the source a naive priority list would rank first for
    having the best identifier and the worst address."""
    pid = p["provider_id"]
    r = _blank_row("clearinghouse", row_id, batch)
    addr = previous_address(p) if p["has_moved"] else p
    r["npi"] = p["npi"]                            # the authoritative field
    r["name_raw"] = "%s %s" % (
        source_given(p, display_first(p, "clr-nick", pid), "clearinghouse"),
        source_family(p, "clearinghouse"))
    r["credential"] = (p["credential"]
                       if not below(0.05, "clr-badcred", pid)
                       else pick(CREDENTIALS, "clr-cred", pid))
    r["street"] = abbreviate_street(addr["street"], "clr-abbr", pid)
    r["suite"] = addr.get("suite")
    r["city"] = p["city"]
    r["state"] = p["state"]
    r["zip"] = addr.get("zip", p["zip"])
    r["phone"] = "%s-%s-%s" % (p["phone"][:3], p["phone"][3:6], p["phone"][6:])
    r["specialty"] = p["specialty"]
    return r


# ---------------------------------------------------------------------------
# ASSEMBLY
# ---------------------------------------------------------------------------

def generate(n=N_PROVIDERS, batch=1):
    """Every canonical provider, every source row, and the link between them.

    Returns (providers, rows, links). row ids are assigned per source in
    provider order, which is deterministic and independent of n only up to n:
    generating 100 providers gives the same first 100 providers but not the
    same row ids as generating 20,000, because coverage decides which
    providers a source carries. Tests that assert row ids state the n they
    used.
    """
    providers = [canonical_provider(pid) for pid in range(1, n + 1)]
    rows, links = [], []
    counters = {s: 0 for s in COVERAGE}

    def emit(row, pid, multi=False):
        rows.append(row)
        links.append({"source_system": row["source_system"],
                      "source_row_id": row["source_row_id"],
                      "provider_id": pid, "multi_provider": multi})

    for p in providers:
        pid = p["provider_id"]

        if below(COVERAGE["payer_feed"], "cov-payer", pid):
            counters["payer_feed"] += 1
            rid = counters["payer_feed"]
            emit(payer_feed_row(p, rid, batch), pid)
            if below(SECOND_LOCATION["payer_feed"], "loc2-payer", pid):
                counters["payer_feed"] += 1
                rid2 = counters["payer_feed"]
                loc = second_location(p, "payer2")
                emit(payer_feed_row(p, rid2, batch, loc=loc, tag="payer2"), pid)

        if below(COVERAGE["license_board"], "cov-lic", pid):
            counters["license_board"] += 1
            emit(license_board_row(p, counters["license_board"], batch), pid)

        if below(COVERAGE["site_scrape"], "cov-scrape", pid):
            counters["site_scrape"] += 1
            rid = counters["site_scrape"]
            # About one scrape row in a hundred names two providers. The
            # passenger is a real provider from the same city, which is what
            # makes the row attract a wrong pair rather than a harmless one.
            passenger = None
            if below(0.01, "scrape-multi", pid) and n > 1:
                other = 1 + _bits("scrape-passenger", pid) % n
                if other != pid:
                    passenger = providers[other - 1]
            emit(site_scrape_row(p, rid, batch, passenger=passenger), pid,
                 multi=passenger is not None)
            if below(SECOND_LOCATION["site_scrape"], "loc2-scrape", pid):
                counters["site_scrape"] += 1
                rid2 = counters["site_scrape"]
                loc = second_location(p, "scrape2")
                emit(site_scrape_row(p, rid2, batch, loc=loc, tag="scrape2"), pid)

        if below(COVERAGE["clearinghouse"], "cov-clr", pid):
            counters["clearinghouse"] += 1
            emit(clearinghouse_row(p, counters["clearinghouse"], batch), pid)

    return providers, rows, links


PROVIDER_COLS = ["provider_id", "npi", "first_name", "nickname", "last_name",
                 "prior_last_name", "name_changed", "credential", "street",
                 "suite", "city", "state", "zip", "phone", "specialty",
                 "network_status", "has_moved"]

ROW_COLS = ["source_system", "source_row_id", "ingest_batch", "observed_at",
            "npi", "name_raw", "credential", "street", "suite", "city",
            "state", "zip", "phone", "specialty", "network_status",
            "license_state"]

LINK_COLS = ["source_system", "source_row_id", "provider_id", "multi_provider"]


def write_csv(path, cols, records):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in records:
            w.writerow({c: ("" if r.get(c) is None else r[c]) for c in cols})


def manifest(providers, rows, links):
    """A hash over everything generated, so a run can prove it used the same
    input as the run that produced the shipped results."""
    h = hashlib.sha256()
    for cols, recs in ((PROVIDER_COLS, providers), (ROW_COLS, rows),
                       (LINK_COLS, links)):
        for r in recs:
            h.update("|".join("" if r.get(c) is None else str(r[c])
                              for c in cols).encode("utf-8"))
            h.update(b"\n")
    counts = {}
    for r in rows:
        counts[r["source_system"]] = counts.get(r["source_system"], 0) + 1
    return {"seed": SEED, "providers": len(providers),
            "source_rows": len(rows), "rows_by_source": counts,
            "sha256": h.hexdigest()}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="data",
                    help="directory to write the CSVs into")
    ap.add_argument("--providers", type=int, default=N_PROVIDERS)
    ap.add_argument("--manifest", action="store_true",
                    help="print the manifest and write nothing")
    a = ap.parse_args()

    providers, rows, links = generate(a.providers)
    man = manifest(providers, rows, links)

    if a.manifest:
        print(json.dumps(man, indent=2, sort_keys=True))
        return 0

    os.makedirs(a.out, exist_ok=True)
    write_csv(os.path.join(a.out, "canonical_provider.csv"),
              PROVIDER_COLS, providers)
    write_csv(os.path.join(a.out, "source_row.csv"), ROW_COLS, rows)
    write_csv(os.path.join(a.out, "source_row_link.csv"), LINK_COLS, links)
    with open(os.path.join(a.out, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(man, fh, indent=2, sort_keys=True)
        fh.write("\n")

    print("providers   %6d" % man["providers"])
    for src in sorted(man["rows_by_source"]):
        print("%-12s%6d" % (src, man["rows_by_source"][src]))
    print("source rows %6d" % man["source_rows"])
    print("sha256      %s" % man["sha256"])
    return 0


if __name__ == "__main__":
    sys.exit(main())


# ---------------------------------------------------------------------------
# THE SECOND INGEST
# ---------------------------------------------------------------------------
#
# A later file. Overrides are made against the first ingest and then a second
# file arrives. It is a DELTA and replaces nothing: each row is a new assertion
# with a new source_row_id, which is how a roster feed actually behaves and
# is why cluster membership changes without anything being deleted.
#
# Three things happen in it, and each one breaks a different assumption:
#   the site scrape reaches providers it had never crawled, so clusters that
#     had three rows now have four and the connected components renumber;
#   the payer feed reissues rows for providers it already carried, so a
#     cluster grows without gaining a provider;
#   the clearinghouse catches up on some movers, which is the case that makes
#     a human override STALE rather than lost: the operator pinned an
#     address because the clearinghouse was wrong, and now it is not.
NEW_SCRAPE_SHARE = 0.5      # Of the providers site_scrape had missed
PAYER_REISSUE_SHARE = 0.06  # of the providers payer_feed already carried
CLEARINGHOUSE_CATCHUP = 0.35   # of the movers it had stale


def generate_batch2(providers, rows_batch1):
    """The second ingest, as new rows with new ids. Returns (rows, links)."""
    # seeded with every source, not only the ones batch 1 happened to emit. A
    # source with no rows in the first file still needs a counter, and a
    # KeyError here would be raised inside a generator whose whole purpose is
    # to be reproducible.
    next_id = {s: 0 for s in COVERAGE}
    for r in rows_batch1:
        s = r["source_system"]
        next_id[s] = max(next_id.get(s, 0), r["source_row_id"])

    rows, links = [], []

    def emit(row, pid):
        rows.append(row)
        links.append({"source_system": row["source_system"],
                      "source_row_id": row["source_row_id"],
                      "provider_id": pid, "multi_provider": False})

    for p in providers:
        pid = p["provider_id"]

        # The scrape reaches providers it had never crawled.
        if not below(COVERAGE["site_scrape"], "cov-scrape", pid) \
                and below(NEW_SCRAPE_SHARE, "b2-scrape", pid):
            next_id["site_scrape"] += 1
            emit(site_scrape_row(p, next_id["site_scrape"], 2, tag="b2scrape"),
                 pid)

        # The payer feed reissues a row it already had.
        if below(COVERAGE["payer_feed"], "cov-payer", pid) \
                and below(PAYER_REISSUE_SHARE, "b2-payer", pid):
            next_id["payer_feed"] += 1
            emit(payer_feed_row(p, next_id["payer_feed"], 2, tag="b2payer"),
                 pid)

        # The clearinghouse notices that a provider moved.
        if p["has_moved"] and below(COVERAGE["clearinghouse"], "cov-clr", pid) \
                and below(CLEARINGHOUSE_CATCHUP, "b2-clr", pid):
            next_id["clearinghouse"] += 1
            r = clearinghouse_row(p, next_id["clearinghouse"], 2)
            # The catch-up row carries the CURRENT address, unlike its
            # predecessor. clearinghouse_row() looks up has_moved and would
            # write the previous one, so the address is overwritten here and
            # the row is otherwise untouched.
            r["street"] = abbreviate_street(p["street"], "b2clr-abbr", pid)
            r["suite"] = p["suite"]
            r["zip"] = p["zip"]
            emit(r, pid)

    return rows, links
