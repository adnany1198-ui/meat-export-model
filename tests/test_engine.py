"""Tests for the rules engine against Shipment 1 fixture data."""

import datetime
import json
from pathlib import Path

from safi_engine.config import StrategyConfig
from safi_engine.cycle import ShipmentCycle
from safi_engine.engine import compute_shipment_cashflow

FIXTURES = Path(__file__).parent / "fixtures"


def _load_outflow_config() -> list[dict]:
    return json.loads((FIXTURES / "outflow_config.json").read_text())


def _shipment_1() -> ShipmentCycle:
    """Shipment 1 from cycle_detail_raw.json row 1."""
    return ShipmentCycle(
        proc_model="SUPPLIER",
        customer_id="A",
        shipment_number=1,
        cash_date=datetime.date(2026, 1, 1),
        slaughter_date=datetime.date(2026, 1, 4),
        slaughter_end_date=datetime.date(2026, 1, 5),
        send_date=datetime.date(2026, 1, 14),
        receive_date=datetime.date(2026, 1, 15),
        pay_days=9,
        weight_kg_net=8000.0,
    )


def _strategy_config() -> StrategyConfig:
    return StrategyConfig(
        usd_to_pkr=281,
        partha_rates={"SUPPLIER": 1110, "INTERNAL": 1000},
    )


class TestShipment1Outflow:
    def test_total_outflow_matches_expected(self):
        entries = compute_shipment_cashflow(
            _shipment_1(), _strategy_config(), _load_outflow_config(),
        )
        total = sum(e.amount_pkr for e in entries)
        assert total == 11_742_800

    def test_entry_count(self):
        """Partha + 14 per-kg outflow items = 15 entries."""
        entries = compute_shipment_cashflow(
            _shipment_1(), _strategy_config(), _load_outflow_config(),
        )
        assert len(entries) == 15

    def test_partha_is_first_and_correct(self):
        entries = compute_shipment_cashflow(
            _shipment_1(), _strategy_config(), _load_outflow_config(),
        )
        partha = entries[0]
        assert partha.cost_type == "Partha"
        assert partha.amount_pkr == 1110 * 8000
        assert partha.event_date == datetime.date(2026, 1, 1)

    def test_all_entries_are_outflows(self):
        entries = compute_shipment_cashflow(
            _shipment_1(), _strategy_config(), _load_outflow_config(),
        )
        assert all(e.direction == "outflow" for e in entries)

    def test_slaughter_start_items_date(self):
        """Slaughter and Animal_Trimming fire on slaughter_date."""
        entries = compute_shipment_cashflow(
            _shipment_1(), _strategy_config(), _load_outflow_config(),
        )
        by_type = {e.cost_type: e for e in entries}
        assert by_type["Slaughter"].event_date == datetime.date(2026, 1, 4)
        assert by_type["Animal_Trimming"].event_date == datetime.date(2026, 1, 4)

    def test_slaughter_end_items_date(self):
        """Freight, Clearance, etc. fire on slaughter_end_date."""
        entries = compute_shipment_cashflow(
            _shipment_1(), _strategy_config(), _load_outflow_config(),
        )
        by_type = {e.cost_type: e for e in entries}
        assert by_type["Freight"].event_date == datetime.date(2026, 1, 5)
        assert by_type["Clearance"].event_date == datetime.date(2026, 1, 5)

    def test_slaughter_end_plus1_items_date(self):
        """TPT, Data_Logger, Chilling, Polysheet fire on slaughter_end + 1."""
        entries = compute_shipment_cashflow(
            _shipment_1(), _strategy_config(), _load_outflow_config(),
        )
        by_type = {e.cost_type: e for e in entries}
        expected = datetime.date(2026, 1, 6)
        assert by_type["TPT_Slaughter"].event_date == expected
        assert by_type["Data_Logger"].event_date == expected
        assert by_type["Chilling"].event_date == expected
        assert by_type["Polysheet"].event_date == expected

    def test_individual_amounts(self):
        """Spot-check a few line items."""
        entries = compute_shipment_cashflow(
            _shipment_1(), _strategy_config(), _load_outflow_config(),
        )
        by_type = {e.cost_type: e for e in entries}
        assert by_type["Freight"].amount_pkr == 212 * 8000  # 1,696,000
        assert by_type["Chilling"].amount_pkr == 55 * 8000  # 440,000
        assert by_type["Animal_Trimming"].amount_pkr == 38.5 * 8000  # 308,000
