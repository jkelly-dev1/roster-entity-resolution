"""The string comparators, against values published outside this repository.

Why these particular strings. MARTHA/MARHTA, DWAYNE/DUANE and DIXON/DICKSONX
are the worked examples in the Jaro-Winkler literature and their expected
values are published. A comparator tested only against its own output is
tested against nothing, and a transposition-counting error, the usual defect
in this function, reproduces plausible-looking similarities everywhere except
on strings that actually contain a transposition.
"""

import pytest

import compare
import normalize


def test_jaro_matches_the_published_value_for_martha_and_marhta():
    assert round(compare.jaro("MARTHA", "MARHTA"), 6) == 0.944444


def test_jaro_winkler_matches_the_published_value_for_martha_and_marhta():
    assert round(compare.jaro_winkler("MARTHA", "MARHTA"), 6) == 0.961111


def test_jaro_winkler_matches_the_published_value_for_dwayne_and_duane():
    assert round(compare.jaro_winkler("DWAYNE", "DUANE"), 6) == 0.840000


def test_jaro_winkler_matches_the_published_value_for_dixon_and_dicksonx():
    assert round(compare.jaro_winkler("DIXON", "DICKSONX"), 6) == 0.813333


def test_a_transposition_scores_below_an_exact_match_but_well_above_chance():
    # The property the published values encode, stated so that a rewrite of
    # the function has to keep it even if the constants are ever changed.
    exact = compare.jaro_winkler("SILVA", "SILVA")
    swapped = compare.jaro_winkler("SILVA", "SLIVA")
    unrelated = compare.jaro_winkler("SILVA", "OKAFOR")
    assert exact == 1.0
    assert unrelated < swapped < exact


def test_jaro_winkler_never_exceeds_one_for_a_long_shared_prefix():
    # (mutation-checked: raise max_prefix to 11 with the same weight and the
    # guard fires; remove the guard and this test fails on the missing raise.
    # These two names still score 0.985185 unguarded; a longer shared prefix,
    # ABCDEFGHIJKX against ABCDEFGHIJKY, scores 1.0056, above 1, and the guard
    # exists for that case)
    #
    # The mutation is run here, not described. A max_prefix of 8 would not
    # fire: the default weight is 0.1, so the product is 0.8 and the function
    # silently returns 0.985185. A mutation claim nothing executes is a claim
    # about coverage that no run can contradict.
    assert compare.jaro_winkler("KATHERINE", "KATHERINA") <= 1.0
    with pytest.raises(ValueError, match="must not exceed 1"):
        compare.jaro_winkler("KATHERINE", "KATHERINA", max_prefix=11)
    # The boundary too, because "must not exceed 1" is not "must be under 1".
    # A product of exactly 1 is safe: the boost is n * w * (1 - j) with
    # n <= max_prefix, so n * w <= 1 and the boost cannot carry j past 1,
    # and a guard tightened to `>= 1.0` would reject a legal configuration
    # while every other assertion here stayed green.
    assert compare.jaro_winkler("KATHERINE", "KATHERINA", max_prefix=10) <= 1.0
    # The message is named as well as the type. `pytest.raises(ValueError)` is satisfied by
    # any ValueError, including one from a typo in the call below it, so an
    # open raises() can stay green over a function that stopped working.
    with pytest.raises(ValueError, match="must not exceed 1"):
        compare.jaro_winkler("A", "B", prefix_weight=0.3, max_prefix=4)


def test_jaro_is_symmetric():
    for a, b in [("SMITH", "SMYTHE"), ("OKAFOR", "OKAFO"), ("LEE", "LI")]:
        assert compare.jaro(a, b) == compare.jaro(b, a)


def test_an_empty_string_scores_zero_rather_than_raising():
    assert compare.jaro("", "SMITH") == 0.0
    assert compare.jaro_winkler("", "") == 1.0


# ---------------------------------------------------------------------------
# LEVELS
# ---------------------------------------------------------------------------

def test_a_missing_field_is_missing_and_not_a_disagreement():
    # The distinction the whole model rests on. The license board ships no
    # address at all; scoring that as an address disagreement would push every
    # one of its true pairs below any threshold.
    # (mutation-checked: return DISAGREE instead of MISSING in cmp_street and
    # the license board's weight for street collapses)
    assert compare.cmp_street(["100", "MAPLE", "STREET"], []) == compare.MISSING
    assert compare.cmp_npi(None, "1234567890") == compare.MISSING
    assert compare.cmp_exact(None, None) == compare.MISSING


def test_two_different_npis_disagree_rather_than_going_missing():
    assert compare.cmp_npi("1111111111", "2222222222") == compare.DISAGREE


def test_street_tokens_agree_when_the_abbreviation_differs_only():
    a = normalize.street_tokens("8864 Parkside Pkwy")
    b = normalize.street_tokens("8864 PARKSIDE PARKWAY")
    assert compare.cmp_street(a, b) == compare.AGREE


def test_a_nickname_agrees_with_its_legal_name_only_with_the_table():
    # (mutation-checked: drop the canonical argument and this is DISAGREE,
    # which is what the given-name weight in results/exp2_threshold.json is
    # measured against)
    assert compare.cmp_given("BOB", "ROBERT",
                             normalize.canonical_given) == compare.AGREE
    assert compare.cmp_given("BOB", "ROBERT") == compare.DISAGREE


def test_an_unknown_short_form_is_left_alone_rather_than_guessed():
    assert normalize.canonical_given("ZARA") == "ZARA"
    assert normalize.canonical_given(None) is None


def test_the_comparison_vector_has_one_level_for_every_field():
    a = {"npi": "1234567890", "given_name": "BOB", "family_name": "SILVA",
         "street_tokens": ["8864", "PARKSIDE", "PARKWAY"], "phone": "5125550100",
         "zip": "78701", "state": "TX", "specialty": "Cardiology"}
    vec = compare.compare_pair(a, a, normalize.canonical_given)
    assert set(vec) == set(compare.FIELDS)
    assert all(v in compare.LEVELS for v in vec.values())
    assert compare.pattern(vec) == tuple(vec[f] for f in compare.FIELDS)


def test_jaccard_is_zero_when_either_side_is_empty():
    assert compare.jaccard([], ["A"]) == 0.0
    assert compare.jaccard(["A", "B"], ["A", "B"]) == 1.0
    assert compare.jaccard(["A", "B"], ["B", "C"]) == pytest.approx(1 / 3)
