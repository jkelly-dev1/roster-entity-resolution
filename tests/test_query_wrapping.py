"""The sub-query wrapper survives a query that ends in a line comment.

`lab.query_json` asks Postgres to serialize by wrapping the caller's SQL in
`SELECT ... FROM (<sql>) t;`. Every query in this repository is written with
its reasoning in `--` comments, and a `--` comment runs to the end of its
line, so a wrapper that appended `) t;` with no newline in front of it would
put its own closing paren inside the caller's last comment. The statement
would end unterminated and the script would not run at all. The comment
under experiment 4's ORDER BY is exactly that shape, and the tests and the
README checker read the committed results file, not the script that writes
it, so only a test of the wrapper itself can see this.

These tests need no Postgres. `scalar` is replaced with a capture on the `lab`
module object, which is the binding `query_json` resolves at call time, so a
patch that missed would show up as a real connection attempt and not as a
silent pass.
"""

import json
import re

import lab


def _capture(monkeypatch):
    """Run query_json against a stub and hand back the SQL it really sent."""
    seen = []

    def fake_scalar(sql, *a, **kw):
        seen.append(sql)
        return "[]"

    monkeypatch.setattr(lab, "scalar", fake_scalar)
    return seen


def _strip_sql_line_comments(sql):
    """What the server sees after `--` comments are consumed to end of line."""
    return "\n".join(re.sub(r"--.*$", "", ln) for ln in sql.splitlines())


def test_a_subquery_ending_in_a_line_comment_still_closes(monkeypatch):
    seen = _capture(monkeypatch)
    rows = lab.query_json("""
        SELECT 1 AS a
         ORDER BY a
         -- This comment explains the ORDER BY above, which is where a comment
         -- about an ORDER BY belongs, and it is the last thing in the string.
    """)
    assert rows == []
    assert len(seen) == 1, "query_json did not call the patched scalar"
    # The closing paren must survive comment stripping. Asserting that ") t;"
    # is present in the raw string would pass on the broken form too, where
    # it is present but commented out.
    assert ") t;" in _strip_sql_line_comments(seen[0]), (
        "the wrapper's closing paren is inside a line comment:\n%s" % seen[0])


def test_the_wrapper_still_wraps_a_query_with_no_comment(monkeypatch):
    seen = _capture(monkeypatch)
    assert lab.query_json("SELECT 1 AS a") == []
    sent = _strip_sql_line_comments(seen[0])
    assert "json_agg(t)" in sent
    assert ") t;" in sent
    # The caller's own trailing semicolon is still absorbed instead of
    # terminating the statement early.
    seen.clear()
    lab.query_json("SELECT 1 AS a;")
    assert _strip_sql_line_comments(seen[0]).count(";") == 1


def test_every_query_in_the_scripts_survives_the_wrapper(monkeypatch):
    """Every triple-quoted query literal in scripts/, read off disk.

    Not a copy of one query. A copy would keep passing after somebody edited
    the script, and it would say nothing about the next query someone writes a
    comment under. The literals are passed through the wrapper verbatim: their
    percent placeholders are the caller's business and the wrapper never looks
    at them.
    """
    import glob
    import os
    pattern = re.compile(r'lab\.query_json\(\s*"""(.*?)"""', re.S)
    checked = 0
    ending_in_a_comment = 0
    for path in sorted(glob.glob(os.path.join(lab.REPO, "scripts", "*.py"))):
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        for sql in pattern.findall(src):
            checked += 1
            if sql.rstrip().splitlines()[-1].strip().startswith("--"):
                ending_in_a_comment += 1
            seen = _capture(monkeypatch)
            lab.query_json(sql)
            assert ") t;" in _strip_sql_line_comments(seen[0]), (
                "%s: the wrapper's closing paren lands inside a line comment"
                % os.path.basename(path))
    # A check that examined nothing is not a check that passed. If the regex
    # stops matching (a rename, a switch to single quotes), this test would
    # otherwise go green having read nothing at all.
    # 8 on 2026-09-13: exp1 1, exp2 1, exp3 2, exp4 4. Measured, not guessed,
    # and a floor rather than an equality so adding a query is not a failure.
    assert checked >= 8, "only %d query literals were found in scripts/" % checked
    assert ending_in_a_comment >= 1, (
        "no query in scripts/ ends in a line comment any more, so this test "
        "no longer exercises the shape it was written for")
