"""Structured query and result types for the analytical workspace.

Queries are explicit dataclasses — no free-form text parsing.
A future conversational interface would construct these objects from
user intent and pass them to query_runner.execute().

Query types (analytical):
    RunScenarioQuery           — compute cashflows under a scenario
    CompareScenarioQuery       — baseline vs scenario comparison
    ExplainShipmentQuery       — full cashflow breakdown with provenance
    ExplainLineItemQuery       — single line-item provenance detail
    ScenarioSummaryQuery       — aggregate scenario impact summary
    MostAffectedShipmentsQuery — top N shipments by scenario delta
    WorkingCapitalQuery        — funding profile (single or portfolio)
    FundingComparisonQuery     — baseline vs scenario funding metrics

Query types (workspace lifecycle):
    SaveScenarioQuery          — save/update a named scenario
    ListScenariosQuery         — list all saved scenarios
    DeleteScenarioQuery        — delete a named scenario
    RenameScenarioQuery        — rename a named scenario
    CompareNamedScenariosQuery — compare two named scenarios

Result types:
    ScenarioResult             — cashflow entries under a scenario
    ScenarioComparisonResult   — baseline vs scenario with deltas
    ShipmentExplanation        — annotated cashflow for one shipment
    LineItemExplanation        — single entry provenance detail
    ScenarioImpactSummary      — aggregate summary with top movers
    MostAffectedResult         — ranked list of affected shipments
    WorkingCapitalResult       — funding profile with timeline
    FundingComparisonResult    — baseline vs scenario funding delta

Named scenario support:
    Analytical queries accept an optional ``scenario_name`` field.
    When set, the workspace resolves the name to ScenarioOverrides
    before dispatching.  ``scenario_name`` takes priority over
    inline ``overrides``.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from enum import Enum, auto

from safi_engine.config import ScenarioOverrides
from safi_engine.engine import CashflowEntry
from safi_engine.scenario_analysis import (
    AggregateScenarioSummary,
    ShipmentScenarioComparison,
)
from safi_engine.working_capital import (
    FundingComparison,
    PortfolioFundingSummary,
    ShipmentFundingProfile,
)


# ---------------------------------------------------------------------------
# Query type enum (for dispatch / logging)
# ---------------------------------------------------------------------------


class QueryType(Enum):
    RUN_SCENARIO = auto()
    COMPARE_SCENARIO = auto()
    EXPLAIN_SHIPMENT = auto()
    EXPLAIN_LINE_ITEM = auto()
    SCENARIO_SUMMARY = auto()
    MOST_AFFECTED = auto()
    WORKING_CAPITAL = auto()
    FUNDING_COMPARISON = auto()
    # Workspace lifecycle
    SAVE_SCENARIO = auto()
    LIST_SCENARIOS = auto()
    DELETE_SCENARIO = auto()
    RENAME_SCENARIO = auto()
    COMPARE_NAMED = auto()
    # Report lifecycle
    SAVE_REPORT = auto()
    LIST_REPORTS = auto()
    GET_REPORT = auto()
    DELETE_REPORT = auto()
    RENAME_REPORT = auto()
    # Template lifecycle
    LIST_TEMPLATES = auto()
    INSPECT_TEMPLATE = auto()
    CREATE_FROM_TEMPLATE = auto()


# ---------------------------------------------------------------------------
# Query dataclasses
# ---------------------------------------------------------------------------


@dataclass
class RunScenarioQuery:
    """Compute cashflows for one or all shipments under a scenario."""

    query_type: QueryType = field(default=QueryType.RUN_SCENARIO, init=False)
    overrides: ScenarioOverrides = field(default_factory=ScenarioOverrides)
    shipment_id: int | None = None  # None = all shipments
    scenario_name: str | None = None  # resolved by workspace


@dataclass
class CompareScenarioQuery:
    """Compare baseline vs scenario for one or all shipments."""

    query_type: QueryType = field(default=QueryType.COMPARE_SCENARIO, init=False)
    overrides: ScenarioOverrides = field(default_factory=ScenarioOverrides)
    shipment_id: int | None = None  # None = all shipments
    scenario_name: str | None = None


@dataclass
class ExplainShipmentQuery:
    """Show full cashflow breakdown with provenance for one shipment."""

    query_type: QueryType = field(default=QueryType.EXPLAIN_SHIPMENT, init=False)
    shipment_id: int = 1
    overrides: ScenarioOverrides | None = None  # None = baseline
    scenario_name: str | None = None


@dataclass
class ExplainLineItemQuery:
    """Show provenance detail for a specific line item in a shipment."""

    query_type: QueryType = field(default=QueryType.EXPLAIN_LINE_ITEM, init=False)
    shipment_id: int = 1
    cost_type: str = ""  # e.g. "Partha", "Freight", "SALE"
    overrides: ScenarioOverrides | None = None
    scenario_name: str | None = None


@dataclass
class ScenarioSummaryQuery:
    """Aggregate scenario impact summary across all shipments."""

    query_type: QueryType = field(default=QueryType.SCENARIO_SUMMARY, init=False)
    overrides: ScenarioOverrides = field(default_factory=ScenarioOverrides)
    top_n: int = 5
    scenario_name: str | None = None


@dataclass
class MostAffectedShipmentsQuery:
    """Rank shipments by absolute scenario impact."""

    query_type: QueryType = field(default=QueryType.MOST_AFFECTED, init=False)
    overrides: ScenarioOverrides = field(default_factory=ScenarioOverrides)
    top_n: int = 5
    scenario_name: str | None = None


@dataclass
class WorkingCapitalQuery:
    """Compute working capital / funding profile."""

    query_type: QueryType = field(default=QueryType.WORKING_CAPITAL, init=False)
    shipment_id: int | None = None  # None = portfolio
    overrides: ScenarioOverrides | None = None
    scenario_name: str | None = None


@dataclass
class FundingComparisonQuery:
    """Compare baseline vs scenario funding profiles."""

    query_type: QueryType = field(default=QueryType.FUNDING_COMPARISON, init=False)
    overrides: ScenarioOverrides = field(default_factory=ScenarioOverrides)
    shipment_id: int | None = None  # None = portfolio
    scenario_name: str | None = None


# ---------------------------------------------------------------------------
# Workspace lifecycle query dataclasses
# ---------------------------------------------------------------------------


@dataclass
class SaveScenarioQuery:
    """Save or update a named scenario."""

    query_type: QueryType = field(default=QueryType.SAVE_SCENARIO, init=False)
    name: str = ""
    overrides: ScenarioOverrides = field(default_factory=ScenarioOverrides)
    description: str = ""
    notes: str = ""


@dataclass
class ListScenariosQuery:
    """List all saved scenarios."""

    query_type: QueryType = field(default=QueryType.LIST_SCENARIOS, init=False)


@dataclass
class DeleteScenarioQuery:
    """Delete a named scenario."""

    query_type: QueryType = field(default=QueryType.DELETE_SCENARIO, init=False)
    name: str = ""


@dataclass
class RenameScenarioQuery:
    """Rename a saved scenario."""

    query_type: QueryType = field(default=QueryType.RENAME_SCENARIO, init=False)
    old_name: str = ""
    new_name: str = ""


@dataclass
class CompareNamedScenariosQuery:
    """Compare two named scenarios (or baseline vs named).

    mode: "cashflow" (default) or "funding"
    """

    query_type: QueryType = field(default=QueryType.COMPARE_NAMED, init=False)
    scenario_a: str = "baseline"
    scenario_b: str = ""
    mode: str = "cashflow"  # "cashflow" or "funding"
    shipment_id: int | None = None  # for funding mode


# ---------------------------------------------------------------------------
# Report lifecycle query dataclasses
# ---------------------------------------------------------------------------


@dataclass
class SaveReportQuery:
    """Save a query result as a named report.

    Provide EITHER source_query (to execute and save) OR
    pre-computed result + formatted_text (to save directly).
    """

    query_type: QueryType = field(default=QueryType.SAVE_REPORT, init=False)
    name: str = ""
    source_query: object = None     # query to execute and save
    result: object = None           # pre-computed result (skip execution)
    formatted_text: str = ""        # pre-computed text (skip execution)
    description: str = ""
    notes: str = ""


@dataclass
class ListReportsQuery:
    """List all saved reports."""

    query_type: QueryType = field(default=QueryType.LIST_REPORTS, init=False)


@dataclass
class GetReportQuery:
    """Retrieve a saved report by name."""

    query_type: QueryType = field(default=QueryType.GET_REPORT, init=False)
    name: str = ""


@dataclass
class DeleteReportQuery:
    """Delete a saved report."""

    query_type: QueryType = field(default=QueryType.DELETE_REPORT, init=False)
    name: str = ""


@dataclass
class RenameReportQuery:
    """Rename a saved report."""

    query_type: QueryType = field(default=QueryType.RENAME_REPORT, init=False)
    old_name: str = ""
    new_name: str = ""


# ---------------------------------------------------------------------------
# Template lifecycle query dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ListScenarioTemplatesQuery:
    """List all available scenario templates."""

    query_type: QueryType = field(default=QueryType.LIST_TEMPLATES, init=False)


@dataclass
class InspectScenarioTemplateQuery:
    """Inspect a scenario template by name."""

    query_type: QueryType = field(default=QueryType.INSPECT_TEMPLATE, init=False)
    name: str = ""


@dataclass
class CreateScenarioFromTemplateQuery:
    """Create a named scenario from a template.

    Optionally provide extra_overrides to layer on top of the template.
    """

    query_type: QueryType = field(default=QueryType.CREATE_FROM_TEMPLATE, init=False)
    template_name: str = ""
    scenario_name: str = ""
    description: str = ""
    notes: str = ""


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ScenarioResult:
    """Cashflow entries produced under a scenario."""

    query: RunScenarioQuery
    entries_by_shipment: dict[int, list[CashflowEntry]] = field(default_factory=dict)
    total_shipments: int = 0
    total_entries: int = 0


@dataclass
class ScenarioComparisonResult:
    """Baseline vs scenario comparison for one or all shipments."""

    query: CompareScenarioQuery
    comparisons: list[ShipmentScenarioComparison] = field(default_factory=list)
    summary: AggregateScenarioSummary | None = None


@dataclass
class ShipmentExplanation:
    """Annotated cashflow breakdown for one shipment."""

    query: ExplainShipmentQuery
    shipment_id: int = 0
    customer_id: str = ""
    proc_model: str = ""
    entries: list[CashflowEntry] = field(default_factory=list)
    total_outflow: float = 0.0
    total_inflow: float = 0.0
    net_cashflow: float = 0.0


@dataclass
class LineItemExplanation:
    """Provenance detail for a single line item."""

    query: ExplainLineItemQuery
    entry: CashflowEntry | None = None
    found: bool = False


@dataclass
class ScenarioImpactSummary:
    """Aggregate scenario summary with top movers."""

    query: ScenarioSummaryQuery
    summary: AggregateScenarioSummary | None = None


@dataclass
class MostAffectedResult:
    """Ranked shipments by scenario impact."""

    query: MostAffectedShipmentsQuery
    shipments: list[ShipmentScenarioComparison] = field(default_factory=list)


@dataclass
class WorkingCapitalResult:
    """Working capital profile (single shipment or portfolio)."""

    query: WorkingCapitalQuery
    shipment_profile: ShipmentFundingProfile | None = None
    portfolio_summary: PortfolioFundingSummary | None = None


@dataclass
class FundingComparisonResult:
    """Baseline vs scenario funding comparison."""

    query: FundingComparisonQuery
    comparison: FundingComparison | None = None
