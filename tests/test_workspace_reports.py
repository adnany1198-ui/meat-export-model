"""Tests for saved analysis artifacts / reports in the analytical workspace."""

import datetime
import json
from pathlib import Path

import pytest

from safi_engine.config import CreditDays, PricingTier, ScenarioOverrides, StrategyConfig
from safi_engine.cycle import ShipmentCycle
from safi_engine.query_model import (
    CompareNamedScenariosQuery,
    CompareScenarioQuery,
    DeleteReportQuery,
    ExplainLineItemQuery,
    ExplainShipmentQuery,
    FundingComparisonQuery,
    GetReportQuery,
    ListReportsQuery,
    RenameReportQuery,
    RunScenarioQuery,
    SaveReportQuery,
    ScenarioSummaryQuery,
    WorkingCapitalQuery,
)
from safi_engine.query_runner import QueryContext
from safi_engine.workspace import AnalyticalWorkspace
from safi_engine.workspace_reports import (
    DeleteReportResult,
    GetReportResult,
    ListReportsResult,
    RenameReportResult,
    ReportType,
    SavedReport,
    SaveReportResult,
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
    ws = AnalyticalWorkspace(ctx)
    ws.save_scenario("fx_stress", ScenarioOverrides(usd_to_pkr=300), description="FX shock")
    return ws


# ---------------------------------------------------------------------------
# Report lifecycle: save / list / get / delete / rename
# ---------------------------------------------------------------------------

class TestReportLifecycle:

    def test_save_report_from_query(self):
        ws = _ws()
        q = SaveReportQuery(
            name="ship1_audit",
            source_query=ExplainShipmentQuery(shipment_id=1),
            description="Ship 1 baseline audit",
        )
        result, text = ws.execute(q)
        assert isinstance(result, SaveReportResult)
        assert result.created is True
        assert result.name == "ship1_audit"
        assert "Saved" in text
        assert "ship1_audit" in text
        assert ws.report_count() == 1

    def test_save_report_updates_existing(self):
        ws = _ws()
        ws.execute(SaveReportQuery(
            name="rpt", source_query=ExplainShipmentQuery(shipment_id=1),
        ))
        result, text = ws.execute(SaveReportQuery(
            name="rpt", source_query=ExplainShipmentQuery(shipment_id=2),
        ))
        assert result.created is False
        assert "Updated" in text
        assert ws.report_count() == 1

    def test_save_report_with_precomputed_result(self):
        ws = _ws()
        # First execute a query to get result + text
        source = CompareScenarioQuery(overrides=ScenarioOverrides(usd_to_pkr=300))
        result, text = ws.execute(source)
        # Then save it directly
        save_result, save_text = ws.execute(SaveReportQuery(
            name="fx_comp",
            source_query=source,
            result=result,
            formatted_text=text,
            description="Pre-computed FX comparison",
        ))
        assert save_result.created is True
        # Retrieve and verify text matches
        get_result = ws.get_report("fx_comp")
        assert get_result.report.formatted_text == text

    def test_list_reports_empty(self):
        ws = _ws()
        result, text = ws.execute(ListReportsQuery())
        assert isinstance(result, ListReportsResult)
        assert len(result.reports) == 0
        assert "No saved reports" in text

    def test_list_reports_populated(self):
        ws = _ws()
        ws.execute(SaveReportQuery(
            name="a", source_query=ExplainShipmentQuery(shipment_id=1),
        ))
        ws.execute(SaveReportQuery(
            name="b", source_query=WorkingCapitalQuery(shipment_id=1),
        ))
        result, text = ws.execute(ListReportsQuery())
        assert len(result.reports) == 2
        assert "Available reports (2)" in text
        assert "a" in text
        assert "b" in text

    def test_get_report_found(self):
        ws = _ws()
        ws.execute(SaveReportQuery(
            name="ship1", source_query=ExplainShipmentQuery(shipment_id=1),
            description="Ship 1 audit",
        ))
        result, text = ws.execute(GetReportQuery(name="ship1"))
        assert isinstance(result, GetReportResult)
        assert result.found is True
        assert result.report is not None
        assert "REPORT: ship1" in text
        assert "Ship 1 audit" in text
        # Should contain the original formatted text
        assert "SHIPMENT EXPLANATION" in text

    def test_get_report_not_found(self):
        ws = _ws()
        result, text = ws.execute(GetReportQuery(name="nope"))
        assert result.found is False
        assert "not found" in text

    def test_delete_report_existing(self):
        ws = _ws()
        ws.execute(SaveReportQuery(
            name="temp", source_query=ExplainShipmentQuery(shipment_id=1),
        ))
        result, text = ws.execute(DeleteReportQuery(name="temp"))
        assert isinstance(result, DeleteReportResult)
        assert result.deleted is True
        assert "Deleted" in text
        assert ws.report_count() == 0

    def test_delete_report_not_found(self):
        ws = _ws()
        result, text = ws.execute(DeleteReportQuery(name="nope"))
        assert result.deleted is False
        assert "not found" in text

    def test_rename_report(self):
        ws = _ws()
        ws.execute(SaveReportQuery(
            name="old", source_query=ExplainShipmentQuery(shipment_id=1),
        ))
        result, text = ws.execute(RenameReportQuery(old_name="old", new_name="new"))
        assert isinstance(result, RenameReportResult)
        assert result.renamed is True
        assert "Renamed" in text
        assert ws.get_report("old").found is False
        assert ws.get_report("new").found is True

    def test_rename_report_nonexistent_fails(self):
        ws = _ws()
        result, text = ws.execute(RenameReportQuery(old_name="nope", new_name="new"))
        assert result.renamed is False
        assert "Could not rename" in text

    def test_rename_report_conflict_fails(self):
        ws = _ws()
        ws.execute(SaveReportQuery(
            name="a", source_query=ExplainShipmentQuery(shipment_id=1),
        ))
        ws.execute(SaveReportQuery(
            name="b", source_query=ExplainShipmentQuery(shipment_id=2),
        ))
        result, text = ws.execute(RenameReportQuery(old_name="a", new_name="b"))
        assert result.renamed is False


# ---------------------------------------------------------------------------
# Saving reports from multiple query types
# ---------------------------------------------------------------------------

class TestSaveFromQueryTypes:

    def test_from_compare_scenario(self):
        ws = _ws()
        ws.execute(SaveReportQuery(
            name="fx_comp",
            source_query=CompareScenarioQuery(
                overrides=ScenarioOverrides(usd_to_pkr=300), shipment_id=1,
            ),
        ))
        rpt = ws.get_report("fx_comp").report
        assert rpt.report_type == ReportType.SCENARIO_COMPARISON
        assert "Shipment 1" in rpt.formatted_text

    def test_from_compare_named_scenarios(self):
        ws = _ws()
        ws.save_scenario("cost_up", ScenarioOverrides(partha_rates={"SUPPLIER": 1300, "INTERNAL": 1000}))
        ws.execute(SaveReportQuery(
            name="fx_vs_cost",
            source_query=CompareNamedScenariosQuery(
                scenario_a="fx_stress", scenario_b="cost_up",
            ),
        ))
        rpt = ws.get_report("fx_vs_cost").report
        assert rpt.report_type == ReportType.NAMED_COMPARISON
        assert "Comparing" in rpt.formatted_text

    def test_from_working_capital(self):
        ws = _ws()
        ws.execute(SaveReportQuery(
            name="wc_ship1",
            source_query=WorkingCapitalQuery(shipment_id=1),
        ))
        rpt = ws.get_report("wc_ship1").report
        assert rpt.report_type == ReportType.WORKING_CAPITAL
        assert "FUNDING PROFILE" in rpt.formatted_text

    def test_from_funding_comparison(self):
        ws = _ws()
        ws.execute(SaveReportQuery(
            name="funding_fx",
            source_query=FundingComparisonQuery(
                overrides=ScenarioOverrides(usd_to_pkr=300),
            ),
        ))
        rpt = ws.get_report("funding_fx").report
        assert rpt.report_type == ReportType.FUNDING_REPORT
        assert "FUNDING COMPARISON" in rpt.formatted_text

    def test_from_explain_shipment(self):
        ws = _ws()
        ws.execute(SaveReportQuery(
            name="ship1_audit",
            source_query=ExplainShipmentQuery(shipment_id=1),
        ))
        rpt = ws.get_report("ship1_audit").report
        assert rpt.report_type == ReportType.SHIPMENT_AUDIT
        assert "SHIPMENT EXPLANATION" in rpt.formatted_text
        assert "Provenance" in rpt.formatted_text

    def test_from_explain_line_item(self):
        ws = _ws()
        ws.execute(SaveReportQuery(
            name="partha_detail",
            source_query=ExplainLineItemQuery(shipment_id=1, cost_type="Partha"),
        ))
        rpt = ws.get_report("partha_detail").report
        assert rpt.report_type == ReportType.LINE_ITEM_AUDIT
        assert "LINE ITEM" in rpt.formatted_text

    def test_from_scenario_summary(self):
        ws = _ws()
        ws.execute(SaveReportQuery(
            name="fx_summary",
            source_query=ScenarioSummaryQuery(
                overrides=ScenarioOverrides(usd_to_pkr=300),
            ),
        ))
        rpt = ws.get_report("fx_summary").report
        assert rpt.report_type == ReportType.SCENARIO_SUMMARY
        assert "SCENARIO COMPARISON SUMMARY" in rpt.formatted_text

    def test_from_run_scenario(self):
        ws = _ws()
        ws.execute(SaveReportQuery(
            name="scenario_run",
            source_query=RunScenarioQuery(
                overrides=ScenarioOverrides(usd_to_pkr=300), shipment_id=1,
            ),
        ))
        rpt = ws.get_report("scenario_run").report
        assert rpt.report_type == ReportType.SCENARIO_RUN

    def test_from_named_scenario(self):
        """Save a report using a named scenario reference."""
        ws = _ws()
        ws.execute(SaveReportQuery(
            name="fx_wc",
            source_query=WorkingCapitalQuery(
                shipment_id=1, scenario_name="fx_stress",
            ),
            description="Working capital under FX stress",
        ))
        rpt = ws.get_report("fx_wc").report
        assert rpt.report_type == ReportType.WORKING_CAPITAL
        assert rpt.description == "Working capital under FX stress"


# ---------------------------------------------------------------------------
# Saved report text/result consistency
# ---------------------------------------------------------------------------

class TestReportConsistency:

    def test_saved_text_matches_live_query(self):
        """Report text snapshot should match a fresh execution."""
        ws = _ws()
        q = ExplainShipmentQuery(shipment_id=1)
        # Execute live
        _, live_text = ws.execute(q)
        # Save report
        ws.execute(SaveReportQuery(name="live", source_query=q))
        rpt = ws.get_report("live").report
        assert rpt.formatted_text == live_text

    def test_saved_result_amounts_match_live(self):
        """Report result object should match a fresh execution."""
        ws = _ws()
        q = WorkingCapitalQuery(shipment_id=1)
        live_result, _ = ws.execute(q)
        ws.execute(SaveReportQuery(name="wc", source_query=q))
        rpt = ws.get_report("wc").report
        saved_result = rpt.result
        assert abs(
            saved_result.shipment_profile.net_cashflow
            - live_result.shipment_profile.net_cashflow
        ) < 0.01

    def test_report_preserves_metadata(self):
        ws = _ws()
        ws.execute(SaveReportQuery(
            name="test", source_query=ExplainShipmentQuery(shipment_id=1),
            description="Test report", notes="For testing",
        ))
        rpt = ws.get_report("test").report
        assert rpt.description == "Test report"
        assert rpt.notes == "For testing"
        assert isinstance(rpt.created_at, datetime.datetime)

    def test_report_type_label(self):
        ws = _ws()
        ws.execute(SaveReportQuery(
            name="test", source_query=ExplainShipmentQuery(shipment_id=1),
        ))
        rpt = ws.get_report("test").report
        assert rpt.report_type.label == "Shipment Audit"

    def test_get_report_shows_full_text(self):
        """GetReportQuery output should include both header and full report text."""
        ws = _ws()
        ws.execute(SaveReportQuery(
            name="audit", source_query=ExplainShipmentQuery(shipment_id=1),
            description="Full audit",
        ))
        _, text = ws.execute(GetReportQuery(name="audit"))
        assert "REPORT: audit" in text
        assert "Shipment Audit" in text
        assert "Full audit" in text
        assert "SHIPMENT EXPLANATION" in text

    def test_list_reports_shows_types(self):
        ws = _ws()
        ws.execute(SaveReportQuery(
            name="a", source_query=ExplainShipmentQuery(shipment_id=1),
        ))
        ws.execute(SaveReportQuery(
            name="b", source_query=FundingComparisonQuery(
                overrides=ScenarioOverrides(usd_to_pkr=300),
            ),
        ))
        _, text = ws.execute(ListReportsQuery())
        assert "Shipment Audit" in text
        assert "Funding Comparison" in text


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestReportEdgeCases:

    def test_reports_and_scenarios_independent(self):
        """Report names and scenario names are in separate namespaces."""
        ws = _ws()
        # "fx_stress" already exists as scenario
        ws.execute(SaveReportQuery(
            name="fx_stress",
            source_query=ExplainShipmentQuery(shipment_id=1),
        ))
        assert ws.report_count() == 1
        assert ws.scenario_count() == 1  # pre-saved in _ws()

    def test_delete_then_get_returns_not_found(self):
        ws = _ws()
        ws.execute(SaveReportQuery(
            name="temp", source_query=ExplainShipmentQuery(shipment_id=1),
        ))
        ws.execute(DeleteReportQuery(name="temp"))
        result, text = ws.execute(GetReportQuery(name="temp"))
        assert result.found is False

    def test_multiple_reports_from_same_query_type(self):
        ws = _ws()
        ws.execute(SaveReportQuery(
            name="ship1", source_query=ExplainShipmentQuery(shipment_id=1),
        ))
        ws.execute(SaveReportQuery(
            name="ship2", source_query=ExplainShipmentQuery(shipment_id=2),
        ))
        assert ws.report_count() == 2
        rpt1 = ws.get_report("ship1").report
        rpt2 = ws.get_report("ship2").report
        assert rpt1.formatted_text != rpt2.formatted_text
