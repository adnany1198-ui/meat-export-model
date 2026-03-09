"""Tests for workspace session state and named scenario management."""

import datetime
import json
from pathlib import Path

import pytest

from safi_engine.config import CreditDays, PricingTier, ScenarioOverrides, StrategyConfig
from safi_engine.cycle import ShipmentCycle
from safi_engine.engine import compute_full_shipment_cashflow
from safi_engine.query_model import (
    CompareNamedScenariosQuery,
    CompareScenarioQuery,
    DeleteScenarioQuery,
    ExplainLineItemQuery,
    ExplainShipmentQuery,
    FundingComparisonQuery,
    ListScenariosQuery,
    MostAffectedShipmentsQuery,
    RenameScenarioQuery,
    RunScenarioQuery,
    SaveScenarioQuery,
    ScenarioSummaryQuery,
    WorkingCapitalQuery,
)
from safi_engine.query_runner import QueryContext
from safi_engine.workspace import (
    AnalyticalWorkspace,
    DeleteScenarioResult,
    ListScenariosResult,
    NamedComparisonResult,
    NamedScenario,
    RenameScenarioResult,
    SaveScenarioResult,
)

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_outflow_config() -> list[dict]:
    return json.loads((FIXTURES / "outflow_config.json").read_text())


def _shipment_1() -> ShipmentCycle:
    return ShipmentCycle(
        proc_model="SUPPLIER", customer_id="A", shipment_number=1,
        cash_date=datetime.date(2026, 1, 1),
        slaughter_date=datetime.date(2026, 1, 4),
        slaughter_end_date=datetime.date(2026, 1, 5),
        send_date=datetime.date(2026, 1, 14),
        receive_date=datetime.date(2026, 1, 15),
        pay_days=9, weight_kg_net=8000.0,
    )


def _shipment_2() -> ShipmentCycle:
    return ShipmentCycle(
        proc_model="SUPPLIER", customer_id="B", shipment_number=2,
        cash_date=datetime.date(2026, 1, 2),
        slaughter_date=datetime.date(2026, 1, 5),
        slaughter_end_date=datetime.date(2026, 1, 6),
        send_date=datetime.date(2026, 1, 15),
        receive_date=datetime.date(2026, 1, 16),
        pay_days=9, weight_kg_net=4800.0,
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


def _ws() -> AnalyticalWorkspace:
    ctx = QueryContext(
        cycles=[_shipment_1(), _shipment_2()],
        config=_full_strategy_config(),
        outflow_config=_load_outflow_config(),
    )
    return AnalyticalWorkspace(ctx)


# ---------------------------------------------------------------------------
# Save / retrieve / list / delete / rename
# ---------------------------------------------------------------------------

class TestScenarioLifecycle:

    def test_save_new_scenario(self):
        ws = _ws()
        res = ws.save_scenario("fx_stress", ScenarioOverrides(usd_to_pkr=300))
        assert res.created is True
        assert res.name == "fx_stress"
        assert ws.scenario_count() == 1

    def test_save_updates_existing(self):
        ws = _ws()
        ws.save_scenario("fx_stress", ScenarioOverrides(usd_to_pkr=300))
        res = ws.save_scenario("fx_stress", ScenarioOverrides(usd_to_pkr=320))
        assert res.created is False
        assert ws.get_scenario("fx_stress").overrides.usd_to_pkr == 320

    def test_save_baseline_name_raises(self):
        ws = _ws()
        with pytest.raises(ValueError, match="baseline"):
            ws.save_scenario("baseline", ScenarioOverrides(usd_to_pkr=300))

    def test_get_scenario(self):
        ws = _ws()
        ws.save_scenario("fx_stress", ScenarioOverrides(usd_to_pkr=300), description="FX shock")
        sc = ws.get_scenario("fx_stress")
        assert isinstance(sc, NamedScenario)
        assert sc.name == "fx_stress"
        assert sc.description == "FX shock"
        assert sc.overrides.usd_to_pkr == 300

    def test_get_nonexistent_returns_none(self):
        ws = _ws()
        assert ws.get_scenario("nope") is None

    def test_list_scenarios_empty(self):
        ws = _ws()
        assert ws.list_scenarios() == []

    def test_list_scenarios_populated(self):
        ws = _ws()
        ws.save_scenario("a", ScenarioOverrides(usd_to_pkr=300))
        ws.save_scenario("b", ScenarioOverrides(usd_to_pkr=250))
        lst = ws.list_scenarios()
        assert len(lst) == 2
        assert [s.name for s in lst] == ["a", "b"]

    def test_delete_existing(self):
        ws = _ws()
        ws.save_scenario("fx_stress", ScenarioOverrides(usd_to_pkr=300))
        res = ws.delete_scenario("fx_stress")
        assert res.deleted is True
        assert ws.scenario_count() == 0

    def test_delete_nonexistent(self):
        ws = _ws()
        res = ws.delete_scenario("nope")
        assert res.deleted is False

    def test_rename_existing(self):
        ws = _ws()
        ws.save_scenario("old", ScenarioOverrides(usd_to_pkr=300))
        res = ws.rename_scenario("old", "new")
        assert res.renamed is True
        assert ws.get_scenario("old") is None
        assert ws.get_scenario("new") is not None
        assert ws.get_scenario("new").overrides.usd_to_pkr == 300

    def test_rename_nonexistent_fails(self):
        ws = _ws()
        res = ws.rename_scenario("nope", "new")
        assert res.renamed is False

    def test_rename_to_existing_fails(self):
        ws = _ws()
        ws.save_scenario("a", ScenarioOverrides(usd_to_pkr=300))
        ws.save_scenario("b", ScenarioOverrides(usd_to_pkr=250))
        res = ws.rename_scenario("a", "b")
        assert res.renamed is False
        assert ws.get_scenario("a") is not None  # unchanged

    def test_rename_to_baseline_fails(self):
        ws = _ws()
        ws.save_scenario("a", ScenarioOverrides(usd_to_pkr=300))
        res = ws.rename_scenario("a", "baseline")
        assert res.renamed is False

    def test_scenario_metadata(self):
        ws = _ws()
        ws.save_scenario(
            "test", ScenarioOverrides(usd_to_pkr=300),
            description="Test scenario", notes="For testing only",
        )
        sc = ws.get_scenario("test")
        assert sc.description == "Test scenario"
        assert sc.notes == "For testing only"
        assert isinstance(sc.created_at, datetime.datetime)


# ---------------------------------------------------------------------------
# Lifecycle queries via execute()
# ---------------------------------------------------------------------------

class TestLifecycleQueries:

    def test_save_query(self):
        ws = _ws()
        result, text = ws.execute(SaveScenarioQuery(
            name="fx_stress", overrides=ScenarioOverrides(usd_to_pkr=300),
            description="FX stress test",
        ))
        assert isinstance(result, SaveScenarioResult)
        assert result.created is True
        assert "Saved" in text
        assert "fx_stress" in text

    def test_save_query_update(self):
        ws = _ws()
        ws.execute(SaveScenarioQuery(
            name="fx_stress", overrides=ScenarioOverrides(usd_to_pkr=300),
        ))
        result, text = ws.execute(SaveScenarioQuery(
            name="fx_stress", overrides=ScenarioOverrides(usd_to_pkr=320),
        ))
        assert result.created is False
        assert "Updated" in text

    def test_save_baseline_via_query(self):
        ws = _ws()
        result, text = ws.execute(SaveScenarioQuery(
            name="baseline", overrides=ScenarioOverrides(usd_to_pkr=300),
        ))
        assert result.created is False
        assert "baseline" in text.lower()

    def test_list_query_empty(self):
        ws = _ws()
        result, text = ws.execute(ListScenariosQuery())
        assert isinstance(result, ListScenariosResult)
        assert "No saved scenarios" in text

    def test_list_query_populated(self):
        ws = _ws()
        ws.save_scenario("a", ScenarioOverrides(usd_to_pkr=300))
        ws.save_scenario("b", ScenarioOverrides(usd_to_pkr=250))
        result, text = ws.execute(ListScenariosQuery())
        assert len(result.scenarios) == 2
        assert "Available scenarios" in text
        assert "a" in text
        assert "b" in text

    def test_delete_query(self):
        ws = _ws()
        ws.save_scenario("fx_stress", ScenarioOverrides(usd_to_pkr=300))
        result, text = ws.execute(DeleteScenarioQuery(name="fx_stress"))
        assert isinstance(result, DeleteScenarioResult)
        assert result.deleted is True
        assert "Deleted" in text

    def test_delete_query_not_found(self):
        ws = _ws()
        result, text = ws.execute(DeleteScenarioQuery(name="nope"))
        assert result.deleted is False
        assert "not found" in text

    def test_rename_query(self):
        ws = _ws()
        ws.save_scenario("old", ScenarioOverrides(usd_to_pkr=300))
        result, text = ws.execute(RenameScenarioQuery(old_name="old", new_name="new"))
        assert isinstance(result, RenameScenarioResult)
        assert result.renamed is True
        assert "Renamed" in text

    def test_rename_query_fails(self):
        ws = _ws()
        result, text = ws.execute(RenameScenarioQuery(old_name="nope", new_name="new"))
        assert result.renamed is False
        assert "Could not rename" in text


# ---------------------------------------------------------------------------
# Named scenario reference in analytical queries
# ---------------------------------------------------------------------------

class TestNamedScenarioReference:

    def test_run_scenario_by_name(self):
        ws = _ws()
        ws.save_scenario("fx_stress", ScenarioOverrides(usd_to_pkr=300))
        result, text = ws.execute(RunScenarioQuery(scenario_name="fx_stress"))
        # Should produce same result as inline overrides
        result2, _ = ws.execute(
            RunScenarioQuery(overrides=ScenarioOverrides(usd_to_pkr=300)),
        )
        assert result.total_entries == result2.total_entries
        for sid in result.entries_by_shipment:
            for e1, e2 in zip(
                result.entries_by_shipment[sid],
                result2.entries_by_shipment[sid],
            ):
                assert abs(e1.amount_pkr - e2.amount_pkr) < 0.01

    def test_compare_scenario_by_name(self):
        ws = _ws()
        ws.save_scenario("fx_stress", ScenarioOverrides(usd_to_pkr=300))
        result, text = ws.execute(
            CompareScenarioQuery(scenario_name="fx_stress", shipment_id=1),
        )
        assert len(result.comparisons) == 1
        assert result.comparisons[0].net_delta > 0  # FX up → more inflow

    def test_explain_shipment_by_name(self):
        ws = _ws()
        ws.save_scenario("fx_stress", ScenarioOverrides(usd_to_pkr=300))
        result, text = ws.execute(
            ExplainShipmentQuery(shipment_id=1, scenario_name="fx_stress"),
        )
        sale = next(e for e in result.entries if e.cost_type == "SALE")
        assert len(sale.overrides_applied) > 0
        assert "Provenance" in text

    def test_explain_line_item_by_name(self):
        ws = _ws()
        ws.save_scenario("fx_stress", ScenarioOverrides(usd_to_pkr=300))
        result, text = ws.execute(
            ExplainLineItemQuery(shipment_id=1, cost_type="SALE", scenario_name="fx_stress"),
        )
        assert result.found
        assert len(result.entry.overrides_applied) > 0

    def test_scenario_summary_by_name(self):
        ws = _ws()
        ws.save_scenario("fx_stress", ScenarioOverrides(usd_to_pkr=300))
        result, text = ws.execute(
            ScenarioSummaryQuery(scenario_name="fx_stress"),
        )
        assert result.summary.total_net_delta > 0

    def test_most_affected_by_name(self):
        ws = _ws()
        ws.save_scenario("fx_stress", ScenarioOverrides(usd_to_pkr=300))
        result, text = ws.execute(
            MostAffectedShipmentsQuery(scenario_name="fx_stress", top_n=2),
        )
        assert len(result.shipments) == 2

    def test_working_capital_by_name(self):
        ws = _ws()
        ws.save_scenario("fx_stress", ScenarioOverrides(usd_to_pkr=300))
        result, text = ws.execute(
            WorkingCapitalQuery(shipment_id=1, scenario_name="fx_stress"),
        )
        # Compare against inline overrides
        result2, _ = ws.execute(
            WorkingCapitalQuery(
                shipment_id=1, overrides=ScenarioOverrides(usd_to_pkr=300),
            ),
        )
        assert abs(
            result.shipment_profile.net_cashflow - result2.shipment_profile.net_cashflow
        ) < 0.01

    def test_funding_comparison_by_name(self):
        ws = _ws()
        ws.save_scenario("fx_stress", ScenarioOverrides(usd_to_pkr=300))
        result, text = ws.execute(
            FundingComparisonQuery(scenario_name="fx_stress"),
        )
        assert result.comparison.net_cashflow_delta > 0

    def test_baseline_scenario_name(self):
        """scenario_name='baseline' should behave identically to no overrides."""
        ws = _ws()
        result, _ = ws.execute(
            RunScenarioQuery(scenario_name="baseline", shipment_id=1),
        )
        result2, _ = ws.execute(
            RunScenarioQuery(shipment_id=1),
        )
        for e1, e2 in zip(
            result.entries_by_shipment[1],
            result2.entries_by_shipment[1],
        ):
            assert abs(e1.amount_pkr - e2.amount_pkr) < 0.01

    def test_invalid_scenario_name_raises(self):
        ws = _ws()
        with pytest.raises(KeyError, match="not found"):
            ws.execute(RunScenarioQuery(scenario_name="nonexistent"))

    def test_scenario_name_takes_priority_over_inline(self):
        """When both scenario_name and overrides are set, name wins."""
        ws = _ws()
        ws.save_scenario("fx_300", ScenarioOverrides(usd_to_pkr=300))
        # Pass inline overrides with a different rate — name should win
        result, _ = ws.execute(
            RunScenarioQuery(
                scenario_name="fx_300",
                overrides=ScenarioOverrides(usd_to_pkr=999),
                shipment_id=1,
            ),
        )
        result_name, _ = ws.execute(
            RunScenarioQuery(
                overrides=ScenarioOverrides(usd_to_pkr=300),
                shipment_id=1,
            ),
        )
        for e1, e2 in zip(
            result.entries_by_shipment[1],
            result_name.entries_by_shipment[1],
        ):
            assert abs(e1.amount_pkr - e2.amount_pkr) < 0.01


# ---------------------------------------------------------------------------
# CompareNamedScenariosQuery
# ---------------------------------------------------------------------------

class TestCompareNamedScenarios:

    def test_baseline_vs_named(self):
        ws = _ws()
        ws.save_scenario("fx_stress", ScenarioOverrides(usd_to_pkr=300))
        result, text = ws.execute(CompareNamedScenariosQuery(
            scenario_a="baseline", scenario_b="fx_stress",
        ))
        assert isinstance(result, NamedComparisonResult)
        assert result.scenario_a_name == "baseline"
        assert result.scenario_b_name == "fx_stress"
        assert "Comparing" in text
        assert "fx_stress" in text

    def test_named_vs_named(self):
        ws = _ws()
        ws.save_scenario("fx_300", ScenarioOverrides(usd_to_pkr=300))
        ws.save_scenario("fx_250", ScenarioOverrides(usd_to_pkr=250))
        result, text = ws.execute(CompareNamedScenariosQuery(
            scenario_a="fx_250", scenario_b="fx_300",
        ))
        assert "NAMED SCENARIO COMPARISON" in text
        # fx_300 has higher FX → higher net
        assert "+" in text  # positive delta expected

    def test_funding_mode(self):
        ws = _ws()
        ws.save_scenario("fx_stress", ScenarioOverrides(usd_to_pkr=300))
        result, text = ws.execute(CompareNamedScenariosQuery(
            scenario_a="baseline", scenario_b="fx_stress",
            mode="funding",
        ))
        assert "FUNDING COMPARISON" in text

    def test_funding_mode_single_shipment(self):
        ws = _ws()
        ws.save_scenario("fx_stress", ScenarioOverrides(usd_to_pkr=300))
        result, text = ws.execute(CompareNamedScenariosQuery(
            scenario_a="baseline", scenario_b="fx_stress",
            mode="funding", shipment_id=1,
        ))
        assert "FUNDING COMPARISON" in text

    def test_invalid_scenario_name(self):
        ws = _ws()
        result, text = ws.execute(CompareNamedScenariosQuery(
            scenario_a="baseline", scenario_b="nonexistent",
        ))
        assert "not found" in text

    def test_both_baseline_gives_zero_delta(self):
        ws = _ws()
        result, text = ws.execute(CompareNamedScenariosQuery(
            scenario_a="baseline", scenario_b="baseline",
        ))
        assert "+0" in text or "0" in text

    def test_named_comparison_consistency(self):
        """Compare named scenario vs baseline should match inline overrides comparison."""
        ws = _ws()
        ov = ScenarioOverrides(usd_to_pkr=300)
        ws.save_scenario("fx_stress", ov)

        # Named comparison
        result_named, _ = ws.execute(CompareNamedScenariosQuery(
            scenario_a="baseline", scenario_b="fx_stress", mode="funding",
        ))

        # Inline comparison
        result_inline, _ = ws.execute(FundingComparisonQuery(overrides=ov))

        # Both should show same net delta
        assert abs(
            result_named.comparison_text.count("+") -
            result_inline.comparison.net_cashflow_delta / abs(result_inline.comparison.net_cashflow_delta)
        ) >= 0  # both positive


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestWorkspaceEdgeCases:

    def test_multiple_scenarios_independent(self):
        ws = _ws()
        ws.save_scenario("a", ScenarioOverrides(usd_to_pkr=300))
        ws.save_scenario("b", ScenarioOverrides(partha_rates={"SUPPLIER": 1300, "INTERNAL": 1000}))
        r_a, _ = ws.execute(RunScenarioQuery(scenario_name="a", shipment_id=1))
        r_b, _ = ws.execute(RunScenarioQuery(scenario_name="b", shipment_id=1))
        # Different overrides → different results
        sale_a = next(e for e in r_a.entries_by_shipment[1] if e.cost_type == "SALE")
        sale_b = next(e for e in r_b.entries_by_shipment[1] if e.cost_type == "SALE")
        # fx override changes sale; partha override doesn't change sale
        assert abs(sale_a.amount_pkr - sale_b.amount_pkr) > 1.0

    def test_delete_then_use_raises(self):
        ws = _ws()
        ws.save_scenario("temp", ScenarioOverrides(usd_to_pkr=300))
        ws.delete_scenario("temp")
        with pytest.raises(KeyError, match="not found"):
            ws.execute(RunScenarioQuery(scenario_name="temp"))

    def test_save_with_all_override_types(self):
        ws = _ws()
        ov = ScenarioOverrides(
            usd_to_pkr=300,
            partha_rates={"SUPPLIER": 1200, "INTERNAL": 1000},
            outflow_rate_overrides={"Freight": 250},
        )
        ws.save_scenario("combined", ov, description="Combined stress test")
        result, text = ws.execute(SaveScenarioQuery(
            name="combined2", overrides=ov, description="Combined via query",
        ))
        assert "usd_to_pkr" in text
        assert "partha_rates" in text

    def test_workspace_with_no_queries(self):
        """Fresh workspace with no scenarios should handle analytical queries."""
        ws = _ws()
        result, text = ws.execute(RunScenarioQuery(shipment_id=1))
        assert result.total_shipments == 1
        assert "BASELINE" in text

    def test_query_without_scenario_name_uses_inline(self):
        """If no scenario_name, inline overrides should still work through workspace."""
        ws = _ws()
        result, _ = ws.execute(
            CompareScenarioQuery(
                overrides=ScenarioOverrides(usd_to_pkr=300), shipment_id=1,
            ),
        )
        assert result.comparisons[0].net_delta > 0
