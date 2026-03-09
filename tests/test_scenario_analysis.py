"""Tests for scenario comparison / analysis layer."""

import datetime
import json
from pathlib import Path

from safi_engine.config import CreditDays, PricingTier, ScenarioOverrides, StrategyConfig
from safi_engine.cycle import ShipmentCycle
from safi_engine.scenario_analysis import (
    AggregateScenarioSummary,
    LineItemDelta,
    ShipmentScenarioComparison,
    aggregate_deltas_by_line_item,
    compare_all_shipments,
    compare_shipment_scenario,
    format_aggregate_summary,
    format_shipment_comparison,
    scenario_summary,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _load_outflow_config() -> list[dict]:
    return json.loads((FIXTURES / "outflow_config.json").read_text())


def _shipment_1() -> ShipmentCycle:
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


def _shipment_2() -> ShipmentCycle:
    return ShipmentCycle(
        proc_model="SUPPLIER",
        customer_id="B",
        shipment_number=2,
        cash_date=datetime.date(2026, 1, 2),
        slaughter_date=datetime.date(2026, 1, 5),
        slaughter_end_date=datetime.date(2026, 1, 6),
        send_date=datetime.date(2026, 1, 15),
        receive_date=datetime.date(2026, 1, 16),
        pay_days=9,
        weight_kg_net=4800.0,
    )


def _full_strategy_config() -> StrategyConfig:
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


class TestSingleShipmentComparison:
    """Tests for compare_shipment_scenario on a single shipment."""

    def test_returns_comparison_dataclass(self):
        comp = compare_shipment_scenario(
            _shipment_1(), _full_strategy_config(), _load_outflow_config(),
            ScenarioOverrides(usd_to_pkr=300),
        )
        assert isinstance(comp, ShipmentScenarioComparison)
        assert comp.shipment_id == 1
        assert comp.customer_id == "A"

    def test_fx_override_increases_inflow(self):
        """Higher FX rate means higher SALE inflow in PKR."""
        comp = compare_shipment_scenario(
            _shipment_1(), _full_strategy_config(), _load_outflow_config(),
            ScenarioOverrides(usd_to_pkr=300),
        )
        # Outflows unchanged (PKR-denominated)
        assert abs(comp.outflow_delta) < 0.01
        # Inflow increases (higher PKR per USD)
        assert comp.inflow_delta > 0
        assert comp.net_delta > 0

        # Check exact SALE delta
        sale = next(li for li in comp.line_items if li.cost_type == "SALE")
        expected_baseline = 8000 * 5.70 * 281
        expected_scenario = 8000 * 5.70 * 300
        assert abs(sale.baseline_amount - expected_baseline) < 0.01
        assert abs(sale.scenario_amount - expected_scenario) < 0.01
        assert abs(sale.delta - (expected_scenario - expected_baseline)) < 0.01

    def test_partha_rate_override_increases_outflow(self):
        """Higher partha rate means higher outflow."""
        comp = compare_shipment_scenario(
            _shipment_1(), _full_strategy_config(), _load_outflow_config(),
            ScenarioOverrides(partha_rates={"SUPPLIER": 1200, "INTERNAL": 1000}),
        )
        partha = next(li for li in comp.line_items if li.cost_type == "Partha")
        assert partha.delta == (1200 - 1110) * 8000
        assert comp.outflow_delta > 0
        assert comp.net_delta < 0  # higher outflow -> lower net

    def test_outflow_rate_override(self):
        """Overriding Freight rate changes that line item only."""
        comp = compare_shipment_scenario(
            _shipment_1(), _full_strategy_config(), _load_outflow_config(),
            ScenarioOverrides(outflow_rate_overrides={"Freight": 250}),
        )
        freight = next(li for li in comp.line_items if li.cost_type == "Freight")
        assert abs(freight.delta - (250 - 212) * 8000) < 0.01
        # Other outflows should have zero delta
        others = [li for li in comp.line_items if li.cost_type not in ("Freight", "SALE")]
        for li in others:
            assert abs(li.delta) < 0.01

    def test_line_items_have_overrides_metadata(self):
        """Overridden line items carry override descriptions."""
        comp = compare_shipment_scenario(
            _shipment_1(), _full_strategy_config(), _load_outflow_config(),
            ScenarioOverrides(usd_to_pkr=300),
        )
        sale = next(li for li in comp.line_items if li.cost_type == "SALE")
        assert any("usd_to_pkr" in o for o in sale.overrides_applied)

    def test_format_does_not_raise(self):
        """format_shipment_comparison produces a non-empty string."""
        comp = compare_shipment_scenario(
            _shipment_1(), _full_strategy_config(), _load_outflow_config(),
            ScenarioOverrides(usd_to_pkr=300),
        )
        text = format_shipment_comparison(comp)
        assert len(text) > 100
        assert "Shipment 1" in text


class TestNoOverrideZeroDeltas:
    """An empty ScenarioOverrides should produce zero deltas everywhere."""

    def test_zero_deltas_single_shipment(self):
        comp = compare_shipment_scenario(
            _shipment_1(), _full_strategy_config(), _load_outflow_config(),
            ScenarioOverrides(),
        )
        assert abs(comp.net_delta) < 0.01
        assert abs(comp.outflow_delta) < 0.01
        assert abs(comp.inflow_delta) < 0.01
        for li in comp.line_items:
            assert abs(li.delta) < 0.01, f"{li.cost_type} has non-zero delta: {li.delta}"

    def test_zero_deltas_aggregation(self):
        cycles = [_shipment_1(), _shipment_2()]
        comparisons = compare_all_shipments(
            cycles, _full_strategy_config(), _load_outflow_config(),
            ScenarioOverrides(),
        )
        summary = scenario_summary(comparisons, ScenarioOverrides())
        assert abs(summary.total_net_delta) < 0.01
        assert summary.shipments_affected == 0


class TestAllShipmentAggregation:
    """Tests for multi-shipment comparison and aggregation."""

    def test_compare_all_returns_list(self):
        cycles = [_shipment_1(), _shipment_2()]
        comps = compare_all_shipments(
            cycles, _full_strategy_config(), _load_outflow_config(),
            ScenarioOverrides(usd_to_pkr=300),
        )
        assert len(comps) == 2
        assert all(isinstance(c, ShipmentScenarioComparison) for c in comps)

    def test_aggregate_deltas_by_line_item(self):
        cycles = [_shipment_1(), _shipment_2()]
        comps = compare_all_shipments(
            cycles, _full_strategy_config(), _load_outflow_config(),
            ScenarioOverrides(usd_to_pkr=300),
        )
        deltas = aggregate_deltas_by_line_item(comps)
        # Only SALE should have a non-zero delta for FX override
        assert "SALE" in deltas
        assert deltas["SALE"] > 0
        for item, delta in deltas.items():
            if item != "SALE":
                assert abs(delta) < 0.01

    def test_scenario_summary_structure(self):
        cycles = [_shipment_1(), _shipment_2()]
        overrides = ScenarioOverrides(usd_to_pkr=300)
        comps = compare_all_shipments(
            cycles, _full_strategy_config(), _load_outflow_config(), overrides,
        )
        summary = scenario_summary(comps, overrides)
        assert isinstance(summary, AggregateScenarioSummary)
        assert summary.shipment_count == 2
        assert summary.shipments_affected == 2
        assert summary.total_net_delta > 0
        assert "FX rate" in summary.overrides_description[0]

    def test_summary_net_delta_equals_sum(self):
        """Total net delta should equal sum of individual shipment deltas."""
        cycles = [_shipment_1(), _shipment_2()]
        overrides = ScenarioOverrides(
            usd_to_pkr=300,
            partha_rates={"SUPPLIER": 1200, "INTERNAL": 1050},
        )
        comps = compare_all_shipments(
            cycles, _full_strategy_config(), _load_outflow_config(), overrides,
        )
        summary = scenario_summary(comps, overrides)
        individual_sum = sum(c.net_delta for c in comps)
        assert abs(summary.total_net_delta - individual_sum) < 0.01

    def test_format_summary_does_not_raise(self):
        cycles = [_shipment_1(), _shipment_2()]
        overrides = ScenarioOverrides(usd_to_pkr=300)
        comps = compare_all_shipments(
            cycles, _full_strategy_config(), _load_outflow_config(), overrides,
        )
        summary = scenario_summary(comps, overrides)
        text = format_aggregate_summary(summary)
        assert len(text) > 100
        assert "SCENARIO COMPARISON SUMMARY" in text


class TestFxAndRateDirectionality:
    """Verify that FX and rate overrides produce expected directional changes."""

    def test_higher_fx_increases_net(self):
        """PKR depreciation (higher usd_to_pkr) increases net cashflow."""
        comp = compare_shipment_scenario(
            _shipment_1(), _full_strategy_config(), _load_outflow_config(),
            ScenarioOverrides(usd_to_pkr=300),  # 281 -> 300
        )
        assert comp.net_delta > 0

    def test_lower_fx_decreases_net(self):
        """PKR appreciation (lower usd_to_pkr) decreases net cashflow."""
        comp = compare_shipment_scenario(
            _shipment_1(), _full_strategy_config(), _load_outflow_config(),
            ScenarioOverrides(usd_to_pkr=260),  # 281 -> 260
        )
        assert comp.net_delta < 0

    def test_higher_partha_rate_decreases_net(self):
        """Higher procurement cost decreases net cashflow."""
        comp = compare_shipment_scenario(
            _shipment_1(), _full_strategy_config(), _load_outflow_config(),
            ScenarioOverrides(partha_rates={"SUPPLIER": 1300, "INTERNAL": 1000}),
        )
        assert comp.net_delta < 0

    def test_higher_freight_rate_decreases_net(self):
        """Higher freight rate decreases net cashflow."""
        comp = compare_shipment_scenario(
            _shipment_1(), _full_strategy_config(), _load_outflow_config(),
            ScenarioOverrides(outflow_rate_overrides={"Freight": 300}),
        )
        assert comp.net_delta < 0

    def test_combined_fx_up_and_cost_up(self):
        """FX up + cost up: net effect depends on magnitudes."""
        comp = compare_shipment_scenario(
            _shipment_1(), _full_strategy_config(), _load_outflow_config(),
            ScenarioOverrides(
                usd_to_pkr=300,
                partha_rates={"SUPPLIER": 1200, "INTERNAL": 1000},
            ),
        )
        # FX boost to inflow should dominate small partha increase
        # SALE delta = 8000 * 5.70 * (300-281) = 866,400
        # Partha delta = (1200-1110) * 8000 = 720,000
        assert comp.inflow_delta > 0
        assert comp.outflow_delta > 0
        assert comp.net_delta > 0  # FX effect is larger
