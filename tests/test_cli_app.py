"""Smoke tests for cli_app — verify the interface layer constructs correct
queries and delegates to the workspace without errors.

Tests cover:
  - overview display
  - individual action functions
  - guided workflows (stress test, deep dive, funding stress)
  - session state memory
  - numbered choosers
  - menu structure completeness
"""

from __future__ import annotations

import unittest
from io import StringIO
from unittest.mock import patch

from safi_engine.query_runner import QueryContext
from safi_engine.workspace import AnalyticalWorkspace

from validate_all_shipments import (
    load_cycle_details,
    load_outflow_config,
    load_strategy_config,
)

import cli_app


def _make_workspace() -> AnalyticalWorkspace:
    ctx = QueryContext(
        cycles=load_cycle_details(),
        config=load_strategy_config(),
        outflow_config=load_outflow_config(),
    )
    return AnalyticalWorkspace(ctx)


def _run_action(action_fn, ws, inputs: list[str]) -> str:
    """Run an action function with simulated stdin, capture stdout."""
    output = StringIO()
    with patch("builtins.input", side_effect=inputs):
        with patch("sys.stdout", output):
            action_fn(ws)
    return output.getvalue()


def _reset_state() -> None:
    """Reset session state between tests."""
    cli_app._state = cli_app.SessionState()


class TestOverview(unittest.TestCase):
    def test_overview_runs(self):
        ws = _make_workspace()
        output = StringIO()
        with patch("sys.stdout", output):
            cli_app.show_overview(ws)
        text = output.getvalue()
        self.assertIn("BASELINE METRICS", text)
        self.assertIn("Net cashflow", text)
        self.assertIn("Peak funding deficit", text)

    def test_overview_shows_quick_start(self):
        ws = _make_workspace()
        output = StringIO()
        with patch("sys.stdout", output):
            cli_app.show_overview(ws)
        text = output.getvalue()
        self.assertIn("QUICK START", text)

    def test_overview_shows_scenarios_after_creation(self):
        ws = _make_workspace()
        from safi_engine.query_model import CreateScenarioFromTemplateQuery
        ws.execute(CreateScenarioFromTemplateQuery(
            template_name="freight_stress", scenario_name="fs",
        ))
        output = StringIO()
        with patch("sys.stdout", output):
            cli_app.show_overview(ws)
        text = output.getvalue()
        self.assertIn("fs", text)
        self.assertIn("Scenarios (1)", text)


class TestScenarioActions(unittest.TestCase):
    def test_list_templates(self):
        ws = _make_workspace()
        text = _run_action(cli_app.action_list_templates, ws, [])
        self.assertIn("Available scenario templates", text)

    def test_inspect_template_by_number(self):
        ws = _make_workspace()
        # Select first template by number
        text = _run_action(cli_app.action_inspect_template, ws, ["1"])
        self.assertIn("TEMPLATE:", text)

    def test_inspect_template_by_name(self):
        ws = _make_workspace()
        text = _run_action(cli_app.action_inspect_template, ws, ["total_downside"])
        self.assertIn("TEMPLATE: total_downside", text)

    def test_create_from_template_with_defaults(self):
        ws = _make_workspace()
        # Choose template 5 (freight_stress), accept default name, no description
        text = _run_action(
            cli_app.action_create_from_template, ws,
            ["freight_stress", "", ""],
        )
        self.assertIn("Created scenario", text)
        # Default name derived from template name
        self.assertIsNotNone(ws.get_scenario("freight"))

    def test_create_from_template_custom_name(self):
        ws = _make_workspace()
        text = _run_action(
            cli_app.action_create_from_template, ws,
            ["freight_stress", "my_freight", "Custom freight test"],
        )
        self.assertIn("Created scenario", text)
        self.assertIsNotNone(ws.get_scenario("my_freight"))

    def test_list_scenarios_empty(self):
        ws = _make_workspace()
        text = _run_action(cli_app.action_list_scenarios, ws, [])
        self.assertIn("No saved scenarios", text)

    def test_list_scenarios_populated(self):
        ws = _make_workspace()
        _run_action(
            cli_app.action_create_from_template, ws,
            ["total_upside", "upside", ""],
        )
        text = _run_action(cli_app.action_list_scenarios, ws, [])
        self.assertIn("upside", text)

    def test_scenario_summary(self):
        ws = _make_workspace()
        _run_action(
            cli_app.action_create_from_template, ws,
            ["freight_stress", "fs", ""],
        )
        # Choose scenario by number (baseline=1, fs=2), top_n=3
        text = _run_action(cli_app.action_scenario_summary, ws, ["1", "3"])
        self.assertIn("SCENARIO COMPARISON SUMMARY", text)


class TestAnalysisActions(unittest.TestCase):
    def test_explain_shipment(self):
        _reset_state()
        ws = _make_workspace()
        text = _run_action(cli_app.action_explain_shipment, ws, ["1", ""])
        self.assertIn("SHIPMENT EXPLANATION", text)

    def test_explain_shipment_remembers_last(self):
        _reset_state()
        ws = _make_workspace()
        # First call sets shipment 5
        _run_action(cli_app.action_explain_shipment, ws, ["5", ""])
        self.assertEqual(cli_app._state.last_shipment, 5)

    def test_explain_line_item(self):
        _reset_state()
        ws = _make_workspace()
        text = _run_action(cli_app.action_explain_line_item, ws, ["1", "Partha", ""])
        self.assertIn("Partha", text)

    def test_explain_line_item_shows_cost_types(self):
        _reset_state()
        ws = _make_workspace()
        text = _run_action(cli_app.action_explain_line_item, ws, ["1", "Freight", ""])
        self.assertIn("Cost types:", text)

    def test_working_capital_portfolio(self):
        ws = _make_workspace()
        text = _run_action(cli_app.action_working_capital, ws, ["", ""])
        self.assertIn("PORTFOLIO", text)

    def test_working_capital_single(self):
        ws = _make_workspace()
        text = _run_action(cli_app.action_working_capital, ws, ["1", ""])
        self.assertTrue(len(text) > 0)

    def test_most_affected(self):
        ws = _make_workspace()
        _run_action(
            cli_app.action_create_from_template, ws,
            ["total_downside", "down", ""],
        )
        # Choose scenario by number (only non-baseline = 1), top_n=3
        text = _run_action(cli_app.action_most_affected, ws, ["1", "3"])
        self.assertIn("MOST AFFECTED", text)


class TestReportActions(unittest.TestCase):
    def test_save_and_list_and_get_report(self):
        _reset_state()
        ws = _make_workspace()
        # Save: type=1 (explain_shipment), shipment=1, report name, desc
        # _ask_scenario_optional returns None immediately (no scenarios)
        text = _run_action(
            cli_app.action_save_report, ws,
            ["1", "1", "ship1_audit", "Test audit"],
        )
        self.assertIn("Saved report", text)
        # List
        text = _run_action(cli_app.action_list_reports, ws, [])
        self.assertIn("ship1_audit", text)
        # Get (choose by number)
        text = _run_action(cli_app.action_get_report, ws, ["1"])
        self.assertIn("REPORT: ship1_audit", text)

    def test_delete_report_with_confirmation(self):
        _reset_state()
        ws = _make_workspace()
        _run_action(
            cli_app.action_save_report, ws,
            ["1", "1", "tmp_report", ""],
        )
        # Delete: choose by number, confirm
        text = _run_action(cli_app.action_delete_report, ws, ["1", "y"])
        self.assertIn("Deleted report", text)

    def test_delete_report_cancelled(self):
        _reset_state()
        ws = _make_workspace()
        _run_action(
            cli_app.action_save_report, ws,
            ["1", "1", "keep_me", ""],
        )
        # Delete: choose by number, cancel
        text = _run_action(cli_app.action_delete_report, ws, ["1", "n"])
        self.assertIn("Cancelled", text)
        self.assertEqual(ws.report_count(), 1)


class TestCompareScenarios(unittest.TestCase):
    def test_compare_baseline_vs_named(self):
        ws = _make_workspace()
        _run_action(
            cli_app.action_create_from_template, ws,
            ["pricing_pressure", "pp", ""],
        )
        # baseline=1, pp=2, cashflow mode, decline save
        text = _run_action(
            cli_app.action_compare_scenarios, ws,
            ["1", "2", "c", "n"],
        )
        self.assertIn("Comparing", text)
        self.assertIn("Net Cashflow", text)

    def test_compare_with_save(self):
        ws = _make_workspace()
        _run_action(
            cli_app.action_create_from_template, ws,
            ["pricing_pressure", "pp", ""],
        )
        # baseline=1, pp=2, cashflow, save=y, accept default name
        text = _run_action(
            cli_app.action_compare_scenarios, ws,
            ["1", "2", "c", "y", ""],
        )
        self.assertEqual(ws.report_count(), 1)


class TestGuidedWorkflows(unittest.TestCase):
    def test_workflow_scenario_stress(self):
        ws = _make_workspace()
        # Choose template "freight_stress", accept default name, decline save
        text = _run_action(
            cli_app.workflow_scenario_stress, ws,
            ["freight_stress", "", "n"],
        )
        self.assertIn("GUIDED WORKFLOW", text)
        self.assertIn("Comparing", text)
        self.assertIn("Net Cashflow", text)
        self.assertIsNotNone(ws.get_scenario("freight"))

    def test_workflow_scenario_stress_with_save(self):
        ws = _make_workspace()
        # Choose template, accept default name, save with default report name
        text = _run_action(
            cli_app.workflow_scenario_stress, ws,
            ["freight_stress", "", "y", ""],
        )
        self.assertEqual(ws.report_count(), 1)

    def test_workflow_shipment_deep_dive(self):
        _reset_state()
        ws = _make_workspace()
        # shipment 1, no scenario, skip line item drill, decline save
        text = _run_action(
            cli_app.workflow_shipment_deep_dive, ws,
            ["1", "", "", "n"],
        )
        self.assertIn("GUIDED WORKFLOW", text)
        self.assertIn("SHIPMENT EXPLANATION", text)

    def test_workflow_shipment_deep_dive_with_drill(self):
        _reset_state()
        ws = _make_workspace()
        # shipment 1, no scenario (no scenarios exist, so not asked),
        # drill into Freight, no more drilling, save=y, accept default name
        text = _run_action(
            cli_app.workflow_shipment_deep_dive, ws,
            ["1", "Freight", "n", "y", ""],
        )
        self.assertIn("Freight", text)
        self.assertEqual(ws.report_count(), 1)

    def test_workflow_funding_stress(self):
        ws = _make_workspace()
        # No existing scenarios, choose template, accept default name, decline save
        text = _run_action(
            cli_app.workflow_funding_stress, ws,
            ["total_downside", "", "n"],
        )
        self.assertIn("GUIDED WORKFLOW", text)
        # Should show funding comparison output
        self.assertTrue(len(text) > 200)

    def test_workflow_funding_stress_with_existing(self):
        ws = _make_workspace()
        _run_action(
            cli_app.action_create_from_template, ws,
            ["total_downside", "down", ""],
        )
        # Use existing scenario (e), choose #1, decline save
        text = _run_action(
            cli_app.workflow_funding_stress, ws,
            ["e", "1", "n"],
        )
        self.assertIn("GUIDED WORKFLOW", text)


class TestSessionState(unittest.TestCase):
    def test_shipment_remembered(self):
        _reset_state()
        ws = _make_workspace()
        _run_action(cli_app.action_explain_shipment, ws, ["42", ""])
        self.assertEqual(cli_app._state.last_shipment, 42)

    def test_scenario_remembered(self):
        _reset_state()
        ws = _make_workspace()
        _run_action(
            cli_app.action_create_from_template, ws,
            ["freight_stress", "my_sc", ""],
        )
        self.assertEqual(cli_app._state.last_scenario, "my_sc")

    def test_report_remembered(self):
        _reset_state()
        ws = _make_workspace()
        # type=1 (explain_shipment), shipment=1, name, desc
        _run_action(
            cli_app.action_save_report, ws,
            ["1", "1", "my_rpt", ""],
        )
        self.assertEqual(cli_app._state.last_report, "my_rpt")


class TestMenuMapping(unittest.TestCase):
    """Verify menu structure completeness."""

    def test_all_actions_are_callable(self):
        for key, fn in cli_app.ACTIONS.items():
            self.assertTrue(callable(fn), f"Action '{key}' is not callable")

    def test_essential_actions_present(self):
        essential = ["h", "t", "i", "n", "ls", "cs", "ss",
                      "x", "l", "w", "fc", "ma",
                      "sr", "lr", "gr", "dr",
                      "s", "d", "f"]
        for key in essential:
            self.assertIn(key, cli_app.ACTIONS, f"Action '{key}' missing")

    def test_menu_text_mentions_all_keys(self):
        menu = cli_app._format_menu()
        for key in cli_app.ACTIONS:
            self.assertIn(f"[{key}]", menu, f"Key [{key}] missing from menu text")


if __name__ == "__main__":
    unittest.main()
