"""Tests for safi_engine.ledger.build_ledger using the shipment_1 fixture."""

import json
import os
import pytest

from safi_engine.ledger import build_ledger

FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "shipment_1.json")


@pytest.fixture
def fixture():
    with open(FIXTURE_PATH) as f:
        return json.load(f)


@pytest.fixture
def ledger(fixture):
    return build_ledger(fixture)


def test_total_outflows(ledger):
    total_out = sum(e["amount_pkr"] for e in ledger if e["direction"] == "OUT")
    assert total_out == 11742800


def test_total_inflows(ledger):
    total_in = sum(e["amount_pkr"] for e in ledger if e["direction"] == "IN")
    assert total_in == 12813600


def test_all_entries_have_non_null_dates(ledger):
    for entry in ledger:
        assert entry["event_date"] is not None, f"null event_date on {entry['cost_type']}"
        assert entry["payment_date"] is not None, f"null payment_date on {entry['cost_type']}"


def test_sale_credit_days_equals_17(ledger):
    sale_entries = [e for e in ledger if e["cost_type"] == "SALE"]
    assert len(sale_entries) == 1, "Expected exactly one SALE entry"
    assert sale_entries[0]["credit_days"] == 17
