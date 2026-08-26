"""Make scripts/ importable, and load the shipped evidence once.

The suite is offline and stays offline. Reproducing the measurements needs
Postgres and about two minutes of wall clock; asserting them does not. Every
test here exercises either a pure function or the committed results/*.json, so
CI installs pytest and nothing else and never starts a container.
"""

import json
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))


def _result(name):
    path = os.path.join(REPO, "results", name + ".json")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="session")
def exp1():
    return _result("exp1_blocking")


@pytest.fixture(scope="session")
def exp2():
    return _result("exp2_threshold")


@pytest.fixture(scope="session")
def exp3():
    return _result("exp3_survivorship")


@pytest.fixture(scope="session")
def exp4():
    return _result("exp4_override_stability")


@pytest.fixture(scope="session")
def lineage():
    return _result("exp3_lineage_sample")
