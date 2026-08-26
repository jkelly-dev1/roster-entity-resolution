"""Field comparators, in pure standard library Python.

Why not in the database. Jaro-Winkler is not in Postgres's `fuzzystrmatch`,
and the extensions that provide it need a source build. That is affordable;
what is not is the consequence for the test suite. CI here installs pytest and
nothing else and never starts a container, so a comparator living in a
database extension could only be tested by reimplementing it in Python, and
the reimplementation is then the only thing under test while the shipped code
is not. A check that cannot run must not look like a check that agrees.

`soundex()` IS taken from Postgres, because it is a BLOCKING KEY rather than a
score: it is computed once on load and then compared for equality inside a
join, and a key computed one way on load and another way in the join is a
defect that presents as a strategy with mysteriously poor completeness.

Every comparator returns a level, not a number. Fellegi-Sunter needs discrete
agreement patterns to estimate m and u against, and MISSING has to be its own
level rather than being folded into DISAGREE: a license board row has no
address at all, and scoring that as an address disagreement would push every
one of its true pairs below any threshold.
"""

AGREE = "agree"
PARTIAL = "partial"
DISAGREE = "disagree"
MISSING = "missing"

LEVELS = (AGREE, PARTIAL, DISAGREE, MISSING)


# ---------------------------------------------------------------------------
# STRING SIMILARITY
# ---------------------------------------------------------------------------

def jaro(s1, s2):
    """Jaro similarity in [0, 1]."""
    if s1 == s2:
        return 1.0
    if not s1 or not s2:
        return 0.0

    len1, len2 = len(s1), len(s2)
    # The window inside which two characters count as the same character.
    window = max(len1, len2) // 2 - 1
    if window < 0:
        window = 0

    s1_flags = [False] * len1
    s2_flags = [False] * len2
    matches = 0

    for i, c in enumerate(s1):
        lo = max(0, i - window)
        hi = min(i + window + 1, len2)
        for j in range(lo, hi):
            if not s2_flags[j] and s2[j] == c:
                s1_flags[i] = s2_flags[j] = True
                matches += 1
                break

    if matches == 0:
        return 0.0

    # Transpositions are counted in pairs and halved. Counting mismatched
    # positions directly double counts every swap, which inflates short-string
    # similarity and is the commonest way this function is written wrong.
    transpositions = 0
    k = 0
    for i in range(len1):
        if not s1_flags[i]:
            continue
        while not s2_flags[k]:
            k += 1
        if s1[i] != s2[k]:
            transpositions += 1
        k += 1
    transpositions //= 2

    m = float(matches)
    return (m / len1 + m / len2 + (m - transpositions) / m) / 3.0


def jaro_winkler(s1, s2, prefix_weight=0.1, max_prefix=4):
    """Jaro, boosted by a shared prefix of up to four characters.

    The boost is bounded at four characters and the weight at 0.25 FOR A
    REASON: prefix_weight * max_prefix must not exceed 1, or the function can
    return more than 1 and every threshold downstream becomes meaningless.
    """
    if prefix_weight * max_prefix > 1.0:
        raise ValueError("prefix_weight * max_prefix must not exceed 1")
    j = jaro(s1, s2)
    if j == 0.0:
        return 0.0
    n = 0
    for a, b in zip(s1[:max_prefix], s2[:max_prefix]):
        if a != b:
            break
        n += 1
    return j + n * prefix_weight * (1.0 - j)


def jaccard(a, b):
    """Set overlap of two token lists, in [0, 1]."""
    sa, sb = set(a or []), set(b or [])
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / float(len(sa | sb))


# ---------------------------------------------------------------------------
# FIELD COMPARATORS
# ---------------------------------------------------------------------------

def cmp_exact(a, b):
    if a is None or b is None:
        return MISSING
    return AGREE if a == b else DISAGREE


def cmp_npi(a, b):
    """An NPI disagreement is not weak evidence, it is almost proof, and the
    weights estimated in experiment 2 say so rather than this function. What
    this function must get right is that ABSENT is not DISAGREE: two thirds of
    site_scrape rows carry no NPI and scoring them as contradicting one would
    make the strongest identifier in the data into its most misleading one."""
    return cmp_exact(a, b)


def _graded(sim, agree_at, partial_at):
    if sim >= agree_at:
        return AGREE
    if sim >= partial_at:
        return PARTIAL
    return DISAGREE


def cmp_given(a, b, canonical=None):
    """Given names, with the short form resolved to the legal one.

    Compared BOTH WAYS and the better taken: the nickname table maps short to
    legal, so Bob/Robert resolves but a name the table does not know is
    compared as written rather than dropped.
    """
    if not a or not b:
        return MISSING
    sim = jaro_winkler(a, b)
    if canonical is not None:
        sim = max(sim, jaro_winkler(canonical(a), canonical(b)))
    return _graded(sim, 0.95, 0.85)


def cmp_family(a, b):
    if not a or not b:
        return MISSING
    return _graded(jaro_winkler(a, b), 0.95, 0.88)


def cmp_street(a, b):
    """Token overlap after abbreviation folding.

    Empty is missing, not disagreement. The license board ships no address at
    all, so an empty token list means the source does not know rather than
    that the addresses differ.
    """
    if not a or not b:
        return MISSING
    j = jaccard(a, b)
    return _graded(j, 0.85, 0.5)


# The comparison vector, in a fixed order so that an agreement pattern is a
# stable tuple and can be used as a dictionary key.
FIELDS = ("npi", "given_name", "family_name", "street", "phone", "zip",
          "state", "specialty")


def compare_pair(a, b, canonical=None):
    """Agreement level of every field, for one candidate pair."""
    return {
        "npi": cmp_npi(a.get("npi"), b.get("npi")),
        "given_name": cmp_given(a.get("given_name"), b.get("given_name"),
                                canonical),
        "family_name": cmp_family(a.get("family_name"), b.get("family_name")),
        "street": cmp_street(a.get("street_tokens"), b.get("street_tokens")),
        "phone": cmp_exact(a.get("phone"), b.get("phone")),
        "zip": cmp_exact(a.get("zip"), b.get("zip")),
        "state": cmp_exact(a.get("state"), b.get("state")),
        "specialty": cmp_exact(a.get("specialty"), b.get("specialty")),
    }


def pattern(vec):
    """The comparison vector as a hashable tuple, in FIELDS order."""
    return tuple(vec[f] for f in FIELDS)
