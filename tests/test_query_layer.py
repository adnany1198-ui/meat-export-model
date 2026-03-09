"""Tests for the structured query / action layer."""

import datetime
import json
from pathlib import Path

from safi_engine.config import CreditDays, PricingTier, ScenarioOverrides, StrategyConfig
from safi_engine.cycle import ShipmentCycle
from safi_engine.engine import CashflowEntry, compute_full_shipment_cashflow
from safi_engine.query_model import (
    CompareScenarioQuery,
    ExplainLineItemQuery,
    ExplainShipmentQuery,
    FundingComparisonQuery,
    FundingComparisonResult,
    LineItemExplanation,
    MostAffectedResult,
    MostAffectedShipmentsQuery,
    RunScenarioQuery,
    ScenarioComparisonResult,
    ScenarioImpactSummary,
    ScenarioResult,
    ScenarioSummaryQuery,
    ShipmentExplanation,
    WorkingCapitalQuery,
    WorkingCapitalResult,
)
from safi_engine.query_runner import QueryContext, execute
from safi_engine.scenario_analysis import compare_shipment_scenario, scenario_summary, compare_all_shipments
from safi_engine.working_capital import shipment_funding_profile, portfolio_funding_summary

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Test helpers (same fixtures as other test modules)
# ---------------------------------------------------------------------------

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


def _ctx() -> QueryContext:
    return QueryContext(
        cycles=[_shipment_1(), _shipment_2()],
        config=_full_strategy_config(),
        outflow_config=_load_outflow_config(),
    )


# ---------------------------------------------------------------------------
# RunScenarioQuery
# ---------------------------------------------------------------------------

class TestRunScenarioQuery:

    def test_baseline_single_shipment(self):
        result, text = execute(RunScenarioQuery(shipment_id=1), _ctx())
        assert isinstance(result, ScenarioResult)
        assert result.total_shipments == 1
        assert 1 in result.entries_by_shipment
        assert result.total_entries == 16
        assert "BASELINE" in text

    def test_baseline_all_shipments(self):
        result, text = execute(RunScenarioQuery(), _ctx())
        assert result.total_shipments == 2
        assert result.total_entries == 32

    def test_scenario_with_overrides(self):
        q = RunScenarioQuery(overrides=ScenarioOverrides(usd_to_pkr=300))
        result, text = execute(q, _ctx())
        assert result.total_shipments == 2
        assert "SCENARIO" in text

    def test_missing_shipment(self):
        result, text = execute(RunScenarioQuery(shipment_id=999), _ctx())
        assert "not found" in text

    def test_entries_match_engine_directly(self):
        """Query layer entries must match direct engine call."""
        ctx = _ctx()
        result, _ = execute(RunScenarioQuery(shipment_id=1), ctx)
        direct = compute_full_shipment_cashflow(
            _shipment_1(), ctx.config, ctx.outflow_config,
        )
        query_entries = result.entries_by_shipment[1]
        assert len(query_entries) == len(direct)
        for qe, de in zip(query_entries, direct):
            assert qe.cost_type == de.cost_type
            assert abs(qe.amount_pkr - de.amount_pkr) < 0.01


# ---------------------------------------------------------------------------
# CompareScenarioQuery
# ---------------------------------------------------------------------------

class TestCompareScenarioQuery:

    def test_single_shipment_comparison(self):
        q = CompareScenarioQuery(
            overrides=ScenarioOverrides(usd_to_pkr=300), shipment_id=1,
        )
        result, text = execute(q, _ctx())
        assert isinstance(result, ScenarioComparisonResult)
        assert len(result.comparisons) == 1
        assert result.comparisons[0].shipment_id == 1
        assert "Shipment 1" in text

    def test_all_shipments_comparison(self):
        q = CompareScenarioQuery(overrides=ScenarioOverrides(usd_to_pkr=300))
        result, text = execute(q, _ctx())
        assert len(result.comparisons) == 2
        assert result.summary is not None
        assert "SCENARIO COMPARISON SUMMARY" in text

    def test_no_override_zero_delta(self):
        q = CompareScenarioQuery(overrides=ScenarioOverrides(), shipment_id=1)
        result, _ = execute(q, _ctx())
        comp = result.comparisons[0]
        assert abs(comp.net_delta) < 0.01

    def test_matches_direct_scenario_analysis(self):
        """Query result must match scenario_analysis module directly."""
        ctx = _ctx()
        q = CompareScenarioQuery(
            overrides=ScenarioOverrides(usd_to_pkr=300), shipment_id=1,
        )
        result, _ = execute(q, ctx)
        direct = compare_shipment_scenario(
            _shipment_1(), ctx.config, ctx.outflow_config,
            ScenarioOverrides(usd_to_pkr=300),
        )
        assert abs(result.comparisons[0].net_delta - direct.net_delta) < 0.01

    def test_missing_shipment(self):
        q = CompareScenarioQuery(
            overrides=ScenarioOverrides(usd_to_pkr=300), shipment_id=999,
        )
        _, text = execute(q, _ctx())
        assert "not found" in text


# ---------------------------------------------------------------------------
# ExplainShipmentQuery
# ---------------------------------------------------------------------------

class TestExplainShipmentQuery:

    def test_basic_explanation(self):
        result, text = execute(ExplainShipmentQuery(shipment_id=1), _ctx())
        assert isinstance(result, ShipmentExplanation)
        assert result.shipment_id == 1
        assert result.customer_id == "A"
        assert len(result.entries) == 16

    def test_provenance_fields_present(self):
        """Explanation should surface provenance from CashflowEntry."""
        result, text = execute(ExplainShipmentQuery(shipment_id=1), _ctx())
        for e in result.entries:
            assert e.rule_name != ""
            assert e.formula_description != ""
            assert e.timing_basis != ""
        assert "Provenance Detail" in text

    def test_totals_match_engine(self):
        ctx = _ctx()
        result, _ = execute(ExplainShipmentQuery(shipment_id=1), ctx)
        entries = compute_full_shipment_cashflow(
            _shipment_1(), ctx.config, ctx.outflow_config,
        )
        expected_out = sum(e.amount_pkr for e in entries if e.direction == "outflow")
        expected_in = sum(e.amount_pkr for e in entries if e.direction == "inflow")
        assert abs(result.total_outflow - expected_out) < 0.01
        assert abs(result.total_inflow - expected_in) < 0.01

    def test_with_overrides(self):
        q = ExplainShipmentQuery(
            shipment_id=1, overrides=ScenarioOverrides(usd_to_pkr=300),
        )
        result, text = execute(q, _ctx())
        # Sale entry should have override tracking
        sale = next(e for e in result.entries if e.cost_type == "SALE")
        assert len(sale.overrides_applied) > 0

    def test_missing_shipment(self):
        _, text = execute(ExplainShipmentQuery(shipment_id=999), _ctx())
        assert "not found" in text

    def test_text_contains_rule_and_formula(self):
        _, text = execute(ExplainShipmentQuery(shipment_id=1), _ctx())
        assert "partha" in text.lower() or "Partha" in text
        assert "Formula" in text


# ---------------------------------------------------------------------------
# ExplainLineItemQuery
# ---------------------------------------------------------------------------

class TestExplainLineItemQuery:

    def test_partha_explanation(self):
        q = ExplainLineItemQuery(shipment_id=1, cost_type="Partha")
        result, text = execute(q, _ctx())
        assert isinstance(result, LineItemExplanation)
        assert result.found is True
        assert result.entry is not None
        assert result.entry.cost_type == "Partha"
        assert "LINE ITEM" in text

    def test_sale_explanation(self):
        q = ExplainLineItemQuery(shipment_id=1, cost_type="SALE")
        result, text = execute(q, _ctx())
        assert result.found is True
        assert result.entry.direction == "inflow"

    def test_provenance_in_text(self):
        q = ExplainLineItemQuery(shipment_id=1, cost_type="Partha")
        _, text = execute(q, _ctx())
        assert "Rule" in text
        assert "Formula" in text
        assert "Inputs" in text

    def test_not_found_cost_type(self):
        q = ExplainLineItemQuery(shipment_id=1, cost_type="NonExistent")
        result, text = execute(q, _ctx())
        assert result.found is False
        assert "not found" in text

    def test_not_found_shipment(self):
        q = ExplainLineItemQuery(shipment_id=999, cost_type="Partha")
        _, text = execute(q, _ctx())
        assert "not found" in text

    def test_with_overrides(self):
        q = ExplainLineItemQuery(
            shipment_id=1, cost_type="SALE",
            overrides=ScenarioOverrides(usd_to_pkr=300),
        )
        result, text = execute(q, _ctx())
        assert result.found
        assert len(result.entry.overrides_applied) > 0
        assert "Overrides" in text


# ---------------------------------------------------------------------------
# ScenarioSummaryQuery
# ---------------------------------------------------------------------------

class TestScenarioSummaryQuery:

    def test_basic_summary(self):
        q = ScenarioSummaryQuery(overrides=ScenarioOverrides(usd_to_pkr=300))
        result, text = execute(q, _ctx())
        assert isinstance(result, ScenarioImpactSummary)
        assert result.summary is not None
        assert result.summary.shipment_count == 2
        assert "SCENARIO COMPARISON SUMMARY" in text

    def test_no_override_zero_delta(self):
        q = ScenarioSummaryQuery(overrides=ScenarioOverrides())
        result, _ = execute(q, _ctx())
        assert abs(result.summary.total_net_delta) < 0.01

    def test_matches_direct_call(self):
        ctx = _ctx()
        ov = ScenarioOverrides(usd_to_pkr=300)
        q = ScenarioSummaryQuery(overrides=ov)
        result, _ = execute(q, ctx)
        comps = compare_all_shipments(ctx.cycles, ctx.config, ctx.outflow_config, ov)
        direct = scenario_summary(comps, ov)
        assert abs(result.summary.total_net_delta - direct.total_net_delta) < 0.01


# ---------------------------------------------------------------------------
# MostAffectedShipmentsQuery
# ---------------------------------------------------------------------------

class TestMostAffectedShipmentsQuery:

    def test_basic(self):
        q = MostAffectedShipmentsQuery(
            overrides=ScenarioOverrides(usd_to_pkr=300), top_n=2,
        )
        result, text = execute(q, _ctx())
        assert isinstance(result, MostAffectedResult)
        assert len(result.shipments) == 2
        assert "MOST AFFECTED" in text

    def test_ranked_by_abs_delta(self):
        q = MostAffectedShipmentsQuery(
            overrides=ScenarioOverrides(usd_to_pkr=300), top_n=2,
        )
        result, _ = execute(q, _ctx())
        deltas = [abs(c.net_delta) for c in result.shipments]
        assert deltas == sorted(deltas, reverse=True)

    def test_top_1(self):
        q = MostAffectedShipmentsQuery(
            overrides=ScenarioOverrides(usd_to_pkr=300), top_n=1,
        )
        result, _ = execute(q, _ctx())
        assert len(result.shipments) == 1


# ---------------------------------------------------------------------------
# WorkingCapitalQuery
# ---------------------------------------------------------------------------

class TestWorkingCapitalQuery:

    def test_single_shipment(self):
        q = WorkingCapitalQuery(shipment_id=1)
        result, text = execute(q, _ctx())
        assert isinstance(result, WorkingCapitalResult)
        assert result.shipment_profile is not None
        assert result.portfolio_summary is None
        assert "FUNDING PROFILE" in text

    def test_portfolio(self):
        q = WorkingCapitalQuery()
        result, text = execute(q, _ctx())
        assert result.portfolio_summary is not None
        assert result.shipment_profile is None
        assert "PORTFOLIO FUNDING SUMMARY" in text

    def test_matches_direct_call(self):
        ctx = _ctx()
        q = WorkingCapitalQuery(shipment_id=1)
        result, _ = execute(q, ctx)
        direct = shipment_funding_profile(
            _shipment_1(), ctx.config, ctx.outflow_config,
        )
        assert abs(result.shipment_profile.peak_deficit - direct.peak_deficit) < 0.01
        assert abs(result.shipment_profile.net_cashflow - direct.net_cashflow) < 0.01

    def test_portfolio_matches_direct(self):
        ctx = _ctx()
        q = WorkingCapitalQuery()
        result, _ = execute(q, ctx)
        direct = portfolio_funding_summary(
            ctx.cycles, ctx.config, ctx.outflow_config,
        )
        assert abs(result.portfolio_summary.net_cashflow - direct.net_cashflow) < 0.01

    def test_with_overrides(self):
        q = WorkingCapitalQuery(
            shipment_id=1, overrides=ScenarioOverrides(usd_to_pkr=300),
        )
        result, _ = execute(q, _ctx())
        baseline_q = WorkingCapitalQuery(shipment_id=1)
        baseline_result, _ = execute(baseline_q, _ctx())
        # Higher FX → higher inflow → better net
        assert result.shipment_profile.net_cashflow > baseline_result.shipment_profile.net_cashflow

    def test_missing_shipment(self):
        q = WorkingCapitalQuery(shipment_id=999)
        _, text = execute(q, _ctx())
        assert "not found" in text


# ---------------------------------------------------------------------------
# FundingComparisonQuery
# ---------------------------------------------------------------------------

class TestFundingComparisonQuery:

    def test_single_shipment(self):
        q = FundingComparisonQuery(
            overrides=ScenarioOverrides(usd_to_pkr=300), shipment_id=1,
        )
        result, text = execute(q, _ctx())
        assert isinstance(result, FundingComparisonResult)
        assert result.comparison is not None
        assert "FUNDING COMPARISON" in text

    def test_portfolio(self):
        q = FundingComparisonQuery(overrides=ScenarioOverrides(usd_to_pkr=300))
        result, text = execute(q, _ctx())
        assert result.comparison is not None
        assert result.comparison.net_cashflow_delta > 0

    def test_no_override_zero_delta(self):
        q = FundingComparisonQuery(overrides=ScenarioOverrides(), shipment_id=1)
        result, _ = execute(q, _ctx())
        assert abs(result.comparison.net_cashflow_delta) < 0.01
        assert result.comparison.negative_days_delta == 0

    def test_missing_shipment(self):
        q = FundingComparisonQuery(
            overrides=ScenarioOverrides(usd_to_pkr=300), shipment_id=999,
        )
        _, text = execute(q, _ctx())
        assert "not found" in text

    def test_higher_cost_worsens_funding(self):
        q = FundingComparisonQuery(
            overrides=ScenarioOverrides(partha_rates={"SUPPLIER": 1300, "INTERNAL": 1000}),
            shipment_id=1,
        )
        result, _ = execute(q, _ctx())
        assert result.comparison.net_cashflow_delta < 0
        assert result.comparison.peak_deficit_delta < 0
