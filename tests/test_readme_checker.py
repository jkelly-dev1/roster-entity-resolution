"""The README figure checker, checked.

`check_readme_numbers.py` is a gate, and a gate nothing tests can stop
examining its target while still printing the sentence that means it did. A
hand-written list of the values a derivation is willing to judge would skip
everything outside it in silence. These tests pin that the rows checked are
read out of the README, so a row published there is judged because it is
there.

They use the SHIPPED results files and a doctored copy of the README, so they
need no database and no network.
"""

import os

import pytest

import check_readme_numbers as chk
import lab


@pytest.fixture(scope="module")
def readme():
    with open(chk.README, encoding="utf-8") as fh:
        return fh.read()


# --- published_table_rows ---------------------------------------------------

TABLE = """intro text

| Band width | Review queue | Expected cost |
| --- | --- | --- |
| none | 0 | 5,919 |
| 2% | 286 | 5,803 |
| 40% | 103,181 | 654 |

text after the table, which must not be read as a row
"""


def test_published_table_rows_reads_the_rows_under_the_named_header():
    assert chk.published_table_rows(TABLE, "Band width") == ["none", "2%", "40%"]


def test_published_table_rows_stops_at_the_end_of_the_table():
    # The paragraph after the table is not a row, and a parser that ran on
    # would report figures the README does not publish.
    assert "text after the table" not in chk.published_table_rows(
        TABLE, "Band width")


def test_published_table_rows_is_empty_for_a_header_that_is_not_there():
    assert chk.published_table_rows(TABLE, "Threshold") == []


def test_published_table_rows_finds_both_of_the_readmes_real_tables(readme):
    damage = chk.published_table_rows(readme, "Threshold")
    bands = chk.published_table_rows(readme, "Band width")
    # Measured 2026-09-14: the README publishes 7 of 13 damage rows and 6 of 8
    # bands. Asserted as a floor and a ceiling rather than an equality, so
    # publishing another row is not a failure but reading NOTHING is.
    assert 5 <= len(damage) <= 13, damage
    assert 5 <= len(bands) <= 8, bands
    assert "8.382 (10:1)" in damage
    assert "none" in bands and "40%" in bands


# --- width_label ------------------------------------------------------------

def test_width_label_derives_every_width():
    assert chk.width_label(0.0) == "none"
    assert chk.width_label(0.02) == "2%"
    assert chk.width_label(0.05) == "5%"      # 5.000000000000001 in binary
    assert chk.width_label(0.1) == "10%"
    assert chk.width_label(0.15) == "15%"
    assert chk.width_label(0.3) == "30%"
    assert chk.width_label(0.4) == "40%"


def test_width_label_covers_every_band_the_results_file_carries():
    e2 = lab.read_result("exp2_threshold")
    for b in e2["review_band"]["bands"]:
        lab_ = chk.width_label(b["band_width_fraction_of_score_range"])
        assert lab_ and lab_ != "None"


# --- build ------------------------------------------------------------------

def test_build_checks_a_damage_row_the_readme_publishes(readme):
    want, orphans = chk.build(readme)
    assert not orphans
    labels = {l for l, _ in want}
    assert any(l.startswith("damage row") for l in labels)
    assert any(l.startswith("band row") for l in labels)


def test_build_reports_a_published_row_with_no_results_row_behind_it(readme):
    """The failure the old skip could not express: a figure with no evidence."""
    doctored = readme.replace("| -3.000 | 71,356", "| -4.000 | 71,356", 1)
    assert doctored != readme
    _, orphans = chk.build(doctored)
    assert any("-4.000" in o for o in orphans), orphans


def test_build_starts_checking_a_band_the_readme_begins_to_publish(readme):
    """The 15% band exists in the results and is not in the README.
    Publishing it must bring it under the checker, not past it."""
    before = {l for l, _ in chk.build(readme)[0]}
    assert "band row 15%" not in before
    doctored = readme.replace(
        "| 20% | 35,348",
        "| 15% | 1 | 1 | 1 | 0.0001 |\n| 20% | 35,348", 1)
    assert doctored != readme
    want, _ = chk.build(doctored)
    after = {l: s for l, s in want}
    assert "band row 15%" in after, "the new row was skipped in silence"
    # And the value it requires is the one the results file actually holds,
    # not the one the doctored README claims.
    assert "| 15% | 1 | 1 | 1 | 0.0001 |" != after["band row 15%"]


def test_build_derives_the_row_distance_the_prose_states(readme):
    """A direction word and a small integer, miscounted twice by hand."""
    want, _ = chk.build(readme)
    d = dict(want)["rows between the operating point and the first six"]
    assert d.endswith("the table")
    assert " up " in d or " down " in d
    # It has to be IN the README, which is what the checker exists to require.
    assert d in " ".join(readme.split())


# --- underived ----------------------------------------------------------------
#
# build() asks whether each derived string is PRESENT. 74,926 appears seven
# times in the README, so that question checks one of them. underived() asks
# the other way round: is every figure in the README one build() derived?

def test_the_shipped_readme_has_no_underived_figure(readme):
    want, _ = chk.build(readme)
    assert chk.underived(readme, want) == []


@pytest.mark.parametrize("shipped, edited", [
    ("same 74,926 rows", "same 76,926 rows"),
    ("any of its 19,617 rows", "any of its 19,817 rows"),
    ("reaches 106,150 of", "reaches 104,150 of"),
])
def test_an_edited_repeat_of_a_derived_figure_is_caught(readme, shipped,
                                                         edited, tmp_path,
                                                         monkeypatch):
    assert readme.count(shipped) == 1, shipped
    doctored = readme.replace(shipped, edited)
    new_figure = (set(chk._FIGURE.findall(edited))
                  - set(chk._FIGURE.findall(shipped))).pop()
    want, _ = chk.build(doctored)
    assert new_figure in [t for _, t in chk.underived(doctored, want)]
    # and the gate itself refuses the document, not only the helper
    path = tmp_path / "README.md"
    path.write_text(doctored, encoding="utf-8")
    monkeypatch.setattr(chk, "README", str(path))
    assert chk.main() == 1


# --- position -----------------------------------------------------------------
#
# A figure is covered only where a derived string puts it. Each edit below
# types one derived figure over another, or a parameter over a result, in a
# single sentence. A check that asked only whether the new digits are derived
# SOMEWHERE passes every one of them.

@pytest.mark.parametrize("shipped, edited", [
    ("distinguishes them from the 271:", "distinguishes them from the 229:"),
    ("not the 95 percent predicted", "not the 74 percent predicted"),
    ("at 10 times a missed one", "at 30 times a missed one"),
    ("takes 8.382 away", "takes 0.385 away"),
    ("is 2.8 billion comparisons", "is 26 billion comparisons"),
    ("Only 3,054 of the", "Only 13,771 of the"),
    ("worth 0.12 bits", "worth 7.16 bits"),
    ("A 23 percent change", "A 90 percent change"),
    ("ends with 33 fewer clusters", "ends with 50 fewer clusters"),
    ("the 12% of providers", "the 30% of providers"),
    ("3 percent of rows carry", "30 percent of rows carry"),
    ("about 3 GB of free", "about 30 GB of free"),
])
def test_a_figure_typed_over_another_derived_figure_is_caught(
        readme, shipped, edited, tmp_path, monkeypatch):
    assert readme.count(shipped) == 1, shipped
    doctored = readme.replace(shipped, edited)
    new_figure = (set(chk._FIGURE.findall(edited))
                  - set(chk._FIGURE.findall(shipped))).pop()
    want, _ = chk.build(doctored)
    # The new digits are a figure the checker derives, or one NOT_DERIVED
    # names, somewhere else in the README: position is what catches them.
    elsewhere = {t for s in [s for _, s in want] + list(chk.NOT_DERIVED)
                 for t in chk._FIGURE.findall(s)}
    assert new_figure in elsewhere, new_figure
    assert new_figure in [t for _, t in chk.underived(doctored, want)]
    path = tmp_path / "README.md"
    path.write_text(doctored, encoding="utf-8")
    monkeypatch.setattr(chk, "README", str(path))
    assert chk.main() == 1


def test_a_bare_figure_cannot_place_itself():
    assert not chk.places("271")
    assert not chk.places("0.385")
    assert chk.places("distinguishes them from the 271:")
    assert chk.places("| 0.385 | 1,448 |")


def test_every_derived_string_places_its_figures(readme):
    want, _ = chk.build(readme)
    assert [s for _, s in want if not chk.places(s)] == []


def test_a_not_derived_entry_whose_sentence_is_gone_fails_the_gate(
        readme, tmp_path, monkeypatch):
    shipped = "Give it about 3 GB of free memory."
    assert readme.count(shipped) == 1
    doctored = readme.replace(shipped, "Give it free memory.")
    assert chk.stale_exceptions(doctored) == ["about 3 GB of free memory"]
    path = tmp_path / "README.md"
    path.write_text(doctored, encoding="utf-8")
    monkeypatch.setattr(chk, "README", str(path))
    assert chk.main() == 1


def test_the_docstring_names_every_figure_not_derived():
    named = {t.rstrip(",") for t in chk._FIGURE.findall(chk.__doc__)}
    for key in chk.NOT_DERIVED:
        for token in chk._FIGURE.findall(key):
            assert token.rstrip(",") in named, (key, token)


def test_emit_prints_every_derived_string_one_per_line(readme, capsys):
    want, _ = chk.build(readme)
    assert chk.main(["--emit"]) == 0
    printed = capsys.readouterr().out.splitlines()
    assert printed == [" ".join(s.split()) for _, s in want]


def test_a_result_repeated_in_a_new_sentence_is_caught(readme, tmp_path,
                                                       monkeypatch):
    """Every derived string is still present, so only the position check
    can see this: 229 is a derived figure, in a sentence nothing derives."""
    shipped = "The contrast is the result."
    assert readme.count(shipped) == 1
    doctored = readme.replace(shipped,
                              "The contrast is the result, and 229 moved.")
    want, _ = chk.build(doctored)
    flat = " ".join(doctored.split())
    assert all(" ".join(s.split()) in flat for _, s in want)
    path = tmp_path / "README.md"
    path.write_text(doctored, encoding="utf-8")
    monkeypatch.setattr(chk, "README", str(path))
    assert chk.main() == 1
