"""Saved analysis artifacts / reports for the analytical workspace.

A SavedReport is a deterministic snapshot of an analytical query's output.
It stores the source query, the structured result, and the formatted text
so past analyses can be listed, retrieved, and compared later within the
same session.

Report types are descriptive labels derived from the source query type.
All reports share the same SavedReport dataclass — the ``report_type``
field distinguishes them.

Public API (used by AnalyticalWorkspace):
    SavedReport          — immutable snapshot of a query result
    ReportType           — enum of report categories
    SaveReportResult     — result of saving a report
    ListReportsResult    — result of listing reports
    GetReportResult      — result of retrieving a report
    DeleteReportResult   — result of deleting a report
    RenameReportResult   — result of renaming a report
    classify_report()    — derive ReportType from a query object
    format_report_list() — readable listing of saved reports
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from enum import Enum, auto


# ---------------------------------------------------------------------------
# Report type classification
# ---------------------------------------------------------------------------


class ReportType(Enum):
    """Categories of saved reports, derived from the source query type."""

    SCENARIO_COMPARISON = auto()
    NAMED_COMPARISON = auto()
    FUNDING_REPORT = auto()
    WORKING_CAPITAL = auto()
    SHIPMENT_AUDIT = auto()
    LINE_ITEM_AUDIT = auto()
    SCENARIO_SUMMARY = auto()
    MOST_AFFECTED = auto()
    SCENARIO_RUN = auto()

    @property
    def label(self) -> str:
        return _REPORT_LABELS.get(self, self.name)


_REPORT_LABELS = {
    ReportType.SCENARIO_COMPARISON: "Scenario Comparison",
    ReportType.NAMED_COMPARISON: "Named Scenario Comparison",
    ReportType.FUNDING_REPORT: "Funding Comparison",
    ReportType.WORKING_CAPITAL: "Working Capital Profile",
    ReportType.SHIPMENT_AUDIT: "Shipment Audit",
    ReportType.LINE_ITEM_AUDIT: "Line Item Audit",
    ReportType.SCENARIO_SUMMARY: "Scenario Impact Summary",
    ReportType.MOST_AFFECTED: "Most Affected Shipments",
    ReportType.SCENARIO_RUN: "Scenario Run",
}


def classify_report(query) -> ReportType:
    """Derive a ReportType from a query object's query_type attribute."""
    from safi_engine.query_model import QueryType

    mapping = {
        QueryType.COMPARE_SCENARIO: ReportType.SCENARIO_COMPARISON,
        QueryType.COMPARE_NAMED: ReportType.NAMED_COMPARISON,
        QueryType.FUNDING_COMPARISON: ReportType.FUNDING_REPORT,
        QueryType.WORKING_CAPITAL: ReportType.WORKING_CAPITAL,
        QueryType.EXPLAIN_SHIPMENT: ReportType.SHIPMENT_AUDIT,
        QueryType.EXPLAIN_LINE_ITEM: ReportType.LINE_ITEM_AUDIT,
        QueryType.SCENARIO_SUMMARY: ReportType.SCENARIO_SUMMARY,
        QueryType.MOST_AFFECTED: ReportType.MOST_AFFECTED,
        QueryType.RUN_SCENARIO: ReportType.SCENARIO_RUN,
    }
    qt = getattr(query, "query_type", None)
    if qt in mapping:
        return mapping[qt]
    return ReportType.SCENARIO_RUN


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class SavedReport:
    """Immutable snapshot of an analytical query's output.

    Fields:
        name:           User-chosen identifier
        report_type:    Category derived from source query
        source_query:   The query object that produced this report
        result:         Structured result dataclass from the query
        formatted_text: Human-readable text snapshot
        created_at:     Timestamp when saved
        description:    Optional user description
        notes:          Optional user notes
    """

    name: str
    report_type: ReportType
    source_query: object
    result: object
    formatted_text: str
    created_at: datetime.datetime = field(default_factory=datetime.datetime.now)
    description: str = ""
    notes: str = ""


# ---------------------------------------------------------------------------
# Operation result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class SaveReportResult:
    name: str
    created: bool  # True if new, False if updated
    report: SavedReport | None = None


@dataclass
class ListReportsResult:
    reports: list[SavedReport] = field(default_factory=list)


@dataclass
class GetReportResult:
    name: str
    found: bool
    report: SavedReport | None = None


@dataclass
class DeleteReportResult:
    name: str
    deleted: bool


@dataclass
class RenameReportResult:
    old_name: str
    new_name: str
    renamed: bool


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def format_save_report(result: SaveReportResult) -> str:
    verb = "Saved" if result.created else "Updated"
    rpt = result.report
    lines = [f"{verb} report '{result.name}'."]
    if rpt:
        lines.append(f"  Type: {rpt.report_type.label}")
        if rpt.description:
            lines.append(f"  Description: {rpt.description}")
        if rpt.notes:
            lines.append(f"  Notes: {rpt.notes}")
    return "\n".join(lines)


def format_report_list(result: ListReportsResult) -> str:
    if not result.reports:
        return "No saved reports."
    lines = [f"Available reports ({len(result.reports)}):"]
    for rpt in result.reports:
        desc = f" — {rpt.description}" if rpt.description else ""
        lines.append(f"  - {rpt.name} [{rpt.report_type.label}]{desc}")
    return "\n".join(lines)


def format_get_report(result: GetReportResult) -> str:
    if not result.found or result.report is None:
        return f"Report '{result.name}' not found."
    rpt = result.report
    lines = [
        "=" * 72,
        f"REPORT: {rpt.name}",
        f"  Type:        {rpt.report_type.label}",
        f"  Created:     {rpt.created_at:%Y-%m-%d %H:%M:%S}",
    ]
    if rpt.description:
        lines.append(f"  Description: {rpt.description}")
    if rpt.notes:
        lines.append(f"  Notes:       {rpt.notes}")
    lines.append("=" * 72)
    lines.append(rpt.formatted_text)
    return "\n".join(lines)


def format_delete_report(result: DeleteReportResult) -> str:
    if result.deleted:
        return f"Deleted report '{result.name}'."
    return f"Report '{result.name}' not found."


def format_rename_report(result: RenameReportResult) -> str:
    if result.renamed:
        return f"Renamed report '{result.old_name}' to '{result.new_name}'."
    return f"Could not rename report '{result.old_name}' to '{result.new_name}'."
