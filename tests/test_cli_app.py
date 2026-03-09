"""Smoke tests for cli_app — verify the interface layer constructs correct
queries and delegates to the workspace without errors.

These tests exercise the action functions with simulated input, confirming
that the CLI maps cleanly onto the workspace/query layer.
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
    input_stream = StringIO("\n".join(inputs) + "\n")
    output = StringIO()
    with patch("builtins.input", side_effect=inputs):
        with patch("sys.stdout", output):
            action_fn(ws)
    return output.getvalue()


class TestOverview(unittest.TestCase):
    def test_overview_runs(self):
        ws = _make_workspace()
        output = StringIO()
        with patch("sys.stdout", output):
            cli_app.show_overview(ws)
        text = output.getvalue()
        self.assertIn("Total shipments", text)
        self.assertIn("Baseline net CF", text)
        self.assertIn("Peak funding deficit", text)


class TestScenarioActions(unittest.TestCase):
    def test_list_templates(self):
        ws = _make_workspace()
        text = _run_action(cli_app.action_list_templates, ws, [])
        self.assertIn("Available scenario templates", text)

    def test_inspect_template(self):
        ws = _make_workspace()
        text = _run_action(cli_app.action_inspect_template, ws, ["total_downside"])
        self.assertIn("TEMPLATE: total_downside", text)

    def test_create_from_template(self):
        ws = _make_workspace()
        text = _run_action(
            cli_app.action_create_from_template, ws,
            ["freight_stress", "my_freight", "Freight test"],
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
        text = _run_action(cli_app.action_scenario_summary, ws, ["fs", "3"])
        self.assertIn("SCENARIO COMPARISON SUMMARY", text)


class TestAnalysisActions(unittest.TestCase):
    def test_explain_shipment(self):
        ws = _make_workspace()
        text = _run_action(cli_app.action_explain_shipment, ws, ["1", ""])
        self.assertIn("SHIPMENT EXPLANATION", text)

    def test_explain_line_item(self):
        ws = _make_workspace()
        text = _run_action(cli_app.action_explain_line_item, ws, ["1", "Partha", ""])
        self.assertIn("Partha", text)

    def test_working_capital_portfolio(self):
        ws = _make_workspace()
        text = _run_action(cli_app.action_working_capital, ws, ["", ""])
        self.assertIn("PORTFOLIO", text)

    def test_working_capital_single(self):
        ws = _make_workspace()
        text = _run_action(cli_app.action_working_capital, ws, ["1", ""])
        # Should contain shipment-level funding profile info
        self.assertTrue(len(text) > 0)

    def test_most_affected(self):
        ws = _make_workspace()
        _run_action(
            cli_app.action_create_from_template, ws,
            ["total_downside", "down", ""],
        )
        text = _run_action(cli_app.action_most_affected, ws, ["down", "3"])
        self.assertIn("MOST AFFECTED", text)


class TestReportActions(unittest.TestCase):
    def test_save_and_list_and_get_report(self):
        ws = _make_workspace()
        # Save
        text = _run_action(
            cli_app.action_save_report, ws,
            ["explain_shipment", "1", "", "ship1_audit", "Test audit"],
        )
        self.assertIn("Saved report", text)
        # List
        text = _run_action(cli_app.action_list_reports, ws, [])
        self.assertIn("ship1_audit", text)
        # Get
        text = _run_action(cli_app.action_get_report, ws, ["ship1_audit"])
        self.assertIn("REPORT: ship1_audit", text)

    def test_delete_report(self):
        ws = _make_workspace()
        _run_action(
            cli_app.action_save_report, ws,
            ["explain_shipment", "1", "", "tmp_report", ""],
        )
        text = _run_action(cli_app.action_delete_report, ws, ["tmp_report"])
        self.assertIn("Deleted report", text)


class TestMenuMapping(unittest.TestCase):
    """Verify every menu option maps to a valid action function."""

    def test_all_actions_are_callable(self):
        for key, fn in cli_app.ACTIONS.items():
            self.assertTrue(callable(fn), f"Action {key} is not callable")

    def test_actions_cover_all_menu_items(self):
        # 0-15 should all be in ACTIONS
        for i in range(16):
            self.assertIn(str(i), cli_app.ACTIONS, f"Menu item {i} missing from ACTIONS")


class TestCompareScenarios(unittest.TestCase):
    def test_compare_baseline_vs_named(self):
        ws = _make_workspace()
        _run_action(
            cli_app.action_create_from_template, ws,
            ["pricing_pressure", "pp", ""],
        )
        text = _run_action(
            cli_app.action_compare_scenarios, ws,
            ["baseline", "pp", "cashflow"],
        )
        self.assertIn("Comparing", text)
        self.assertIn("Net Cashflow", text)


if __name__ == "__main__":
    unittest.main()
