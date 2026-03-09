"""Scenario comparison layer — compares baseline vs scenario cashflows.

Public API:
    compare_shipment_scenario()   — single shipment baseline vs scenario
    compare_all_shipments()       — all shipments baseline vs scenario
    aggregate_deltas_by_line_item() — group deltas by cost_type
    scenario_summary()            — top-level summary with top contributors

Dataclasses:
    LineItemDelta               — one line item's baseline vs scenario delta
    ShipmentScenarioComparison  — full comparison for one shipment
    AggregateScenarioSummary    — all-shipment summary with top movers
"""

from __future__ import annotations

from dataclasses import dataclass, field

from safi_engine.config import ScenarioOverrides, StrategyConfig
from safi_engine.cycle import ShipmentCycle
from safi_engine.engine import CashflowEntry, compute_full_shipment_cashflow


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class LineItemDelta:
    """Delta for one line item between baseline and scenario."""

    shipment_id: int
    cost_type: str
    direction: str
    model_type: str
    baseline_amount: float
    scenario_amount: float
    delta: float  # scenario - baseline (positive = higher in scenario)
    overrides_applied: list[str] = field(default_factory=list)
    rule_name: str = ""


@dataclass
class ShipmentScenarioComparison:
    """Full baseline vs scenario comparison for one shipment."""

    shipment_id: int
    customer_id: str
    proc_model: str
    baseline_net: float  # inflows - outflows
    scenario_net: float
    net_delta: float
    baseline_total_outflow: float
    scenario_total_outflow: float
    baseline_total_inflow: float
    scenario_total_inflow: float
    line_items: list[LineItemDelta] = field(default_factory=list)

    @property
    def outflow_delta(self) -> float:
        return self.scenario_total_outflow - self.baseline_total_outflow

    @property
    def inflow_delta(self) -> float:
        return self.scenario_total_inflow - self.baseline_total_inflow


@dataclass
class AggregateScenarioSummary:
    """All-shipment scenario summary with top contributors."""

    total_baseline_net: float
    total_scenario_net: float
    total_net_delta: float
    shipment_count: int
    shipments_affected: int  # shipments with non-zero delta
    deltas_by_line_item: dict[str, float] = field(default_factory=dict)
    top_positive: list[LineItemDelta] = field(default_factory=list)
    top_negative: list[LineItemDelta] = field(default_factory=list)
    most_affected_shipments: list[ShipmentScenarioComparison] = field(default_factory=list)
    overrides_description: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Comparison functions
# ---------------------------------------------------------------------------


def _net_cashflow(entries: list[CashflowEntry]) -> float:
    """Compute net cashflow: inflows - outflows."""
    return sum(
        e.amount_pkr if e.direction == "inflow" else -e.amount_pkr
        for e in entries
    )


def _total_by_direction(entries: list[CashflowEntry], direction: str) -> float:
    return sum(e.amount_pkr for e in entries if e.direction == direction)


def compare_shipment_scenario(
    cycle: ShipmentCycle,
    config: StrategyConfig,
    outflow_config: list[dict],
    overrides: ScenarioOverrides,
) -> ShipmentScenarioComparison:
    """Compare baseline vs scenario cashflow for a single shipment."""
    baseline = compute_full_shipment_cashflow(cycle, config, outflow_config)
    scenario = compute_full_shipment_cashflow(cycle, config, outflow_config, overrides)

    # Build line-item deltas by matching on (cost_type, direction)
    baseline_by_key = {(e.cost_type, e.direction): e for e in baseline}
    scenario_by_key = {(e.cost_type, e.direction): e for e in scenario}

    line_items: list[LineItemDelta] = []
    all_keys = sorted(set(baseline_by_key) | set(scenario_by_key))
    for key in all_keys:
        b = baseline_by_key.get(key)
        s = scenario_by_key.get(key)
        b_amt = b.amount_pkr if b else 0.0
        s_amt = s.amount_pkr if s else 0.0
        line_items.append(LineItemDelta(
            shipment_id=cycle.shipment_number,
            cost_type=key[0],
            direction=key[1],
            model_type=(s or b).model_type,
            baseline_amount=b_amt,
            scenario_amount=s_amt,
            delta=s_amt - b_amt,
            overrides_applied=s.overrides_applied if s else [],
            rule_name=(s or b).rule_name,
        ))

    baseline_net = _net_cashflow(baseline)
    scenario_net = _net_cashflow(scenario)

    return ShipmentScenarioComparison(
        shipment_id=cycle.shipment_number,
        customer_id=cycle.customer_id,
        proc_model=cycle.proc_model,
        baseline_net=baseline_net,
        scenario_net=scenario_net,
        net_delta=scenario_net - baseline_net,
        baseline_total_outflow=_total_by_direction(baseline, "outflow"),
        scenario_total_outflow=_total_by_direction(scenario, "outflow"),
        baseline_total_inflow=_total_by_direction(baseline, "inflow"),
        scenario_total_inflow=_total_by_direction(scenario, "inflow"),
        line_items=line_items,
    )


def compare_all_shipments(
    cycles: list[ShipmentCycle],
    config: StrategyConfig,
    outflow_config: list[dict],
    overrides: ScenarioOverrides,
) -> list[ShipmentScenarioComparison]:
    """Compare baseline vs scenario for all shipments."""
    return [
        compare_shipment_scenario(cycle, config, outflow_config, overrides)
        for cycle in cycles
    ]


def aggregate_deltas_by_line_item(
    comparisons: list[ShipmentScenarioComparison],
) -> dict[str, float]:
    """Aggregate deltas across shipments, grouped by cost_type.

    Returns {cost_type: total_delta} sorted by absolute delta descending.
    """
    totals: dict[str, float] = {}
    for comp in comparisons:
        for li in comp.line_items:
            totals[li.cost_type] = totals.get(li.cost_type, 0.0) + li.delta
    return dict(sorted(totals.items(), key=lambda kv: abs(kv[1]), reverse=True))


def _describe_overrides(overrides: ScenarioOverrides) -> list[str]:
    """Produce a human-readable list of what the overrides change."""
    desc: list[str] = []
    if overrides.usd_to_pkr is not None:
        desc.append(f"FX rate: usd_to_pkr = {overrides.usd_to_pkr}")
    if overrides.partha_rates is not None:
        desc.append(f"Partha rates: {overrides.partha_rates}")
    if overrides.outflow_rate_overrides is not None:
        desc.append(f"Outflow rate overrides: {overrides.outflow_rate_overrides}")
    if overrides.pricing_tiers is not None:
        desc.append(f"Pricing tiers: overridden ({len(overrides.pricing_tiers)} tiers)")
    if overrides.customer_credit_days is not None:
        desc.append(f"Credit days: overridden ({len(overrides.customer_credit_days)} months)")
    if overrides.proc_model is not None:
        desc.append(f"Procurement model: {overrides.proc_model}")
    return desc


def scenario_summary(
    comparisons: list[ShipmentScenarioComparison],
    overrides: ScenarioOverrides,
    top_n: int = 5,
) -> AggregateScenarioSummary:
    """Produce an aggregate summary across all shipment comparisons."""
    total_baseline = sum(c.baseline_net for c in comparisons)
    total_scenario = sum(c.scenario_net for c in comparisons)
    deltas_by_item = aggregate_deltas_by_line_item(comparisons)

    # Collect all line-item deltas across shipments
    all_deltas = [li for c in comparisons for li in c.line_items if abs(li.delta) > 0.01]
    all_deltas.sort(key=lambda d: d.delta)

    top_negative = all_deltas[:top_n]
    top_positive = list(reversed(all_deltas[-top_n:])) if len(all_deltas) >= top_n else list(reversed(all_deltas))

    # Most affected shipments by absolute net delta
    affected = sorted(comparisons, key=lambda c: abs(c.net_delta), reverse=True)

    return AggregateScenarioSummary(
        total_baseline_net=total_baseline,
        total_scenario_net=total_scenario,
        total_net_delta=total_scenario - total_baseline,
        shipment_count=len(comparisons),
        shipments_affected=sum(1 for c in comparisons if abs(c.net_delta) > 0.01),
        deltas_by_line_item=deltas_by_item,
        top_positive=top_positive,
        top_negative=top_negative,
        most_affected_shipments=affected[:top_n],
        overrides_description=_describe_overrides(overrides),
    )


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def format_shipment_comparison(comp: ShipmentScenarioComparison) -> str:
    """Format a single shipment comparison as a human-readable string."""
    lines: list[str] = []
    lines.append(f"Shipment {comp.shipment_id} (Customer {comp.customer_id}, {comp.proc_model})")
    lines.append("-" * 60)
    lines.append(f"  {'':30s} {'Baseline':>14s} {'Scenario':>14s} {'Delta':>14s}")
    lines.append(f"  {'Total Outflow':30s} {comp.baseline_total_outflow:>14,.0f} {comp.scenario_total_outflow:>14,.0f} {comp.outflow_delta:>+14,.0f}")
    lines.append(f"  {'Total Inflow':30s} {comp.baseline_total_inflow:>14,.0f} {comp.scenario_total_inflow:>14,.0f} {comp.inflow_delta:>+14,.0f}")
    lines.append(f"  {'Net Cashflow':30s} {comp.baseline_net:>14,.0f} {comp.scenario_net:>14,.0f} {comp.net_delta:>+14,.0f}")
    lines.append("")
    lines.append("  Line Item Detail:")
    lines.append(f"  {'Item':20s} {'Dir':5s} {'Baseline':>14s} {'Scenario':>14s} {'Delta':>14s}  Overrides")
    for li in comp.line_items:
        overrides_str = "; ".join(li.overrides_applied) if li.overrides_applied else ""
        delta_str = f"{li.delta:>+14,.0f}" if abs(li.delta) > 0.01 else f"{'0':>14s}"
        lines.append(
            f"  {li.cost_type:20s} {li.direction:5s} "
            f"{li.baseline_amount:>14,.0f} {li.scenario_amount:>14,.0f} "
            f"{delta_str}  {overrides_str}"
        )
    return "\n".join(lines)


def format_aggregate_summary(summary: AggregateScenarioSummary) -> str:
    """Format aggregate scenario summary as a human-readable string."""
    lines: list[str] = []
    lines.append("=" * 72)
    lines.append("SCENARIO COMPARISON SUMMARY")
    lines.append("=" * 72)

    if summary.overrides_description:
        lines.append("")
        lines.append("Overrides Applied:")
        for d in summary.overrides_description:
            lines.append(f"  - {d}")

    lines.append("")
    lines.append(f"Shipments analysed:  {summary.shipment_count}")
    lines.append(f"Shipments affected:  {summary.shipments_affected}")
    lines.append("")
    lines.append(f"  {'':25s} {'Baseline':>16s} {'Scenario':>16s} {'Delta':>16s}")
    lines.append(f"  {'Total Net Cashflow':25s} {summary.total_baseline_net:>16,.0f} {summary.total_scenario_net:>16,.0f} {summary.total_net_delta:>+16,.0f}")

    lines.append("")
    lines.append("Deltas by Line Item (all shipments):")
    for item, delta in summary.deltas_by_line_item.items():
        if abs(delta) > 0.01:
            lines.append(f"  {item:25s} {delta:>+16,.0f} PKR")

    if summary.top_positive:
        lines.append("")
        lines.append("Top Positive Deltas (single line items):")
        for li in summary.top_positive:
            if li.delta > 0.01:
                lines.append(f"  Ship {li.shipment_id:>3d} {li.cost_type:20s} {li.delta:>+14,.0f} PKR")

    if summary.top_negative:
        lines.append("")
        lines.append("Top Negative Deltas (single line items):")
        for li in summary.top_negative:
            if li.delta < -0.01:
                lines.append(f"  Ship {li.shipment_id:>3d} {li.cost_type:20s} {li.delta:>+14,.0f} PKR")

    if summary.most_affected_shipments:
        lines.append("")
        lines.append("Most Affected Shipments:")
        for c in summary.most_affected_shipments:
            if abs(c.net_delta) > 0.01:
                lines.append(
                    f"  Ship {c.shipment_id:>3d} (Customer {c.customer_id}, {c.proc_model})"
                    f"  net delta: {c.net_delta:>+14,.0f} PKR"
                )

    lines.append("")
    lines.append("=" * 72)
    return "\n".join(lines)
