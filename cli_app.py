#!/usr/bin/env python3
"""Lightweight CLI interface for the SAFI meat-export analytical workspace.

A menu-driven terminal app that maps directly onto the existing
query/workspace layer.  Every action constructs a query dataclass,
passes it to workspace.execute(), and prints the formatted_text
that comes back.

Usability features:
  - Session memory: last-used shipment and scenario are remembered
  - Numbered choosers: select scenarios, templates, and reports by number
  - Guided workflows: multi-step flows for common analyst tasks
  - Contextual prompts: defaults shown in brackets, available options listed

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
# Constants
# ---------------------------------------------------------------------------

DIVIDER = "=" * 72
THIN = "-" * 72

COST_TYPES = [
    "Partha", "SALE", "Slaughter", "Animal_Trimming", "Freight",
    "Clearance", "Stickers_Wrap", "AWB", "AQD", "PSW", "Halal",
    "Dry_Ice_Box", "TPT_Slaughter", "Data_Logger", "Chilling",
    "Polysheet", "Admin", "Bank",
]


# ---------------------------------------------------------------------------
# Session state — remembers last-used values across actions
# ---------------------------------------------------------------------------


class SessionState:
    """Lightweight memory for reducing repetitive input."""

    def __init__(self) -> None:
        self.last_shipment: int = 1
        self.last_scenario: str | None = None
        self.last_report: str | None = None


# Module-level state, set during build_workspace
_state = SessionState()


def _set_shipment(sid: int) -> None:
    _state.last_shipment = sid


def _set_scenario(name: str) -> None:
    _state.last_scenario = name


def _set_report(name: str) -> None:
    _state.last_report = name


# ---------------------------------------------------------------------------
# Input helpers
# ---------------------------------------------------------------------------


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
        print(f"  Invalid number: '{raw}'")
        return default


def _pause() -> None:
    _input("\nPress Enter to continue...")


def _print_result(text: str) -> None:
    print()
    print(text)


# ---------------------------------------------------------------------------
# Choosers — pick from numbered lists instead of typing names
# ---------------------------------------------------------------------------


def _choose_scenario(ws: AnalyticalWorkspace, prompt_label: str = "scenario",
                     allow_baseline: bool = True) -> str | None:
    """Show numbered list of scenarios, return chosen name or None."""
    scenarios = ws.list_scenarios()
    options: list[tuple[str, str]] = []
    if allow_baseline:
        options.append(("baseline", "baseline (no overrides)"))
    for sc in scenarios:
        desc = f" — {sc.description}" if sc.description else ""
        options.append((sc.name, f"{sc.name}{desc}"))

    if not options:
        print("  No scenarios available. Create one first.")
        return None

    if len(options) == 1 and allow_baseline:
        # Only baseline exists
        default_hint = " [baseline]"
    elif _state.last_scenario and any(n == _state.last_scenario for n, _ in options):
        default_hint = f" [{_state.last_scenario}]"
    else:
        default_hint = ""

    print(f"  Available {prompt_label}s:")
    for i, (name, desc) in enumerate(options):
        print(f"    [{i + 1}] {desc}")
    raw = _input(f"  Select {prompt_label} (# or name){default_hint}: ")
    if not raw:
        # Use default
        if default_hint:
            chosen = default_hint.strip(" []")
            _set_scenario(chosen)
            return chosen
        return None

    # Try as number
    try:
        idx = int(raw) - 1
        if 0 <= idx < len(options):
            chosen = options[idx][0]
            _set_scenario(chosen)
            return chosen
    except ValueError:
        pass

    # Try as name
    if raw == "baseline" and allow_baseline:
        return "baseline"
    if any(n == raw for n, _ in options):
        _set_scenario(raw)
        return raw

    print(f"  Not found: '{raw}'")
    return None


def _choose_template(ws: AnalyticalWorkspace) -> str | None:
    """Show numbered list of templates, return chosen name or None."""
    templates = ws.templates.list_templates()
    if not templates:
        print("  No templates available.")
        return None
    print("  Available templates:")
    for i, t in enumerate(templates):
        print(f"    [{i + 1}] {t.name}: {t.description}")
    raw = _input("  Select template (# or name): ")
    if not raw:
        return None
    try:
        idx = int(raw) - 1
        if 0 <= idx < len(templates):
            return templates[idx].name
    except ValueError:
        pass
    if any(t.name == raw for t in templates):
        return raw
    print(f"  Not found: '{raw}'")
    return None


def _choose_report(ws: AnalyticalWorkspace) -> str | None:
    """Show numbered list of reports, return chosen name or None."""
    reports = ws.list_reports()
    if not reports:
        print("  No saved reports.")
        return None
    default_hint = ""
    if _state.last_report and any(r.name == _state.last_report for r in reports):
        default_hint = f" [{_state.last_report}]"
    print("  Saved reports:")
    for i, rpt in enumerate(reports):
        desc = f" — {rpt.description}" if rpt.description else ""
        print(f"    [{i + 1}] {rpt.name} [{rpt.report_type.label}]{desc}")
    raw = _input(f"  Select report (# or name){default_hint}: ")
    if not raw:
        if default_hint:
            return _state.last_report
        return None
    try:
        idx = int(raw) - 1
        if 0 <= idx < len(reports):
            chosen = reports[idx].name
            _set_report(chosen)
            return chosen
    except ValueError:
        pass
    if any(r.name == raw for r in reports):
        _set_report(raw)
        return raw
    print(f"  Not found: '{raw}'")
    return None


def _ask_shipment(default: int | None = None) -> int | None:
    """Prompt for shipment ID with session default."""
    d = default if default is not None else _state.last_shipment
    sid = _input_int(f"  Shipment ID [{d}]: ", d)
    if sid is not None:
        _set_shipment(sid)
    return sid


def _ask_scenario_optional(ws: AnalyticalWorkspace, label: str = "Under scenario") -> str | None:
    """Prompt for optional scenario name, showing available options."""
    scenarios = ws.list_scenarios()
    if not scenarios:
        return None
    names = [sc.name for sc in scenarios]
    hint = ", ".join(names[:5])
    if len(names) > 5:
        hint += ", ..."
    raw = _input(f"  {label} (blank=baseline, or: {hint}): ")
    if not raw:
        return None
    if raw in names or raw == "baseline":
        _set_scenario(raw)
        return raw
    print(f"  Scenario '{raw}' not found, using baseline.")
    return None


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
    print(f"  {len(ctx.cycles)} shipments loaded  |  "
          f"{len(ws.templates)} templates  |  "
          f"FX {ctx.config.usd_to_pkr} PKR/USD")
    return ws


# ---------------------------------------------------------------------------
# Overview / home
# ---------------------------------------------------------------------------


def show_overview(ws: AnalyticalWorkspace) -> None:
    """Display a workspace overview using existing queries."""
    print()
    print(DIVIDER)
    print("  SAFI ANALYTICAL WORKSPACE")
    print(DIVIDER)

    # Baseline metrics
    r, _ = ws.execute(ScenarioSummaryQuery())
    summary = r.summary
    r2, _ = ws.execute(WorkingCapitalQuery())
    port = r2.portfolio_summary

    print()
    print("  BASELINE METRICS")
    print(f"  {'Shipments:':22s} {len(ws.ctx.cycles)}")
    print(f"  {'FX rate:':22s} {ws.ctx.config.usd_to_pkr} PKR/USD")
    print(f"  {'Net cashflow:':22s} {summary.total_baseline_net:>14,.0f} PKR")
    if port:
        print(f"  {'Peak funding deficit:':22s} {port.peak_deficit:>14,.0f} PKR")
        print(f"  {'Peak surplus:':22s} {port.peak_surplus:>14,.0f} PKR")
        print(f"  {'Negative cash days:':22s} {port.negative_cash_days:>4d}")

    # Workspace state
    scenarios = ws.list_scenarios()
    reports = ws.list_reports()
    print()
    print("  WORKSPACE STATE")
    if scenarios:
        print(f"  Scenarios ({len(scenarios)}):")
        for sc in scenarios:
            desc = f" — {sc.description}" if sc.description else ""
            print(f"    {sc.name}{desc}")
    else:
        print("  Scenarios:  none (use [s] to create from a template)")
    if reports:
        print(f"  Reports ({len(reports)}):")
        for rpt in reports:
            print(f"    {rpt.name} [{rpt.report_type.label}]")
    else:
        print("  Reports:    none")

    # Quick start hints
    print()
    print("  QUICK START")
    if not scenarios:
        print("    [s] Create scenario from template (recommended first step)")
    else:
        names = ", ".join(sc.name for sc in scenarios[:3])
        print(f"    [c] Compare baseline vs {names}")
    print("    [d] Shipment deep-dive (explain + line items)")
    print("    [f] Funding stress test (create downside + compare funding)")
    print(DIVIDER)


# ---------------------------------------------------------------------------
# Menu actions — Scenarios
# ---------------------------------------------------------------------------


def action_list_templates(ws: AnalyticalWorkspace) -> None:
    _, text = ws.execute(ListScenarioTemplatesQuery())
    _print_result(text)


def action_inspect_template(ws: AnalyticalWorkspace) -> None:
    name = _choose_template(ws)
    if not name:
        return
    _, text = ws.execute(InspectScenarioTemplateQuery(name=name))
    _print_result(text)


def action_create_from_template(ws: AnalyticalWorkspace) -> None:
    name = _choose_template(ws)
    if not name:
        return
    default_scenario = name.replace("_stress", "").replace("total_", "")
    scenario = _input(f"  Name for new scenario [{default_scenario}]: ") or default_scenario
    desc = _input("  Description (optional): ")
    _, text = ws.execute(CreateScenarioFromTemplateQuery(
        template_name=name,
        scenario_name=scenario,
        description=desc,
    ))
    _set_scenario(scenario)
    _print_result(text)


def action_list_scenarios(ws: AnalyticalWorkspace) -> None:
    _, text = ws.execute(ListScenariosQuery())
    _print_result(text)


def action_compare_scenarios(ws: AnalyticalWorkspace) -> None:
    print("  Select two scenarios to compare.")
    a = _choose_scenario(ws, "scenario A")
    if a is None:
        return
    b = _choose_scenario(ws, "scenario B")
    if b is None:
        return
    mode = _input("  Mode — [c]ashflow or [f]unding [cashflow]: ") or "cashflow"
    if mode in ("f", "funding"):
        mode = "funding"
    else:
        mode = "cashflow"
    ship_id = None
    if mode == "funding":
        ship_id = _input_int("  Shipment ID (blank=portfolio): ")
    _, text = ws.execute(CompareNamedScenariosQuery(
        scenario_a=a, scenario_b=b, mode=mode, shipment_id=ship_id,
    ))
    _print_result(text)

    # Offer to save as report
    save = _input("  Save this comparison as a report? [y/N]: ")
    if save.lower() in ("y", "yes"):
        default_name = f"{a}_vs_{b}"
        rname = _input(f"  Report name [{default_name}]: ") or default_name
        ws.execute(SaveReportQuery(
            name=rname,
            source_query=CompareNamedScenariosQuery(
                scenario_a=a, scenario_b=b, mode=mode, shipment_id=ship_id,
            ),
            description=f"Comparison: {a} vs {b} ({mode})",
        ))
        _set_report(rname)
        print(f"  Saved report '{rname}'.")


def action_scenario_summary(ws: AnalyticalWorkspace) -> None:
    name = _choose_scenario(ws, "scenario", allow_baseline=False)
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
    ship_id = _ask_shipment()
    if ship_id is None:
        return
    scenario = _ask_scenario_optional(ws)
    _, text = ws.execute(ExplainShipmentQuery(
        shipment_id=ship_id, scenario_name=scenario,
    ))
    _print_result(text)


def action_explain_line_item(ws: AnalyticalWorkspace) -> None:
    ship_id = _ask_shipment()
    if ship_id is None:
        return
    # Show available cost types
    print(f"  Cost types: {', '.join(COST_TYPES)}")
    cost = _input("  Cost type: ")
    if not cost:
        return
    scenario = _ask_scenario_optional(ws)
    _, text = ws.execute(ExplainLineItemQuery(
        shipment_id=ship_id, cost_type=cost, scenario_name=scenario,
    ))
    _print_result(text)


def action_working_capital(ws: AnalyticalWorkspace) -> None:
    scope = _input(f"  Shipment ID (blank=portfolio) [{_state.last_shipment}]: ")
    ship_id: int | None = None
    if scope:
        try:
            ship_id = int(scope)
            _set_shipment(ship_id)
        except ValueError:
            print(f"  Invalid number: '{scope}', using portfolio.")
    scenario = _ask_scenario_optional(ws)
    _, text = ws.execute(WorkingCapitalQuery(
        shipment_id=ship_id, scenario_name=scenario,
    ))
    _print_result(text)


def action_funding_comparison(ws: AnalyticalWorkspace) -> None:
    name = _choose_scenario(ws, "scenario", allow_baseline=False)
    if not name:
        return
    ship_id = _input_int("  Shipment ID (blank=portfolio): ")
    _, text = ws.execute(FundingComparisonQuery(
        scenario_name=name, shipment_id=ship_id,
    ))
    _print_result(text)

    # Offer to save
    save = _input("  Save as report? [y/N]: ")
    if save.lower() in ("y", "yes"):
        default_name = f"{name}_funding"
        rname = _input(f"  Report name [{default_name}]: ") or default_name
        ws.execute(SaveReportQuery(
            name=rname,
            source_query=FundingComparisonQuery(scenario_name=name, shipment_id=ship_id),
            description=f"Funding comparison: baseline vs {name}",
        ))
        _set_report(rname)
        print(f"  Saved report '{rname}'.")


def action_most_affected(ws: AnalyticalWorkspace) -> None:
    name = _choose_scenario(ws, "scenario", allow_baseline=False)
    if not name:
        return
    top_n = _input_int("  Top N [5]: ", 5)
    _, text = ws.execute(MostAffectedShipmentsQuery(
        scenario_name=name, top_n=top_n or 5,
    ))
    _print_result(text)


# ---------------------------------------------------------------------------
# Menu actions — Reports
# ---------------------------------------------------------------------------


REPORT_QUERY_TYPES = [
    ("explain_shipment", "Explain a shipment"),
    ("scenario_summary", "Scenario impact summary"),
    ("funding_comparison", "Funding comparison"),
    ("working_capital", "Working capital profile"),
    ("most_affected", "Most affected shipments"),
]


def action_save_report(ws: AnalyticalWorkspace) -> None:
    print("  Select query type to execute and save:")
    for i, (key, desc) in enumerate(REPORT_QUERY_TYPES):
        print(f"    [{i + 1}] {desc}")
    raw = _input("  Query type (# or name): ")
    if not raw:
        return

    # Resolve to key
    qtype = None
    try:
        idx = int(raw) - 1
        if 0 <= idx < len(REPORT_QUERY_TYPES):
            qtype = REPORT_QUERY_TYPES[idx][0]
    except ValueError:
        qtype = raw

    source_query = None
    if qtype == "explain_shipment":
        sid = _ask_shipment()
        scn = _ask_scenario_optional(ws)
        source_query = ExplainShipmentQuery(shipment_id=sid or 1, scenario_name=scn)
    elif qtype == "scenario_summary":
        scn = _choose_scenario(ws, "scenario", allow_baseline=False)
        if not scn:
            return
        source_query = ScenarioSummaryQuery(scenario_name=scn)
    elif qtype == "funding_comparison":
        scn = _choose_scenario(ws, "scenario", allow_baseline=False)
        if not scn:
            return
        source_query = FundingComparisonQuery(scenario_name=scn)
    elif qtype == "working_capital":
        sid = _input_int("  Shipment ID (blank=portfolio): ")
        scn = _ask_scenario_optional(ws)
        source_query = WorkingCapitalQuery(shipment_id=sid, scenario_name=scn)
    elif qtype == "most_affected":
        scn = _choose_scenario(ws, "scenario", allow_baseline=False)
        if not scn:
            return
        top_n = _input_int("  Top N [5]: ", 5)
        source_query = MostAffectedShipmentsQuery(
            scenario_name=scn, top_n=top_n or 5,
        )
    else:
        print(f"  Unknown query type: '{qtype}'")
        return

    name = _input("  Report name: ")
    if not name:
        return
    desc = _input("  Description (optional): ")
    _, text = ws.execute(SaveReportQuery(
        name=name, source_query=source_query, description=desc,
    ))
    _set_report(name)
    _print_result(text)


def action_list_reports(ws: AnalyticalWorkspace) -> None:
    _, text = ws.execute(ListReportsQuery())
    _print_result(text)


def action_get_report(ws: AnalyticalWorkspace) -> None:
    name = _choose_report(ws)
    if not name:
        return
    _, text = ws.execute(GetReportQuery(name=name))
    _print_result(text)


def action_delete_report(ws: AnalyticalWorkspace) -> None:
    name = _choose_report(ws)
    if not name:
        return
    confirm = _input(f"  Delete report '{name}'? [y/N]: ")
    if confirm.lower() not in ("y", "yes"):
        print("  Cancelled.")
        return
    _, text = ws.execute(DeleteReportQuery(name=name))
    _print_result(text)


# ---------------------------------------------------------------------------
# Guided workflows
# ---------------------------------------------------------------------------


def workflow_scenario_stress(ws: AnalyticalWorkspace) -> None:
    """Guided: create scenario from template -> compare vs baseline."""
    print()
    print("  GUIDED WORKFLOW: Scenario Stress Test")
    print(THIN)
    print("  Step 1/3: Choose a template")
    name = _choose_template(ws)
    if not name:
        return

    print()
    print("  Step 2/3: Name the scenario")
    default_scenario = name.replace("_stress", "").replace("total_", "")
    scenario = _input(f"  Scenario name [{default_scenario}]: ") or default_scenario
    _, text = ws.execute(CreateScenarioFromTemplateQuery(
        template_name=name, scenario_name=scenario,
    ))
    _set_scenario(scenario)
    _print_result(text)

    print()
    print("  Step 3/3: Compare vs baseline")
    _, text = ws.execute(CompareNamedScenariosQuery(
        scenario_a="baseline", scenario_b=scenario,
    ))
    _print_result(text)

    # Offer to save
    save = _input("  Save this comparison as a report? [y/N]: ")
    if save.lower() in ("y", "yes"):
        default_name = f"baseline_vs_{scenario}"
        rname = _input(f"  Report name [{default_name}]: ") or default_name
        ws.execute(SaveReportQuery(
            name=rname,
            source_query=CompareNamedScenariosQuery(
                scenario_a="baseline", scenario_b=scenario,
            ),
            description=f"Stress test: baseline vs {scenario}",
        ))
        _set_report(rname)
        print(f"  Saved report '{rname}'.")


def workflow_shipment_deep_dive(ws: AnalyticalWorkspace) -> None:
    """Guided: explain shipment -> drill into line items -> save report."""
    print()
    print("  GUIDED WORKFLOW: Shipment Deep Dive")
    print(THIN)
    print("  Step 1/3: Examine a shipment")
    ship_id = _ask_shipment()
    if ship_id is None:
        return
    scenario = _ask_scenario_optional(ws)
    _, text = ws.execute(ExplainShipmentQuery(
        shipment_id=ship_id, scenario_name=scenario,
    ))
    _print_result(text)

    # Step 2: drill into line items
    while True:
        print()
        print(f"  Step 2/3: Drill into a line item (shipment {ship_id})")
        print(f"  Cost types: {', '.join(COST_TYPES[:8])}")
        print(f"              {', '.join(COST_TYPES[8:])}")
        cost = _input("  Cost type (blank to skip): ")
        if not cost:
            break
        _, text = ws.execute(ExplainLineItemQuery(
            shipment_id=ship_id, cost_type=cost, scenario_name=scenario,
        ))
        _print_result(text)
        more = _input("  Examine another line item? [y/N]: ")
        if more.lower() not in ("y", "yes"):
            break

    # Step 3: offer to save
    print()
    print("  Step 3/3: Save shipment audit as report")
    save = _input("  Save? [y/N]: ")
    if save.lower() in ("y", "yes"):
        default_name = f"ship{ship_id}_audit"
        rname = _input(f"  Report name [{default_name}]: ") or default_name
        ws.execute(SaveReportQuery(
            name=rname,
            source_query=ExplainShipmentQuery(
                shipment_id=ship_id, scenario_name=scenario,
            ),
            description=f"Audit of shipment {ship_id}",
        ))
        _set_report(rname)
        print(f"  Saved report '{rname}'.")


def workflow_funding_stress(ws: AnalyticalWorkspace) -> None:
    """Guided: create downside scenario -> funding comparison -> save report."""
    print()
    print("  GUIDED WORKFLOW: Funding Stress Test")
    print(THIN)

    # Step 1: ensure a stress scenario exists
    scenarios = ws.list_scenarios()
    if scenarios:
        print("  Step 1/3: Select or create a stress scenario")
        choice = _input("  Use [e]xisting scenario or [n]ew from template? [e/n]: ") or "e"
        if choice.lower() in ("n", "new"):
            name = _choose_template(ws)
            if not name:
                return
            default_scenario = name.replace("_stress", "").replace("total_", "")
            scenario = _input(f"  Scenario name [{default_scenario}]: ") or default_scenario
            ws.execute(CreateScenarioFromTemplateQuery(
                template_name=name, scenario_name=scenario,
            ))
            _set_scenario(scenario)
            print(f"  Created scenario '{scenario}'.")
        else:
            scenario = _choose_scenario(ws, "scenario", allow_baseline=False)
            if not scenario:
                return
    else:
        print("  Step 1/3: Create a stress scenario")
        name = _choose_template(ws)
        if not name:
            return
        default_scenario = name.replace("_stress", "").replace("total_", "")
        scenario = _input(f"  Scenario name [{default_scenario}]: ") or default_scenario
        ws.execute(CreateScenarioFromTemplateQuery(
            template_name=name, scenario_name=scenario,
        ))
        _set_scenario(scenario)
        print(f"  Created scenario '{scenario}'.")

    # Step 2: funding comparison
    print()
    print("  Step 2/3: Funding comparison vs baseline")
    _, text = ws.execute(FundingComparisonQuery(scenario_name=scenario))
    _print_result(text)

    # Step 3: save
    print()
    print("  Step 3/3: Save funding report")
    save = _input("  Save? [y/N]: ")
    if save.lower() in ("y", "yes"):
        default_name = f"{scenario}_funding"
        rname = _input(f"  Report name [{default_name}]: ") or default_name
        ws.execute(SaveReportQuery(
            name=rname,
            source_query=FundingComparisonQuery(scenario_name=scenario),
            description=f"Funding stress: baseline vs {scenario}",
        ))
        _set_report(rname)
        print(f"  Saved report '{rname}'.")


# ---------------------------------------------------------------------------
# Menu structure
# ---------------------------------------------------------------------------


def _format_menu() -> str:
    return f"""
{THIN}
  MAIN MENU
{THIN}
  [h]  Home / overview

  Scenarios                          Analysis
  [t]  List templates                [x]  Explain shipment
  [i]  Inspect template              [l]  Explain line item
  [n]  Create scenario (new)         [w]  Working capital
  [ls] List saved scenarios          [fc] Funding comparison
  [cs] Compare two scenarios         [ma] Most affected shipments
  [ss] Scenario impact summary

  Reports                            Guided Workflows
  [sr] Save a report                 [s]  Stress test (template->compare)
  [lr] List reports                  [d]  Shipment deep dive (explain->audit)
  [gr] Retrieve a report             [f]  Funding stress (scenario->funding)
  [dr] Delete a report

  [q]  Quit
{THIN}"""


ACTIONS: dict[str, object] = {
    "h": show_overview,
    # Scenarios
    "t": action_list_templates,
    "i": action_inspect_template,
    "n": action_create_from_template,
    "ls": action_list_scenarios,
    "cs": action_compare_scenarios,
    "ss": action_scenario_summary,
    # Analysis
    "x": action_explain_shipment,
    "l": action_explain_line_item,
    "w": action_working_capital,
    "fc": action_funding_comparison,
    "ma": action_most_affected,
    # Reports
    "sr": action_save_report,
    "lr": action_list_reports,
    "gr": action_get_report,
    "dr": action_delete_report,
    # Guided workflows
    "s": workflow_scenario_stress,
    "d": workflow_shipment_deep_dive,
    "f": workflow_funding_stress,
}


def main_loop(ws: AnalyticalWorkspace) -> None:
    """Run the interactive menu loop."""
    show_overview(ws)

    while True:
        print(_format_menu())
        choice = _input("  > ").lower()
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
            print(f"  Unknown command: '{choice}'. Type 'h' for help.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    print(DIVIDER)
    print("  SAFI Meat-Export Analytical Workspace")
    print(DIVIDER)
    ws = build_workspace()
    main_loop(ws)


if __name__ == "__main__":
    main()
