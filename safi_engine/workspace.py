"""Persistent analytical workspace with named scenario and report management.

The AnalyticalWorkspace holds baseline context (cycles, config, outflow_config),
a dictionary of named scenarios, and a dictionary of saved reports (analysis
artifacts).  Its execute() method resolves scenario names to ScenarioOverrides,
dispatches queries, and handles report lifecycle operations.

Public API:
    AnalyticalWorkspace(ctx)       — create workspace from a QueryContext
    workspace.execute(query)       — dispatch any query (lifecycle or analytical)
    workspace.save_scenario(...)   — imperative save scenario
    workspace.get_scenario(...)    — imperative retrieve scenario
    workspace.list_scenarios()     — imperative list scenarios
    workspace.delete_scenario(...) — imperative delete scenario
    workspace.rename_scenario(...) — imperative rename scenario
    workspace.save_report(...)     — imperative save report
    workspace.get_report(...)      — imperative retrieve report
    workspace.list_reports()       — imperative list reports
    workspace.delete_report(...)   — imperative delete report
    workspace.rename_report(...)   — imperative rename report

Dataclasses:
    NamedScenario                  — scenario with name, overrides, metadata
    SaveScenarioResult             — result of saving a scenario
    ListScenariosResult            — result of listing scenarios
    DeleteScenarioResult           — result of deleting a scenario
    RenameScenarioResult           — result of renaming a scenario
    NamedComparisonResult          — result of comparing two named scenarios
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field

from safi_engine.config import ScenarioOverrides
from safi_engine.query_model import (
    CompareNamedScenariosQuery,
    CompareScenarioQuery,
    DeleteReportQuery,
    DeleteScenarioQuery,
    ExplainLineItemQuery,
    ExplainShipmentQuery,
    FundingComparisonQuery,
    GetReportQuery,
    ListReportsQuery,
    ListScenariosQuery,
    MostAffectedShipmentsQuery,
    QueryType,
    RenameReportQuery,
    RenameScenarioQuery,
    RunScenarioQuery,
    SaveReportQuery,
    SaveScenarioQuery,
    ScenarioSummaryQuery,
    WorkingCapitalQuery,
)
from safi_engine.workspace_reports import (
    DeleteReportResult,
    GetReportResult,
    ListReportsResult,
    RenameReportResult,
    SavedReport,
    SaveReportResult,
    classify_report,
    format_delete_report,
    format_get_report,
    format_rename_report,
    format_report_list,
    format_save_report,
)
from safi_engine.query_runner import QueryContext, execute as _execute_query
from safi_engine.scenario_analysis import (
    compare_all_shipments,
    format_aggregate_summary,
    scenario_summary,
)
from safi_engine.working_capital import (
    compare_funding_profiles,
    format_funding_comparison,
)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class NamedScenario:
    """A reusable scenario with name and metadata."""

    name: str
    overrides: ScenarioOverrides
    description: str = ""
    created_at: datetime.datetime = field(default_factory=datetime.datetime.now)
    notes: str = ""


@dataclass
class SaveScenarioResult:
    name: str
    created: bool       # True if new, False if updated
    scenario: NamedScenario | None = None


@dataclass
class ListScenariosResult:
    scenarios: list[NamedScenario] = field(default_factory=list)


@dataclass
class DeleteScenarioResult:
    name: str
    deleted: bool


@dataclass
class RenameScenarioResult:
    old_name: str
    new_name: str
    renamed: bool


@dataclass
class NamedComparisonResult:
    """Result of comparing two named scenarios (or baseline vs named)."""

    scenario_a_name: str
    scenario_b_name: str
    scenario_a_overrides: ScenarioOverrides
    scenario_b_overrides: ScenarioOverrides
    comparison_text: str = ""


# ---------------------------------------------------------------------------
# Workspace
# ---------------------------------------------------------------------------


class AnalyticalWorkspace:
    """Session-scoped analytical workspace with named scenario management.

    Wraps QueryContext and adds a scenario registry so queries can
    reference scenarios by name instead of passing inline overrides.
    """

    BASELINE = "baseline"

    def __init__(self, ctx: QueryContext) -> None:
        self.ctx = ctx
        self._scenarios: dict[str, NamedScenario] = {}
        self._reports: dict[str, SavedReport] = {}

    # -- Imperative scenario management ------------------------------------

    def save_scenario(
        self,
        name: str,
        overrides: ScenarioOverrides,
        description: str = "",
        notes: str = "",
    ) -> SaveScenarioResult:
        """Save or update a named scenario."""
        if name == self.BASELINE:
            raise ValueError("Cannot overwrite the reserved name 'baseline'.")
        created = name not in self._scenarios
        sc = NamedScenario(
            name=name,
            overrides=overrides,
            description=description,
            notes=notes,
        )
        self._scenarios[name] = sc
        return SaveScenarioResult(name=name, created=created, scenario=sc)

    def get_scenario(self, name: str) -> NamedScenario | None:
        """Retrieve a named scenario, or None if not found."""
        return self._scenarios.get(name)

    def list_scenarios(self) -> list[NamedScenario]:
        """Return all saved scenarios in insertion order."""
        return list(self._scenarios.values())

    def delete_scenario(self, name: str) -> DeleteScenarioResult:
        """Delete a named scenario. Returns whether it existed."""
        deleted = name in self._scenarios
        self._scenarios.pop(name, None)
        return DeleteScenarioResult(name=name, deleted=deleted)

    def rename_scenario(self, old_name: str, new_name: str) -> RenameScenarioResult:
        """Rename a scenario. Fails if old doesn't exist or new conflicts."""
        if old_name not in self._scenarios:
            return RenameScenarioResult(old_name=old_name, new_name=new_name, renamed=False)
        if new_name in self._scenarios or new_name == self.BASELINE:
            return RenameScenarioResult(old_name=old_name, new_name=new_name, renamed=False)
        sc = self._scenarios.pop(old_name)
        sc.name = new_name
        self._scenarios[new_name] = sc
        return RenameScenarioResult(old_name=old_name, new_name=new_name, renamed=True)

    def scenario_count(self) -> int:
        return len(self._scenarios)

    # -- Imperative report management --------------------------------------

    def save_report(
        self,
        name: str,
        source_query: object,
        result: object,
        formatted_text: str,
        description: str = "",
        notes: str = "",
    ) -> SaveReportResult:
        """Save or update a named report artifact."""
        created = name not in self._reports
        rpt = SavedReport(
            name=name,
            report_type=classify_report(source_query),
            source_query=source_query,
            result=result,
            formatted_text=formatted_text,
            description=description,
            notes=notes,
        )
        self._reports[name] = rpt
        return SaveReportResult(name=name, created=created, report=rpt)

    def get_report(self, name: str) -> GetReportResult:
        """Retrieve a saved report by name."""
        rpt = self._reports.get(name)
        return GetReportResult(name=name, found=rpt is not None, report=rpt)

    def list_reports(self) -> list[SavedReport]:
        """Return all saved reports in insertion order."""
        return list(self._reports.values())

    def delete_report(self, name: str) -> DeleteReportResult:
        """Delete a saved report. Returns whether it existed."""
        deleted = name in self._reports
        self._reports.pop(name, None)
        return DeleteReportResult(name=name, deleted=deleted)

    def rename_report(self, old_name: str, new_name: str) -> RenameReportResult:
        """Rename a report. Fails if old doesn't exist or new conflicts."""
        if old_name not in self._reports:
            return RenameReportResult(old_name=old_name, new_name=new_name, renamed=False)
        if new_name in self._reports:
            return RenameReportResult(old_name=old_name, new_name=new_name, renamed=False)
        rpt = self._reports.pop(old_name)
        rpt.name = new_name
        self._reports[new_name] = rpt
        return RenameReportResult(old_name=old_name, new_name=new_name, renamed=True)

    def report_count(self) -> int:
        return len(self._reports)

    # -- Resolve scenario name → overrides ---------------------------------

    def _resolve_overrides(
        self,
        scenario_name: str | None,
        inline_overrides: ScenarioOverrides | None,
    ) -> ScenarioOverrides:
        """Resolve a scenario_name to ScenarioOverrides.

        Priority: scenario_name > inline_overrides > empty overrides.
        """
        if scenario_name is not None:
            if scenario_name == self.BASELINE:
                return ScenarioOverrides()
            sc = self._scenarios.get(scenario_name)
            if sc is None:
                raise KeyError(f"Scenario '{scenario_name}' not found.")
            return sc.overrides
        if inline_overrides is not None:
            return inline_overrides
        return ScenarioOverrides()

    # -- Query dispatch ----------------------------------------------------

    def execute(self, query) -> tuple:
        """Dispatch a query, resolving named scenarios first.

        Returns (result, formatted_text).
        """
        # Scenario lifecycle queries
        if isinstance(query, SaveScenarioQuery):
            return self._handle_save(query)
        if isinstance(query, ListScenariosQuery):
            return self._handle_list(query)
        if isinstance(query, DeleteScenarioQuery):
            return self._handle_delete(query)
        if isinstance(query, RenameScenarioQuery):
            return self._handle_rename(query)
        if isinstance(query, CompareNamedScenariosQuery):
            return self._handle_compare_named(query)

        # Report lifecycle queries
        if isinstance(query, SaveReportQuery):
            return self._handle_save_report(query)
        if isinstance(query, ListReportsQuery):
            return self._handle_list_reports(query)
        if isinstance(query, GetReportQuery):
            return self._handle_get_report(query)
        if isinstance(query, DeleteReportQuery):
            return self._handle_delete_report(query)
        if isinstance(query, RenameReportQuery):
            return self._handle_rename_report(query)

        # Analytical queries — resolve scenario_name, then delegate
        resolved_query = self._resolve_query(query)
        return _execute_query(resolved_query, self.ctx)

    # -- Lifecycle handlers ------------------------------------------------

    def _handle_save(self, query: SaveScenarioQuery) -> tuple[SaveScenarioResult, str]:
        try:
            result = self.save_scenario(
                query.name, query.overrides, query.description, query.notes,
            )
        except ValueError as e:
            return SaveScenarioResult(name=query.name, created=False), str(e)
        verb = "Saved" if result.created else "Updated"
        text = _format_save(result, verb)
        return result, text

    def _handle_list(self, query: ListScenariosQuery) -> tuple[ListScenariosResult, str]:
        scenarios = self.list_scenarios()
        result = ListScenariosResult(scenarios=scenarios)
        text = _format_list(result)
        return result, text

    def _handle_delete(self, query: DeleteScenarioQuery) -> tuple[DeleteScenarioResult, str]:
        result = self.delete_scenario(query.name)
        text = _format_delete(result)
        return result, text

    def _handle_rename(self, query: RenameScenarioQuery) -> tuple[RenameScenarioResult, str]:
        result = self.rename_scenario(query.old_name, query.new_name)
        text = _format_rename(result)
        return result, text

    # -- Report lifecycle handlers -------------------------------------------

    def _handle_save_report(
        self, query: SaveReportQuery,
    ) -> tuple[SaveReportResult, str]:
        # If source_query is provided, execute it first to get result + text
        if query.source_query is not None and query.result is None:
            result, text = self.execute(query.source_query)
            save_result = self.save_report(
                query.name, query.source_query, result, text,
                query.description, query.notes,
            )
        else:
            save_result = self.save_report(
                query.name, query.source_query, query.result,
                query.formatted_text, query.description, query.notes,
            )
        return save_result, format_save_report(save_result)

    def _handle_list_reports(
        self, query: ListReportsQuery,
    ) -> tuple[ListReportsResult, str]:
        reports = self.list_reports()
        result = ListReportsResult(reports=reports)
        return result, format_report_list(result)

    def _handle_get_report(
        self, query: GetReportQuery,
    ) -> tuple[GetReportResult, str]:
        result = self.get_report(query.name)
        return result, format_get_report(result)

    def _handle_delete_report(
        self, query: DeleteReportQuery,
    ) -> tuple[DeleteReportResult, str]:
        result = self.delete_report(query.name)
        return result, format_delete_report(result)

    def _handle_rename_report(
        self, query: RenameReportQuery,
    ) -> tuple[RenameReportResult, str]:
        result = self.rename_report(query.old_name, query.new_name)
        return result, format_rename_report(result)

    # -- Named scenario comparison handler ---------------------------------

    def _handle_compare_named(
        self, query: CompareNamedScenariosQuery,
    ) -> tuple[NamedComparisonResult, str]:
        try:
            ov_a = self._resolve_overrides(query.scenario_a, None)
            ov_b = self._resolve_overrides(query.scenario_b, None)
        except KeyError as e:
            return NamedComparisonResult(
                scenario_a_name=query.scenario_a,
                scenario_b_name=query.scenario_b,
                scenario_a_overrides=ScenarioOverrides(),
                scenario_b_overrides=ScenarioOverrides(),
            ), str(e)

        # Compute scenario A cashflows as the "baseline" and scenario B as the "scenario"
        # by running the engine under both sets of overrides and comparing
        ov_a_or_none = ov_a if _has_overrides(ov_a) else None
        ov_b_or_none = ov_b if _has_overrides(ov_b) else None

        if query.mode == "funding":
            comp = _compare_funding_named(
                self.ctx, ov_a_or_none, ov_b_or_none, query.shipment_id,
            )
            text_body = format_funding_comparison(comp)
        else:
            text_body = _compare_scenario_named(
                self.ctx, ov_a, ov_b,
            )

        header = f"Comparing '{query.scenario_a}' vs '{query.scenario_b}'"
        text = f"{header}\n{text_body}"

        return NamedComparisonResult(
            scenario_a_name=query.scenario_a,
            scenario_b_name=query.scenario_b,
            scenario_a_overrides=ov_a,
            scenario_b_overrides=ov_b,
            comparison_text=text,
        ), text

    # -- Scenario name resolution for analytical queries --------------------

    def _resolve_query(self, query):
        """Return a copy of the query with scenario_name resolved to overrides."""
        scenario_name = getattr(query, "scenario_name", None)
        if scenario_name is None:
            return query

        overrides = self._resolve_overrides(scenario_name, None)

        # Queries that use 'overrides' field
        if isinstance(query, (
            RunScenarioQuery, CompareScenarioQuery, ScenarioSummaryQuery,
            MostAffectedShipmentsQuery, FundingComparisonQuery,
        )):
            return _replace(query, overrides=overrides)

        # Queries that use optional 'overrides' field
        if isinstance(query, (ExplainShipmentQuery, ExplainLineItemQuery, WorkingCapitalQuery)):
            return _replace(query, overrides=overrides)

        return query


# ---------------------------------------------------------------------------
# Internal helpers
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


def _replace(query, **kwargs):
    """Shallow copy a dataclass with field replacements."""
    from dataclasses import fields as dc_fields
    vals = {f.name: getattr(query, f.name) for f in dc_fields(query) if f.init}
    vals.update(kwargs)
    return type(query)(**vals)


def _compare_scenario_named(
    ctx: QueryContext,
    ov_a: ScenarioOverrides,
    ov_b: ScenarioOverrides,
) -> str:
    """Produce a text comparison of two scenario overrides across all shipments.

    Runs the engine twice — once under ov_a (treated as baseline) and once
    under ov_b — then summarises the delta.
    """
    from safi_engine.engine import compute_full_shipment_cashflow

    net_a = 0.0
    net_b = 0.0
    ov_a_or_none = ov_a if _has_overrides(ov_a) else None
    ov_b_or_none = ov_b if _has_overrides(ov_b) else None

    for cycle in ctx.cycles:
        entries_a = compute_full_shipment_cashflow(
            cycle, ctx.config, ctx.outflow_config, ov_a_or_none,
        )
        entries_b = compute_full_shipment_cashflow(
            cycle, ctx.config, ctx.outflow_config, ov_b_or_none,
        )
        net_a += sum(
            e.amount_pkr if e.direction == "inflow" else -e.amount_pkr
            for e in entries_a
        )
        net_b += sum(
            e.amount_pkr if e.direction == "inflow" else -e.amount_pkr
            for e in entries_b
        )

    delta = net_b - net_a
    lines = [
        "=" * 60,
        "NAMED SCENARIO COMPARISON",
        "=" * 60,
        f"  Shipments analysed: {len(ctx.cycles)}",
        f"  {'Metric':25s} {'Scenario A':>16s} {'Scenario B':>16s} {'Delta':>16s}",
        f"  {'-' * 65}",
        f"  {'Net Cashflow':25s} {net_a:>16,.0f} {net_b:>16,.0f} {delta:>+16,.0f}",
        "=" * 60,
    ]
    return "\n".join(lines)


def _compare_funding_named(ctx, ov_a, ov_b, shipment_id=None):
    """Build a FundingComparison treating ov_a as baseline, ov_b as scenario.

    Uses the working_capital module's compare_funding_profiles, but we
    need to run each side independently since that function always treats
    None as baseline.
    """
    from safi_engine.working_capital import (
        portfolio_funding_summary,
        shipment_funding_profile,
        FundingComparison,
    )

    if shipment_id is not None:
        cycle = next((c for c in ctx.cycles if c.shipment_number == shipment_id), None)
        if cycle is None:
            raise KeyError(f"Shipment {shipment_id} not found.")
        base = shipment_funding_profile(cycle, ctx.config, ctx.outflow_config, ov_a)
        scen = shipment_funding_profile(cycle, ctx.config, ctx.outflow_config, ov_b)
    else:
        base = portfolio_funding_summary(ctx.cycles, ctx.config, ctx.outflow_config, ov_a)
        scen = portfolio_funding_summary(ctx.cycles, ctx.config, ctx.outflow_config, ov_b)

    return FundingComparison(
        baseline=base,
        scenario=scen,
        peak_deficit_delta=scen.peak_deficit - base.peak_deficit,
        peak_surplus_delta=scen.peak_surplus - base.peak_surplus,
        net_cashflow_delta=scen.net_cashflow - base.net_cashflow,
        negative_days_delta=scen.negative_cash_days - base.negative_cash_days,
    )


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _format_save(result: SaveScenarioResult, verb: str) -> str:
    sc = result.scenario
    lines = [f"{verb} scenario '{result.name}'."]
    if sc and sc.description:
        lines.append(f"  Description: {sc.description}")
    if sc and sc.notes:
        lines.append(f"  Notes: {sc.notes}")
    ov = sc.overrides if sc else None
    if ov:
        parts = _describe_overrides(ov)
        if parts:
            lines.append("  Overrides:")
            for p in parts:
                lines.append(f"    - {p}")
    return "\n".join(lines)


def _format_list(result: ListScenariosResult) -> str:
    if not result.scenarios:
        return "No saved scenarios."
    lines = [f"Available scenarios ({len(result.scenarios)}):"]
    for sc in result.scenarios:
        desc = f" — {sc.description}" if sc.description else ""
        lines.append(f"  - {sc.name}{desc}")
    return "\n".join(lines)


def _format_delete(result: DeleteScenarioResult) -> str:
    if result.deleted:
        return f"Deleted scenario '{result.name}'."
    return f"Scenario '{result.name}' not found."


def _format_rename(result: RenameScenarioResult) -> str:
    if result.renamed:
        return f"Renamed scenario '{result.old_name}' to '{result.new_name}'."
    return f"Could not rename '{result.old_name}' to '{result.new_name}'."


def _describe_overrides(ov: ScenarioOverrides) -> list[str]:
    desc: list[str] = []
    if ov.usd_to_pkr is not None:
        desc.append(f"usd_to_pkr = {ov.usd_to_pkr}")
    if ov.partha_rates is not None:
        desc.append(f"partha_rates = {ov.partha_rates}")
    if ov.outflow_rate_overrides is not None:
        desc.append(f"outflow_rate_overrides = {ov.outflow_rate_overrides}")
    if ov.pricing_tiers is not None:
        desc.append(f"pricing_tiers overridden ({len(ov.pricing_tiers)} tiers)")
    if ov.customer_credit_days is not None:
        desc.append(f"customer_credit_days overridden")
    if ov.proc_model is not None:
        desc.append(f"proc_model = {ov.proc_model}")
    return desc
