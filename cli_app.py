#!/usr/bin/env python3
"""Lightweight CLI interface for the SAFI meat-export analytical workspace.

A menu-driven terminal app that maps directly onto the existing
query/workspace layer.  Every action constructs a query dataclass,
passes it to workspace.execute(), and prints the formatted_text
that comes back.

Usage:
    python cli_app.py

No external dependencies required.
"""

from __future__ import annotations

import sys

from safi_engine.query_model import (
    CompareNamedScenariosQuery,
    CompareScenarioQuery,
    CreateScenarioFromTemplateQuery,
    DeleteReportQuery,
    ExplainLineItemQuery,
    ExplainShipmentQuery,
    FundingComparisonQuery,
    GetReportQuery,
    InspectScenarioTemplateQuery,
    ListReportsQuery,
    ListScenariosQuery,
    ListScenarioTemplatesQuery,
    MostAffectedShipmentsQuery,
    SaveReportQuery,
    ScenarioSummaryQuery,
    WorkingCapitalQuery,
)
from safi_engine.query_runner import QueryContext
from safi_engine.workspace import AnalyticalWorkspace

from validate_all_shipments import (
    load_cycle_details,
    load_outflow_config,
    load_strategy_config,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DIVIDER = "=" * 72
THIN_DIVIDER = "-" * 72


def _input(prompt: str) -> str:
    """Read input, handling EOF/Ctrl-C gracefully."""
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return ""


def _input_int(prompt: str, default: int | None = None) -> int | None:
    """Read an integer, returning default on empty/invalid input."""
    raw = _input(prompt)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        print(f"  Invalid number: {raw}")
        return default


def _pause() -> None:
    _input("\nPress Enter to continue...")


def _print_result(text: str) -> None:
    print()
    print(text)


# ---------------------------------------------------------------------------
# Workspace bootstrap
# ---------------------------------------------------------------------------


def build_workspace() -> AnalyticalWorkspace:
    """Load data and return a ready workspace."""
    print("Loading shipment data...")
    ctx = QueryContext(
        cycles=load_cycle_details(),
        config=load_strategy_config(),
        outflow_config=load_outflow_config(),
    )
    ws = AnalyticalWorkspace(ctx)
    print(f"  {len(ctx.cycles)} shipments loaded.")
    print(f"  {len(ws.templates)} scenario templates available.")
    print(f"  Baseline FX rate: {ctx.config.usd_to_pkr} PKR/USD")
    return ws


# ---------------------------------------------------------------------------
# Overview / home
# ---------------------------------------------------------------------------


def show_overview(ws: AnalyticalWorkspace) -> None:
    """Display a workspace overview using existing queries."""
    print()
    print(DIVIDER)
    print("  SAFI ANALYTICAL WORKSPACE — OVERVIEW")
    print(DIVIDER)
    print(f"  Total shipments:     {len(ws.ctx.cycles)}")
    print(f"  Baseline FX rate:    {ws.ctx.config.usd_to_pkr} PKR/USD")

    # Baseline net cashflow via ScenarioSummaryQuery (no overrides = baseline)
    r, _ = ws.execute(ScenarioSummaryQuery())
    summary = r.summary
    print(f"  Baseline net CF:     {summary.total_baseline_net:>16,.0f} PKR")

    # Portfolio funding profile
    r2, _ = ws.execute(WorkingCapitalQuery())
    port = r2.portfolio_summary
    if port:
        print(f"  Peak funding deficit:{port.peak_deficit:>16,.0f} PKR")
        print(f"  Peak surplus:        {port.peak_surplus:>16,.0f} PKR")
        print(f"  Negative cash days:  {port.negative_cash_days:>6d}")

    # Saved scenarios
    scenarios = ws.list_scenarios()
    if scenarios:
        print(f"  Saved scenarios ({len(scenarios)}):")
        for sc in scenarios:
            desc = f" — {sc.description}" if sc.description else ""
            print(f"    - {sc.name}{desc}")
    else:
        print("  Saved scenarios:     none")

    # Saved reports
    reports = ws.list_reports()
    if reports:
        print(f"  Saved reports ({len(reports)}):")
        for rpt in reports:
            print(f"    - {rpt.name} [{rpt.report_type.label}]")
    else:
        print("  Saved reports:       none")
    print(DIVIDER)


# ---------------------------------------------------------------------------
# Menu actions — Scenarios
# ---------------------------------------------------------------------------


def action_list_templates(ws: AnalyticalWorkspace) -> None:
    _, text = ws.execute(ListScenarioTemplatesQuery())
    _print_result(text)


def action_inspect_template(ws: AnalyticalWorkspace) -> None:
    name = _input("  Template name: ")
    if not name:
        return
    _, text = ws.execute(InspectScenarioTemplateQuery(name=name))
    _print_result(text)


def action_create_from_template(ws: AnalyticalWorkspace) -> None:
    template = _input("  Template name: ")
    if not template:
        return
    scenario = _input("  New scenario name: ")
    if not scenario:
        return
    desc = _input("  Description (optional): ")
    _, text = ws.execute(CreateScenarioFromTemplateQuery(
        template_name=template,
        scenario_name=scenario,
        description=desc,
    ))
    _print_result(text)


def action_list_scenarios(ws: AnalyticalWorkspace) -> None:
    _, text = ws.execute(ListScenariosQuery())
    _print_result(text)


def action_compare_scenarios(ws: AnalyticalWorkspace) -> None:
    a = _input("  Scenario A name (or 'baseline'): ")
    if not a:
        return
    b = _input("  Scenario B name: ")
    if not b:
        return
    mode = _input("  Mode — cashflow or funding [cashflow]: ") or "cashflow"
    ship_id = None
    if mode == "funding":
        ship_id = _input_int("  Shipment ID (blank=portfolio): ")
    _, text = ws.execute(CompareNamedScenariosQuery(
        scenario_a=a, scenario_b=b, mode=mode, shipment_id=ship_id,
    ))
    _print_result(text)


def action_scenario_summary(ws: AnalyticalWorkspace) -> None:
    name = _input("  Scenario name: ")
    if not name:
        return
    top_n = _input_int("  Top N shipments [5]: ", 5)
    _, text = ws.execute(ScenarioSummaryQuery(
        scenario_name=name, top_n=top_n or 5,
    ))
    _print_result(text)


# ---------------------------------------------------------------------------
# Menu actions — Analysis
# ---------------------------------------------------------------------------


def action_explain_shipment(ws: AnalyticalWorkspace) -> None:
    ship_id = _input_int("  Shipment ID [1]: ", 1)
    if ship_id is None:
        return
    scenario = _input("  Scenario name (blank=baseline): ") or None
    _, text = ws.execute(ExplainShipmentQuery(
        shipment_id=ship_id, scenario_name=scenario,
    ))
    _print_result(text)


def action_explain_line_item(ws: AnalyticalWorkspace) -> None:
    ship_id = _input_int("  Shipment ID [1]: ", 1)
    if ship_id is None:
        return
    cost = _input("  Cost type (e.g. Partha, Freight, SALE): ")
    if not cost:
        return
    scenario = _input("  Scenario name (blank=baseline): ") or None
    _, text = ws.execute(ExplainLineItemQuery(
        shipment_id=ship_id, cost_type=cost, scenario_name=scenario,
    ))
    _print_result(text)


def action_working_capital(ws: AnalyticalWorkspace) -> None:
    ship_id = _input_int("  Shipment ID (blank=portfolio): ")
    scenario = _input("  Scenario name (blank=baseline): ") or None
    _, text = ws.execute(WorkingCapitalQuery(
        shipment_id=ship_id, scenario_name=scenario,
    ))
    _print_result(text)


def action_funding_comparison(ws: AnalyticalWorkspace) -> None:
    scenario = _input("  Scenario name: ")
    if not scenario:
        return
    ship_id = _input_int("  Shipment ID (blank=portfolio): ")
    _, text = ws.execute(FundingComparisonQuery(
        scenario_name=scenario, shipment_id=ship_id,
    ))
    _print_result(text)


def action_most_affected(ws: AnalyticalWorkspace) -> None:
    scenario = _input("  Scenario name: ")
    if not scenario:
        return
    top_n = _input_int("  Top N [5]: ", 5)
    _, text = ws.execute(MostAffectedShipmentsQuery(
        scenario_name=scenario, top_n=top_n or 5,
    ))
    _print_result(text)


# ---------------------------------------------------------------------------
# Menu actions — Reports
# ---------------------------------------------------------------------------


def action_save_report(ws: AnalyticalWorkspace) -> None:
    print("  Save a report by running a query and naming the result.")
    print("  Query types: explain_shipment, scenario_summary,")
    print("    funding_comparison, working_capital, most_affected")
    qtype = _input("  Query type: ")
    if not qtype:
        return

    source_query = None
    if qtype == "explain_shipment":
        sid = _input_int("  Shipment ID [1]: ", 1)
        scn = _input("  Scenario name (blank=baseline): ") or None
        source_query = ExplainShipmentQuery(shipment_id=sid or 1, scenario_name=scn)
    elif qtype == "scenario_summary":
        scn = _input("  Scenario name: ")
        source_query = ScenarioSummaryQuery(scenario_name=scn or None)
    elif qtype == "funding_comparison":
        scn = _input("  Scenario name: ")
        source_query = FundingComparisonQuery(scenario_name=scn or None)
    elif qtype == "working_capital":
        sid = _input_int("  Shipment ID (blank=portfolio): ")
        scn = _input("  Scenario name (blank=baseline): ") or None
        source_query = WorkingCapitalQuery(shipment_id=sid, scenario_name=scn)
    elif qtype == "most_affected":
        scn = _input("  Scenario name: ")
        top_n = _input_int("  Top N [5]: ", 5)
        source_query = MostAffectedShipmentsQuery(
            scenario_name=scn or None, top_n=top_n or 5,
        )
    else:
        print(f"  Unknown query type: {qtype}")
        return

    name = _input("  Report name: ")
    if not name:
        return
    desc = _input("  Description (optional): ")
    _, text = ws.execute(SaveReportQuery(
        name=name, source_query=source_query, description=desc,
    ))
    _print_result(text)


def action_list_reports(ws: AnalyticalWorkspace) -> None:
    _, text = ws.execute(ListReportsQuery())
    _print_result(text)


def action_get_report(ws: AnalyticalWorkspace) -> None:
    name = _input("  Report name: ")
    if not name:
        return
    _, text = ws.execute(GetReportQuery(name=name))
    _print_result(text)


def action_delete_report(ws: AnalyticalWorkspace) -> None:
    name = _input("  Report name: ")
    if not name:
        return
    _, text = ws.execute(DeleteReportQuery(name=name))
    _print_result(text)


# ---------------------------------------------------------------------------
# Menu structure
# ---------------------------------------------------------------------------

MAIN_MENU = """
{divider}
  MAIN MENU
{divider}
  [0] Overview / Home
  --- Scenarios ---
  [1] List templates
  [2] Inspect template
  [3] Create scenario from template
  [4] List saved scenarios
  [5] Compare two scenarios
  [6] Scenario impact summary
  --- Analysis ---
  [7] Explain shipment
  [8] Explain line item
  [9] Working capital profile
  [10] Funding comparison
  [11] Most affected shipments
  --- Reports ---
  [12] Save a report
  [13] List reports
  [14] Retrieve a report
  [15] Delete a report
  ---
  [q] Quit
{divider}
""".format(divider=THIN_DIVIDER)

ACTIONS = {
    "0": show_overview,
    "1": action_list_templates,
    "2": action_inspect_template,
    "3": action_create_from_template,
    "4": action_list_scenarios,
    "5": action_compare_scenarios,
    "6": action_scenario_summary,
    "7": action_explain_shipment,
    "8": action_explain_line_item,
    "9": action_working_capital,
    "10": action_funding_comparison,
    "11": action_most_affected,
    "12": action_save_report,
    "13": action_list_reports,
    "14": action_get_report,
    "15": action_delete_report,
}


def main_loop(ws: AnalyticalWorkspace) -> None:
    """Run the interactive menu loop."""
    show_overview(ws)

    while True:
        print(MAIN_MENU)
        choice = _input("  Select [0-15, q]: ")
        if choice in ("q", "quit", "exit"):
            print("Goodbye.")
            break
        if choice in ACTIONS:
            try:
                ACTIONS[choice](ws)
            except (KeyError, ValueError) as e:
                print(f"\n  Error: {e}")
            _pause()
        elif choice:
            print(f"  Unknown option: {choice}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    print(DIVIDER)
    print("  SAFI Meat-Export Analytical Workspace CLI")
    print(DIVIDER)
    ws = build_workspace()
    main_loop(ws)


if __name__ == "__main__":
    main()
