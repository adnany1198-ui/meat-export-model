"""Query execution layer — dispatches structured queries to engine modules.

Public API:
    execute(query, context) -> (result, formatted_text)

The QueryContext bundles the shared state (cycles, config, outflow_config)
so individual queries stay small and focused on *what* to ask.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from safi_engine.config import ScenarioOverrides, StrategyConfig
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
    QueryType,
    RunScenarioQuery,
    ScenarioComparisonResult,
    ScenarioImpactSummary,
    ScenarioResult,
    ScenarioSummaryQuery,
    ShipmentExplanation,
    WorkingCapitalQuery,
    WorkingCapitalResult,
)
from safi_engine.scenario_analysis import (
    compare_all_shipments,
    compare_shipment_scenario,
    format_aggregate_summary,
    format_shipment_comparison,
    scenario_summary,
)
from safi_engine.working_capital import (
    compare_funding_profiles,
    format_funding_comparison,
    format_portfolio_summary,
    format_shipment_funding,
    portfolio_funding_summary,
    shipment_funding_profile,
)


# ---------------------------------------------------------------------------
# Query context — shared state for all queries
# ---------------------------------------------------------------------------


@dataclass
class QueryContext:
    """Bundles shared data so queries only express intent."""

    cycles: list[ShipmentCycle] = field(default_factory=list)
    config: StrategyConfig = field(default_factory=StrategyConfig)
    outflow_config: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_cycle(ctx: QueryContext, shipment_id: int) -> ShipmentCycle | None:
    return next((c for c in ctx.cycles if c.shipment_number == shipment_id), None)


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------

# Each handler returns (result_dataclass, formatted_text)

_QUERY_TYPE = (
    RunScenarioQuery
    | CompareScenarioQuery
    | ExplainShipmentQuery
    | ExplainLineItemQuery
    | ScenarioSummaryQuery
    | MostAffectedShipmentsQuery
    | WorkingCapitalQuery
    | FundingComparisonQuery
)


def execute(query: _QUERY_TYPE, ctx: QueryContext) -> tuple:
    """Dispatch a structured query and return (result, formatted_text)."""
    handlers = {
        QueryType.RUN_SCENARIO: _handle_run_scenario,
        QueryType.COMPARE_SCENARIO: _handle_compare_scenario,
        QueryType.EXPLAIN_SHIPMENT: _handle_explain_shipment,
        QueryType.EXPLAIN_LINE_ITEM: _handle_explain_line_item,
        QueryType.SCENARIO_SUMMARY: _handle_scenario_summary,
        QueryType.MOST_AFFECTED: _handle_most_affected,
        QueryType.WORKING_CAPITAL: _handle_working_capital,
        QueryType.FUNDING_COMPARISON: _handle_funding_comparison,
    }
    handler = handlers[query.query_type]
    return handler(query, ctx)


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def _handle_run_scenario(
    query: RunScenarioQuery, ctx: QueryContext,
) -> tuple[ScenarioResult, str]:
    overrides = query.overrides if _has_overrides(query.overrides) else None
    entries_by_ship: dict[int, list[CashflowEntry]] = {}

    if query.shipment_id is not None:
        cycle = _find_cycle(ctx, query.shipment_id)
        if cycle is None:
            return _not_found(query, query.shipment_id)
        entries = compute_full_shipment_cashflow(
            cycle, ctx.config, ctx.outflow_config, overrides,
        )
        entries_by_ship[cycle.shipment_number] = entries
    else:
        for cycle in ctx.cycles:
            entries = compute_full_shipment_cashflow(
                cycle, ctx.config, ctx.outflow_config, overrides,
            )
            entries_by_ship[cycle.shipment_number] = entries

    total_entries = sum(len(v) for v in entries_by_ship.values())
    result = ScenarioResult(
        query=query,
        entries_by_shipment=entries_by_ship,
        total_shipments=len(entries_by_ship),
        total_entries=total_entries,
    )
    text = _format_scenario_result(result)
    return result, text


def _handle_compare_scenario(
    query: CompareScenarioQuery, ctx: QueryContext,
) -> tuple[ScenarioComparisonResult, str]:
    if query.shipment_id is not None:
        cycle = _find_cycle(ctx, query.shipment_id)
        if cycle is None:
            return _not_found(query, query.shipment_id)
        comp = compare_shipment_scenario(
            cycle, ctx.config, ctx.outflow_config, query.overrides,
        )
        result = ScenarioComparisonResult(query=query, comparisons=[comp])
        text = format_shipment_comparison(comp)
    else:
        comps = compare_all_shipments(
            ctx.cycles, ctx.config, ctx.outflow_config, query.overrides,
        )
        summary = scenario_summary(comps, query.overrides)
        result = ScenarioComparisonResult(
            query=query, comparisons=comps, summary=summary,
        )
        text = format_aggregate_summary(summary)
    return result, text


def _handle_explain_shipment(
    query: ExplainShipmentQuery, ctx: QueryContext,
) -> tuple[ShipmentExplanation, str]:
    cycle = _find_cycle(ctx, query.shipment_id)
    if cycle is None:
        return _not_found(query, query.shipment_id)

    overrides = query.overrides if query.overrides and _has_overrides(query.overrides) else None
    entries = compute_full_shipment_cashflow(
        cycle, ctx.config, ctx.outflow_config, overrides,
    )
    total_out = sum(e.amount_pkr for e in entries if e.direction == "outflow")
    total_in = sum(e.amount_pkr for e in entries if e.direction == "inflow")

    result = ShipmentExplanation(
        query=query,
        shipment_id=cycle.shipment_number,
        customer_id=cycle.customer_id,
        proc_model=cycle.proc_model,
        entries=entries,
        total_outflow=total_out,
        total_inflow=total_in,
        net_cashflow=total_in - total_out,
    )
    text = _format_shipment_explanation(result)
    return result, text


def _handle_explain_line_item(
    query: ExplainLineItemQuery, ctx: QueryContext,
) -> tuple[LineItemExplanation, str]:
    cycle = _find_cycle(ctx, query.shipment_id)
    if cycle is None:
        return _not_found(query, query.shipment_id)

    overrides = query.overrides if query.overrides and _has_overrides(query.overrides) else None
    entries = compute_full_shipment_cashflow(
        cycle, ctx.config, ctx.outflow_config, overrides,
    )
    match = next((e for e in entries if e.cost_type == query.cost_type), None)

    result = LineItemExplanation(query=query, entry=match, found=match is not None)
    text = _format_line_item_explanation(result)
    return result, text


def _handle_scenario_summary(
    query: ScenarioSummaryQuery, ctx: QueryContext,
) -> tuple[ScenarioImpactSummary, str]:
    comps = compare_all_shipments(
        ctx.cycles, ctx.config, ctx.outflow_config, query.overrides,
    )
    summary = scenario_summary(comps, query.overrides, top_n=query.top_n)
    result = ScenarioImpactSummary(query=query, summary=summary)
    text = format_aggregate_summary(summary)
    return result, text


def _handle_most_affected(
    query: MostAffectedShipmentsQuery, ctx: QueryContext,
) -> tuple[MostAffectedResult, str]:
    comps = compare_all_shipments(
        ctx.cycles, ctx.config, ctx.outflow_config, query.overrides,
    )
    ranked = sorted(comps, key=lambda c: abs(c.net_delta), reverse=True)
    top = ranked[: query.top_n]
    result = MostAffectedResult(query=query, shipments=top)
    text = _format_most_affected(result)
    return result, text


def _handle_working_capital(
    query: WorkingCapitalQuery, ctx: QueryContext,
) -> tuple[WorkingCapitalResult, str]:
    overrides = query.overrides if query.overrides and _has_overrides(query.overrides) else None

    if query.shipment_id is not None:
        cycle = _find_cycle(ctx, query.shipment_id)
        if cycle is None:
            return _not_found(query, query.shipment_id)
        profile = shipment_funding_profile(
            cycle, ctx.config, ctx.outflow_config, overrides,
        )
        result = WorkingCapitalResult(query=query, shipment_profile=profile)
        text = format_shipment_funding(profile)
    else:
        summary = portfolio_funding_summary(
            ctx.cycles, ctx.config, ctx.outflow_config, overrides,
        )
        result = WorkingCapitalResult(query=query, portfolio_summary=summary)
        text = format_portfolio_summary(summary)
    return result, text


def _handle_funding_comparison(
    query: FundingComparisonQuery, ctx: QueryContext,
) -> tuple[FundingComparisonResult, str]:
    if query.shipment_id is not None:
        cycle = _find_cycle(ctx, query.shipment_id)
        if cycle is None:
            return _not_found(query, query.shipment_id)
        comp = compare_funding_profiles(
            [cycle], ctx.config, ctx.outflow_config, query.overrides,
            single_shipment=True,
        )
    else:
        comp = compare_funding_profiles(
            ctx.cycles, ctx.config, ctx.outflow_config, query.overrides,
        )
    result = FundingComparisonResult(query=query, comparison=comp)
    text = format_funding_comparison(comp)
    return result, text


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _has_overrides(ov: ScenarioOverrides) -> bool:
    return any([
        ov.usd_to_pkr is not None,
        ov.pricing_tiers is not None,
        ov.customer_credit_days is not None,
        ov.partha_rates is not None,
        ov.outflow_rate_overrides is not None,
        ov.proc_model is not None,
    ])


def _not_found(query, shipment_id: int):
    """Return a minimal result + error text for missing shipment."""
    text = f"Shipment {shipment_id} not found."
    # Return the most reasonable empty result for the query type
    if isinstance(query, ExplainShipmentQuery):
        return ShipmentExplanation(query=query), text
    if isinstance(query, ExplainLineItemQuery):
        return LineItemExplanation(query=query), text
    if isinstance(query, WorkingCapitalQuery):
        return WorkingCapitalResult(query=query), text
    if isinstance(query, FundingComparisonQuery):
        return FundingComparisonResult(query=query), text
    if isinstance(query, (RunScenarioQuery, CompareScenarioQuery)):
        return ScenarioResult(query=RunScenarioQuery()), text
    return None, text


def _format_scenario_result(result: ScenarioResult) -> str:
    lines: list[str] = []
    lines.append("=" * 60)
    label = "SCENARIO" if _has_overrides(result.query.overrides) else "BASELINE"
    lines.append(f"{label} CASHFLOW RESULT")
    lines.append("=" * 60)
    lines.append(f"  Shipments: {result.total_shipments}")
    lines.append(f"  Total entries: {result.total_entries}")

    for ship_id in sorted(result.entries_by_shipment):
        entries = result.entries_by_shipment[ship_id]
        total_out = sum(e.amount_pkr for e in entries if e.direction == "outflow")
        total_in = sum(e.amount_pkr for e in entries if e.direction == "inflow")
        lines.append(
            f"  Ship {ship_id:>3d}:  outflow {total_out:>14,.0f}  "
            f"inflow {total_in:>14,.0f}  net {total_in - total_out:>+14,.0f}"
        )
    lines.append("=" * 60)
    return "\n".join(lines)


def _format_shipment_explanation(expl: ShipmentExplanation) -> str:
    lines: list[str] = []
    lines.append(f"SHIPMENT EXPLANATION: Ship {expl.shipment_id} "
                 f"(Customer {expl.customer_id}, {expl.proc_model})")
    lines.append("=" * 72)
    lines.append(f"  Total outflow: {expl.total_outflow:>14,.0f} PKR")
    lines.append(f"  Total inflow:  {expl.total_inflow:>14,.0f} PKR")
    lines.append(f"  Net cashflow:  {expl.net_cashflow:>+14,.0f} PKR")
    lines.append("")
    lines.append("  Line Items:")
    lines.append(
        f"  {'Item':16s} {'Dir':7s} {'Amount':>14s} {'Event Date':>12s} "
        f"{'Pay Date':>12s} {'Rule':20s} {'Formula'}"
    )
    lines.append(f"  {'-' * 110}")
    for e in expl.entries:
        lines.append(
            f"  {e.cost_type:16s} {e.direction:7s} {e.amount_pkr:>14,.0f} "
            f"{e.event_date!s:>12s} {e.payment_date!s:>12s} "
            f"{e.rule_name:20s} {e.formula_description}"
        )
    lines.append("")

    # Provenance detail
    lines.append("  Provenance Detail:")
    for e in expl.entries:
        lines.append(f"    {e.cost_type} ({e.direction}):")
        lines.append(f"      Rule:    {e.rule_name}")
        lines.append(f"      Formula: {e.formula_description}")
        lines.append(f"      Inputs:  {e.inputs_used}")
        if e.rate_used is not None:
            lines.append(f"      Rate:    {e.rate_used}")
        lines.append(f"      Timing:  {e.timing_basis}")
        if e.overrides_applied:
            lines.append(f"      Overrides: {'; '.join(e.overrides_applied)}")
        if e.notes:
            lines.append(f"      Notes:   {e.notes}")
    return "\n".join(lines)


def _format_line_item_explanation(expl: LineItemExplanation) -> str:
    if not expl.found or expl.entry is None:
        return (
            f"Line item '{expl.query.cost_type}' not found "
            f"in Shipment {expl.query.shipment_id}."
        )

    e = expl.entry
    lines: list[str] = []
    lines.append(f"LINE ITEM: {e.cost_type} ({e.direction})")
    lines.append(f"  Shipment {e.shipment_id}, Customer {e.customer_id}")
    lines.append("=" * 60)
    lines.append(f"  Amount:          {e.amount_pkr:>14,.0f} PKR")
    lines.append(f"  Event date:      {e.event_date}")
    lines.append(f"  Payment date:    {e.payment_date}")
    lines.append(f"  Model type:      {e.model_type}")
    lines.append(f"  Rule:            {e.rule_name}")
    lines.append(f"  Formula:         {e.formula_description}")
    lines.append(f"  Inputs:          {e.inputs_used}")
    if e.rate_used is not None:
        lines.append(f"  Rate used:       {e.rate_used}")
    lines.append(f"  Timing basis:    {e.timing_basis}")
    lines.append(f"  Source:          {e.source_assumption}")
    if e.overrides_applied:
        lines.append(f"  Overrides:       {'; '.join(e.overrides_applied)}")
    if e.notes:
        lines.append(f"  Notes:           {e.notes}")
    return "\n".join(lines)


def _format_most_affected(result: MostAffectedResult) -> str:
    lines: list[str] = []
    lines.append("=" * 72)
    lines.append("MOST AFFECTED SHIPMENTS BY SCENARIO")
    lines.append("=" * 72)
    lines.append(
        f"  {'Rank':>4s}  {'Ship':>4s}  {'Customer':>8s}  {'Model':>8s}  "
        f"{'Baseline Net':>14s}  {'Scenario Net':>14s}  {'Delta':>14s}"
    )
    lines.append(f"  {'-' * 70}")
    for i, c in enumerate(result.shipments, 1):
        lines.append(
            f"  {i:>4d}  {c.shipment_id:>4d}  {c.customer_id:>8s}  "
            f"{c.proc_model:>8s}  {c.baseline_net:>14,.0f}  "
            f"{c.scenario_net:>14,.0f}  {c.net_delta:>+14,.0f}"
        )
    lines.append("=" * 72)
    return "\n".join(lines)
