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
