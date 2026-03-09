"""Working capital / funding analysis on top of the cashflow engine.

Computes cumulative cash position over time from CashflowEntry objects,
identifies peak funding requirements, and compares baseline vs scenario.

Cash timing uses ``payment_date`` (when cash actually moves), not
``event_date`` (when the economic event occurs).

Public API:
    build_cash_timeline()             — sorted list of CashPositionPoints
    shipment_funding_profile()        — single-shipment funding analysis
    portfolio_funding_summary()       — all-shipment cumulative analysis
    compare_funding_profiles()        — baseline vs scenario funding comparison

Dataclasses:
    CashPositionPoint                 — one point on the cumulative cash curve
    ShipmentFundingProfile            — funding metrics for one shipment
    PortfolioFundingSummary           — funding metrics across all shipments
    FundingComparison                 — baseline vs scenario funding delta
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field

from safi_engine.config import ScenarioOverrides, StrategyConfig
from safi_engine.cycle import ShipmentCycle
from safi_engine.engine import CashflowEntry, compute_full_shipment_cashflow


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class CashPositionPoint:
    """One point on the cumulative cash position timeline.

    Represents the state after all cashflows on ``date`` are applied.
    """

    date: datetime.date
    daily_inflow: float
    daily_outflow: float
    daily_net: float           # inflow - outflow for this date
    cumulative_position: float  # running total from start
    entries: list[CashflowEntry] = field(default_factory=list)


@dataclass
class ShipmentFundingProfile:
    """Working capital analysis for a single shipment."""

    shipment_id: int
    customer_id: str
    proc_model: str
    first_cash_date: datetime.date
    last_cash_date: datetime.date
    cash_conversion_days: int       # last_cash_date - first_cash_date
    total_outflow: float
    total_inflow: float
    net_cashflow: float
    peak_deficit: float             # most negative cumulative position (<=0)
    peak_deficit_date: datetime.date | None
    peak_surplus: float             # most positive cumulative position (>=0)
    peak_surplus_date: datetime.date | None
    negative_cash_days: int         # dates where cumulative position < 0
    timeline: list[CashPositionPoint] = field(default_factory=list)


@dataclass
class PortfolioFundingSummary:
    """Working capital analysis across all shipments combined."""

    shipment_count: int
    first_cash_date: datetime.date
    last_cash_date: datetime.date
    total_outflow: float
    total_inflow: float
    net_cashflow: float
    peak_deficit: float
    peak_deficit_date: datetime.date | None
    peak_surplus: float
    peak_surplus_date: datetime.date | None
    negative_cash_days: int
    total_calendar_days: int
    timeline: list[CashPositionPoint] = field(default_factory=list)
    top_deficit_shipments: list[ShipmentFundingProfile] = field(default_factory=list)


@dataclass
class FundingComparison:
    """Baseline vs scenario funding comparison."""

    baseline: PortfolioFundingSummary | ShipmentFundingProfile
    scenario: PortfolioFundingSummary | ShipmentFundingProfile
    peak_deficit_delta: float       # scenario - baseline (negative = worse)
    peak_surplus_delta: float
    net_cashflow_delta: float
    negative_days_delta: int
    overrides_description: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Core analysis functions
# ---------------------------------------------------------------------------


def build_cash_timeline(entries: list[CashflowEntry]) -> list[CashPositionPoint]:
    """Build a chronological cumulative cash position timeline.

    Groups entries by payment_date, computes daily net, and accumulates
    a running cash position.  Returns one CashPositionPoint per date.
    """
    if not entries:
        return []

    # Group by payment_date
    by_date: dict[datetime.date, list[CashflowEntry]] = {}
    for e in entries:
        by_date.setdefault(e.payment_date, []).append(e)

    timeline: list[CashPositionPoint] = []
    cumulative = 0.0

    for date in sorted(by_date):
        day_entries = by_date[date]
        daily_inflow = sum(e.amount_pkr for e in day_entries if e.direction == "inflow")
        daily_outflow = sum(e.amount_pkr for e in day_entries if e.direction == "outflow")
        daily_net = daily_inflow - daily_outflow
        cumulative += daily_net
        timeline.append(CashPositionPoint(
            date=date,
            daily_inflow=daily_inflow,
            daily_outflow=daily_outflow,
            daily_net=daily_net,
            cumulative_position=cumulative,
            entries=day_entries,
        ))

    return timeline


def _extract_metrics(timeline: list[CashPositionPoint]) -> dict:
    """Extract peak deficit/surplus and negative-cash-days from a timeline."""
    if not timeline:
        return {
            "peak_deficit": 0.0, "peak_deficit_date": None,
            "peak_surplus": 0.0, "peak_surplus_date": None,
            "negative_cash_days": 0,
        }

    min_point = min(timeline, key=lambda p: p.cumulative_position)
    max_point = max(timeline, key=lambda p: p.cumulative_position)

    return {
        "peak_deficit": min(min_point.cumulative_position, 0.0),
        "peak_deficit_date": min_point.date if min_point.cumulative_position < 0 else None,
        "peak_surplus": max(max_point.cumulative_position, 0.0),
        "peak_surplus_date": max_point.date if max_point.cumulative_position > 0 else None,
        "negative_cash_days": sum(1 for p in timeline if p.cumulative_position < -0.01),
    }


# ---------------------------------------------------------------------------
# Single-shipment analysis
# ---------------------------------------------------------------------------


def shipment_funding_profile(
    cycle: ShipmentCycle,
    config: StrategyConfig,
    outflow_config: list[dict],
    overrides: ScenarioOverrides | None = None,
) -> ShipmentFundingProfile:
    """Compute working capital / funding profile for one shipment."""
    entries = compute_full_shipment_cashflow(cycle, config, outflow_config, overrides)
    timeline = build_cash_timeline(entries)

    total_outflow = sum(e.amount_pkr for e in entries if e.direction == "outflow")
    total_inflow = sum(e.amount_pkr for e in entries if e.direction == "inflow")
    metrics = _extract_metrics(timeline)

    first_date = timeline[0].date
    last_date = timeline[-1].date

    return ShipmentFundingProfile(
        shipment_id=cycle.shipment_number,
        customer_id=cycle.customer_id,
        proc_model=cycle.proc_model,
        first_cash_date=first_date,
        last_cash_date=last_date,
        cash_conversion_days=(last_date - first_date).days,
        total_outflow=total_outflow,
        total_inflow=total_inflow,
        net_cashflow=total_inflow - total_outflow,
        peak_deficit=metrics["peak_deficit"],
        peak_deficit_date=metrics["peak_deficit_date"],
        peak_surplus=metrics["peak_surplus"],
        peak_surplus_date=metrics["peak_surplus_date"],
        negative_cash_days=metrics["negative_cash_days"],
        timeline=timeline,
    )


# ---------------------------------------------------------------------------
# Multi-shipment portfolio analysis
# ---------------------------------------------------------------------------


def portfolio_funding_summary(
    cycles: list[ShipmentCycle],
    config: StrategyConfig,
    outflow_config: list[dict],
    overrides: ScenarioOverrides | None = None,
    top_n: int = 5,
) -> PortfolioFundingSummary:
    """Compute cumulative working capital profile across all shipments.

    Merges all cashflow entries into a single timeline, then extracts
    portfolio-level funding metrics.
    """
    # Collect all entries and per-shipment profiles
    all_entries: list[CashflowEntry] = []
    profiles: list[ShipmentFundingProfile] = []

    for cycle in cycles:
        entries = compute_full_shipment_cashflow(cycle, config, outflow_config, overrides)
        all_entries.extend(entries)
        profile = shipment_funding_profile(cycle, config, outflow_config, overrides)
        profiles.append(profile)

    timeline = build_cash_timeline(all_entries)

    total_outflow = sum(e.amount_pkr for e in all_entries if e.direction == "outflow")
    total_inflow = sum(e.amount_pkr for e in all_entries if e.direction == "inflow")
    metrics = _extract_metrics(timeline)

    first_date = timeline[0].date if timeline else datetime.date(1900, 1, 1)
    last_date = timeline[-1].date if timeline else datetime.date(1900, 1, 1)

    # Top deficit shipments
    top_deficit = sorted(profiles, key=lambda p: p.peak_deficit)[:top_n]

    return PortfolioFundingSummary(
        shipment_count=len(cycles),
        first_cash_date=first_date,
        last_cash_date=last_date,
        total_outflow=total_outflow,
        total_inflow=total_inflow,
        net_cashflow=total_inflow - total_outflow,
        peak_deficit=metrics["peak_deficit"],
        peak_deficit_date=metrics["peak_deficit_date"],
        peak_surplus=metrics["peak_surplus"],
        peak_surplus_date=metrics["peak_surplus_date"],
        negative_cash_days=metrics["negative_cash_days"],
        total_calendar_days=(last_date - first_date).days if timeline else 0,
        timeline=timeline,
        top_deficit_shipments=top_deficit,
    )


# ---------------------------------------------------------------------------
# Baseline vs scenario funding comparison
# ---------------------------------------------------------------------------


def compare_funding_profiles(
    cycles: list[ShipmentCycle],
    config: StrategyConfig,
    outflow_config: list[dict],
    overrides: ScenarioOverrides,
    single_shipment: bool = False,
) -> FundingComparison:
    """Compare baseline vs scenario funding profiles.

    When single_shipment=True and len(cycles)==1, returns ShipmentFundingProfile
    objects; otherwise returns PortfolioFundingSummary objects.
    """
    if single_shipment and len(cycles) == 1:
        cycle = cycles[0]
        baseline = shipment_funding_profile(cycle, config, outflow_config)
        scenario = shipment_funding_profile(cycle, config, outflow_config, overrides)
    else:
        baseline = portfolio_funding_summary(cycles, config, outflow_config)
        scenario = portfolio_funding_summary(cycles, config, outflow_config, overrides)

    desc: list[str] = []
    if overrides.usd_to_pkr is not None:
        desc.append(f"FX rate: usd_to_pkr = {overrides.usd_to_pkr}")
    if overrides.partha_rates is not None:
        desc.append(f"Partha rates: {overrides.partha_rates}")
    if overrides.outflow_rate_overrides is not None:
        desc.append(f"Outflow rate overrides: {overrides.outflow_rate_overrides}")
    if overrides.pricing_tiers is not None:
        desc.append(f"Pricing tiers: overridden")
    if overrides.customer_credit_days is not None:
        desc.append(f"Credit days: overridden")
    if overrides.proc_model is not None:
        desc.append(f"Procurement model: {overrides.proc_model}")

    return FundingComparison(
        baseline=baseline,
        scenario=scenario,
        peak_deficit_delta=scenario.peak_deficit - baseline.peak_deficit,
        peak_surplus_delta=scenario.peak_surplus - baseline.peak_surplus,
        net_cashflow_delta=scenario.net_cashflow - baseline.net_cashflow,
        negative_days_delta=scenario.negative_cash_days - baseline.negative_cash_days,
        overrides_description=desc,
    )


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def format_shipment_funding(profile: ShipmentFundingProfile) -> str:
    """Format a single shipment funding profile as a human-readable string."""
    lines: list[str] = []
    lines.append(f"FUNDING PROFILE: Shipment {profile.shipment_id} "
                 f"(Customer {profile.customer_id}, {profile.proc_model})")
    lines.append("-" * 60)
    lines.append(f"  Cash cycle:           {profile.first_cash_date} to {profile.last_cash_date} "
                 f"({profile.cash_conversion_days} days)")
    lines.append(f"  Total outflow:        {profile.total_outflow:>16,.0f} PKR")
    lines.append(f"  Total inflow:         {profile.total_inflow:>16,.0f} PKR")
    lines.append(f"  Net cashflow:         {profile.net_cashflow:>+16,.0f} PKR")
    lines.append(f"  Peak deficit:         {profile.peak_deficit:>16,.0f} PKR"
                 + (f"  on {profile.peak_deficit_date}" if profile.peak_deficit_date else ""))
    lines.append(f"  Peak surplus:         {profile.peak_surplus:>16,.0f} PKR"
                 + (f"  on {profile.peak_surplus_date}" if profile.peak_surplus_date else ""))
    lines.append(f"  Negative-cash dates:  {profile.negative_cash_days}")
    lines.append("")
    lines.append("  Cash Timeline:")
    lines.append(f"  {'Date':12s} {'Outflow':>14s} {'Inflow':>14s} {'Daily Net':>14s} {'Cumulative':>14s}")
    for pt in profile.timeline:
        lines.append(
            f"  {pt.date!s:12s} {pt.daily_outflow:>14,.0f} {pt.daily_inflow:>14,.0f} "
            f"{pt.daily_net:>+14,.0f} {pt.cumulative_position:>+14,.0f}"
        )
    return "\n".join(lines)


def format_portfolio_summary(summary: PortfolioFundingSummary) -> str:
    """Format portfolio-level funding summary as a human-readable string."""
    lines: list[str] = []
    lines.append("=" * 72)
    lines.append("PORTFOLIO FUNDING SUMMARY")
    lines.append("=" * 72)
    lines.append(f"  Shipments:            {summary.shipment_count}")
    lines.append(f"  Period:               {summary.first_cash_date} to {summary.last_cash_date} "
                 f"({summary.total_calendar_days} days)")
    lines.append(f"  Total outflow:        {summary.total_outflow:>16,.0f} PKR")
    lines.append(f"  Total inflow:         {summary.total_inflow:>16,.0f} PKR")
    lines.append(f"  Net cashflow:         {summary.net_cashflow:>+16,.0f} PKR")
    lines.append(f"  Peak deficit:         {summary.peak_deficit:>16,.0f} PKR"
                 + (f"  on {summary.peak_deficit_date}" if summary.peak_deficit_date else ""))
    lines.append(f"  Peak surplus:         {summary.peak_surplus:>16,.0f} PKR"
                 + (f"  on {summary.peak_surplus_date}" if summary.peak_surplus_date else ""))
    lines.append(f"  Negative-cash dates:  {summary.negative_cash_days} of {len(summary.timeline)} "
                 f"({summary.negative_cash_days / max(len(summary.timeline), 1) * 100:.0f}%)")

    if summary.top_deficit_shipments:
        lines.append("")
        lines.append("  Shipments with Deepest Individual Deficits:")
        for p in summary.top_deficit_shipments:
            if p.peak_deficit < -0.01:
                lines.append(
                    f"    Ship {p.shipment_id:>3d} (Customer {p.customer_id}, {p.proc_model})"
                    f"  deficit: {p.peak_deficit:>14,.0f} PKR"
                    f"  cycle: {p.cash_conversion_days}d"
                )

    lines.append("")
    lines.append("=" * 72)
    return "\n".join(lines)


def format_funding_comparison(comp: FundingComparison) -> str:
    """Format baseline vs scenario funding comparison."""
    lines: list[str] = []
    lines.append("=" * 72)
    lines.append("FUNDING COMPARISON: Baseline vs Scenario")
    lines.append("=" * 72)

    if comp.overrides_description:
        lines.append("")
        lines.append("Overrides Applied:")
        for d in comp.overrides_description:
            lines.append(f"  - {d}")

    b = comp.baseline
    s = comp.scenario
    lines.append("")
    lines.append(f"  {'Metric':30s} {'Baseline':>16s} {'Scenario':>16s} {'Delta':>16s}")
    lines.append(f"  {'-' * 78}")
    lines.append(f"  {'Net Cashflow':30s} {b.net_cashflow:>16,.0f} {s.net_cashflow:>16,.0f} {comp.net_cashflow_delta:>+16,.0f}")
    lines.append(f"  {'Peak Deficit':30s} {b.peak_deficit:>16,.0f} {s.peak_deficit:>16,.0f} {comp.peak_deficit_delta:>+16,.0f}")
    lines.append(f"  {'Peak Surplus':30s} {b.peak_surplus:>16,.0f} {s.peak_surplus:>16,.0f} {comp.peak_surplus_delta:>+16,.0f}")
    lines.append(f"  {'Negative-Cash Dates':30s} {b.negative_cash_days:>16d} {s.negative_cash_days:>16d} {comp.negative_days_delta:>+16d}")

    lines.append("")
    lines.append("=" * 72)
    return "\n".join(lines)
