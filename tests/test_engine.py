"""Tests for the rules engine against Shipment 1 fixture data."""

import datetime
import json
from pathlib import Path

from safi_engine.config import CreditDays, PricingTier, StrategyConfig
from safi_engine.cycle import ShipmentCycle
from safi_engine.engine import (
    compute_full_shipment_cashflow,
    compute_sale_entry,
    compute_shipment_cashflow,
)

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
    """Minimal StrategyConfig for outflow-only tests.

    Uses the canonical partha rates.  Does not populate pricing_tiers or
    customer_credit_days (not needed for outflow computation).
    """
    return StrategyConfig(
        usd_to_pkr=281,
        partha_rates={"SUPPLIER": 1110, "INTERNAL": 1000},
    )


def _full_strategy_config() -> StrategyConfig:
    """Fully-populated StrategyConfig for full cashflow tests.

    Values match strategy_control_raw.json January row.
    """
    return StrategyConfig(
        usd_to_pkr=281,
        partha_rates={"SUPPLIER": 1110, "INTERNAL": 1000},
        pricing_tiers=[
            PricingTier(credit_days_min=10, credit_days_max=12, price_usd_per_kg=5.90),
            PricingTier(credit_days_min=13, credit_days_max=15, price_usd_per_kg=5.80),
            PricingTier(credit_days_min=16, credit_days_max=18, price_usd_per_kg=5.70),
            PricingTier(credit_days_min=19, credit_days_max=20, price_usd_per_kg=5.65),
        ],
        customer_credit_days=[
            CreditDays(month="Jan-2026", min_days=15.0, max_days=20.0, avg_days=17.5),
        ],
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


class TestFullShipmentCashflow:
    """Tests for compute_full_shipment_cashflow — the unified entry point."""

    def test_returns_16_entries(self):
        """15 outflows + 1 SALE inflow = 16 entries."""
        entries = compute_full_shipment_cashflow(
            _shipment_1(), _full_strategy_config(), _load_outflow_config(),
        )
        assert len(entries) == 16

    def test_has_one_inflow(self):
        entries = compute_full_shipment_cashflow(
            _shipment_1(), _full_strategy_config(), _load_outflow_config(),
        )
        inflows = [e for e in entries if e.direction == "inflow"]
        assert len(inflows) == 1
        assert inflows[0].cost_type == "SALE"

    def test_outflows_unchanged(self):
        """Full cashflow outflows match outflow-only computation."""
        outflow_only = compute_shipment_cashflow(
            _shipment_1(), _strategy_config(), _load_outflow_config(),
        )
        full = compute_full_shipment_cashflow(
            _shipment_1(), _full_strategy_config(), _load_outflow_config(),
        )
        full_outflows = [e for e in full if e.direction == "outflow"]
        assert len(full_outflows) == len(outflow_only)
        for a, b in zip(outflow_only, full_outflows):
            assert a.cost_type == b.cost_type
            assert a.amount_pkr == b.amount_pkr
            assert a.event_date == b.event_date

    def test_sale_amount_matches_spreadsheet(self):
        """SALE for shipment 1 = 12,813,600 PKR (8000 kg × 5.70 USD/kg × 281)."""
        entries = compute_full_shipment_cashflow(
            _shipment_1(), _full_strategy_config(), _load_outflow_config(),
        )
        sale = next(e for e in entries if e.cost_type == "SALE")
        assert sale.amount_pkr == 8000 * 5.70 * 281  # 12,813,600

    def test_sale_credit_days(self):
        """Jan avg_days=17.5 → floor=17 → payment 17 days after receive."""
        entries = compute_full_shipment_cashflow(
            _shipment_1(), _full_strategy_config(), _load_outflow_config(),
        )
        sale = next(e for e in entries if e.cost_type == "SALE")
        assert sale.event_date == datetime.date(2026, 1, 15)
        assert sale.payment_date == datetime.date(2026, 2, 1)
        assert (sale.payment_date - sale.event_date).days == 17

    def test_sale_source_assumption_is_explicit(self):
        """The source_assumption should record the price and credit days used."""
        entries = compute_full_shipment_cashflow(
            _shipment_1(), _full_strategy_config(), _load_outflow_config(),
        )
        sale = next(e for e in entries if e.cost_type == "SALE")
        assert "5.7" in sale.source_assumption
        assert "17" in sale.source_assumption
