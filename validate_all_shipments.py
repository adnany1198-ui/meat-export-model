"""Validate the rules engine against every shipment in the spreadsheet.

This is a thin validation layer.  All business logic lives in safi_engine/.
This script loads fixtures, calls the engine, and compares results.

Usage:
    python validate_all_shipments.py
"""

from __future__ import annotations

import datetime
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from safi_engine.config import CreditDays, PricingTier, StrategyConfig
from safi_engine.cycle import ShipmentCycle
from safi_engine.engine import LedgerEntry, compute_full_shipment_cashflow

FIXTURES = Path(__file__).resolve().parent / "tests" / "fixtures"

# ---------------------------------------------------------------------------
# Fixture loaders
# ---------------------------------------------------------------------------


def load_cycle_details() -> list[ShipmentCycle]:
    """Parse cycle_detail_raw.json into a list of ShipmentCycle objects."""
    raw = json.loads((FIXTURES / "cycle_detail_raw.json").read_text())
    cycles: list[ShipmentCycle] = []
    for row in raw[4:]:
        # Skip rows without a shipment number
        if not row[2]:
            continue
        cycles.append(ShipmentCycle(
            proc_model=row[0].strip(),
            customer_id=row[1].strip(),
            shipment_number=int(row[2]),
            cash_date=_parse_ddmmyyyy(row[8]),
            slaughter_date=_parse_ddmmyyyy(row[13]),
            slaughter_end_date=_parse_ddmmyyyy(row[17]),
            send_date=_parse_ddmmyyyy(row[21]),
            receive_date=_parse_ddmmyyyy(row[23]),
            pay_days=int(float(row[19])) if row[19] else 0,
            weight_kg_net=float(row[28]) if row[28] else 0.0,
        ))
    return cycles


def load_expected_cashflows() -> dict[int, list[dict]]:
    """Load cashflow_master.json grouped by shipment number.

    Returns {shipment_number: [row_dict, ...]}.  Rows with blank shipment
    (Admin/Bank monthly items) are excluded.
    """
    rows = json.loads((FIXTURES / "cashflow_master.json").read_text())
    by_ship: dict[int, list[dict]] = {}
    for r in rows:
        ship_str = r.get("Shipment", "").strip()
        if not ship_str:
            continue
        ship_num = int(ship_str)
        by_ship.setdefault(ship_num, []).append(r)
    return by_ship


def load_outflow_config() -> list[dict]:
    return json.loads((FIXTURES / "outflow_config.json").read_text())


def load_strategy_config() -> StrategyConfig:
    """Build a fully-populated StrategyConfig from strategy_control_raw.json.

    Parses:
      - USD/PKR rate (Section 2, row 26)
      - Pricing tiers (Section 2, rows 21-24)
      - Customer credit terms (Section 4, rows 48-59)
      - Partha rates (hardcoded — source not yet traced to a fixture)
    """
    raw = json.loads((FIXTURES / "strategy_control_raw.json").read_text())

    # USD_to_PKR is at row 26, col 1
    usd_to_pkr = float(raw[26][1])

    # Pricing tiers: rows 21-24 (Section 2)
    pricing_tiers: list[PricingTier] = []
    for row in raw[21:25]:
        if row[0] and row[1]:
            parts = row[0].split("-")
            pricing_tiers.append(PricingTier(
                credit_days_min=int(parts[0]),
                credit_days_max=int(parts[1]),
                price_usd_per_kg=float(row[1]),
            ))

    # Customer credit terms: rows 48-59 (Section 4)
    customer_credit_days: list[CreditDays] = []
    for row in raw[48:60]:
        if row[0] and row[3]:
            customer_credit_days.append(CreditDays(
                month=row[0],
                min_days=float(row[1]) if row[1] else 0.0,
                max_days=float(row[2]) if row[2] else 0.0,
                avg_days=float(row[3]),
            ))

    return StrategyConfig(
        usd_to_pkr=usd_to_pkr,
        pricing_tiers=pricing_tiers,
        customer_credit_days=customer_credit_days,
        # NOTE: partha rates are hardcoded here — source in spreadsheet not
        # yet identified.  This is the SINGLE canonical location for these
        # values.  All other code reads them from this StrategyConfig.
        partha_rates={"SUPPLIER": 1110, "INTERNAL": 1000},
    )


def _parse_ddmmyyyy(s: str) -> datetime.date:
    """Parse DD/MM/YYYY date string."""
    if not s:
        return datetime.date(1900, 1, 1)  # sentinel for missing dates
    parts = s.strip().split("/")
    return datetime.date(int(parts[2]), int(parts[1]), int(parts[0]))


# ---------------------------------------------------------------------------
# Comparison logic
# ---------------------------------------------------------------------------

@dataclass
class RowComparison:
    """Comparison of one expected row against a computed entry."""
    item: str
    direction: str
    expected_amount: float
    computed_amount: float | None
    amount_diff: float
    expected_date: datetime.date
    computed_date: datetime.date | None
    date_match: bool
    expected_pay_date: datetime.date
    computed_pay_date: datetime.date | None
    pay_date_match: bool
    status: str  # "MATCH", "AMOUNT_DIFF", "DATE_DIFF", "MISSING"


@dataclass
class ShipmentResult:
    """Validation result for one shipment."""
    shipment_number: int
    customer_id: str
    proc_model: str
    expected_count: int
    computed_count: int
    comparisons: list[RowComparison]
    passed: bool
    error: str | None = None


def compare_shipment(
    cycle: ShipmentCycle,
    expected_rows: list[dict],
    computed_entries: list[LedgerEntry],
) -> ShipmentResult:
    """Compare expected cashflow rows against computed entries."""
    comparisons: list[RowComparison] = []

    # Build lookup of computed entries by (item, direction)
    computed_by_key: dict[tuple[str, str], LedgerEntry] = {}
    for entry in computed_entries:
        # Normalise direction to match fixture format
        direction = "OUT" if entry.direction == "outflow" else "IN"
        key = (entry.cost_type, direction)
        computed_by_key[key] = entry

    all_passed = True
    for row in expected_rows:
        item = row["Item"]
        direction = row["Direction"]
        expected_amount = float(row["Amount_PKR"])
        expected_date = _parse_ddmmyyyy(row["Date"])
        expected_pay_date = _parse_ddmmyyyy(row["Payment_Date_After_Credit"])

        # Map the spreadsheet item name to our engine's cost_type
        engine_item = item
        if item in ("PROCUREMENT_SUPPLIER", "PROCUREMENT_INTERNAL"):
            engine_item = "Partha"

        key = (engine_item, direction)
        entry = computed_by_key.get(key)

        if entry is None:
            comparisons.append(RowComparison(
                item=item, direction=direction,
                expected_amount=expected_amount, computed_amount=None,
                amount_diff=expected_amount,
                expected_date=expected_date, computed_date=None,
                date_match=False,
                expected_pay_date=expected_pay_date, computed_pay_date=None,
                pay_date_match=False,
                status="MISSING",
            ))
            all_passed = False
            continue

        amount_diff = abs(entry.amount_pkr - expected_amount)
        amount_match = amount_diff < 0.02  # tolerance for float rounding
        date_match = entry.event_date == expected_date
        pay_date_match = entry.payment_date == expected_pay_date

        if amount_match and date_match and pay_date_match:
            status = "MATCH"
        elif not amount_match:
            status = "AMOUNT_DIFF"
            all_passed = False
        else:
            status = "DATE_DIFF"
            all_passed = False

        comparisons.append(RowComparison(
            item=item, direction=direction,
            expected_amount=expected_amount,
            computed_amount=entry.amount_pkr,
            amount_diff=amount_diff,
            expected_date=expected_date,
            computed_date=entry.event_date,
            date_match=date_match,
            expected_pay_date=expected_pay_date,
            computed_pay_date=entry.payment_date,
            pay_date_match=pay_date_match,
            status=status,
        ))

    return ShipmentResult(
        shipment_number=cycle.shipment_number,
        customer_id=cycle.customer_id,
        proc_model=cycle.proc_model,
        expected_count=len(expected_rows),
        computed_count=len(computed_entries),
        comparisons=comparisons,
        passed=all_passed,
    )


# ---------------------------------------------------------------------------
# Validation runner
# ---------------------------------------------------------------------------

def validate_all() -> list[ShipmentResult]:
    """Run the engine for every shipment and compare against expected data."""
    cycles = load_cycle_details()
    expected = load_expected_cashflows()
    outflow_config = load_outflow_config()
    config = load_strategy_config()

    results: list[ShipmentResult] = []

    for cycle in cycles:
        ship_num = cycle.shipment_number
        if ship_num not in expected:
            results.append(ShipmentResult(
                shipment_number=ship_num,
                customer_id=cycle.customer_id,
                proc_model=cycle.proc_model,
                expected_count=0,
                computed_count=0,
                comparisons=[],
                passed=False,
                error="No expected data in cashflow_master",
            ))
            continue

        try:
            all_entries = compute_full_shipment_cashflow(
                cycle, config, outflow_config,
            )
            result = compare_shipment(cycle, expected[ship_num], all_entries)
            results.append(result)

        except Exception as exc:
            results.append(ShipmentResult(
                shipment_number=ship_num,
                customer_id=cycle.customer_id,
                proc_model=cycle.proc_model,
                expected_count=len(expected.get(ship_num, [])),
                computed_count=0,
                comparisons=[],
                passed=False,
                error=str(exc),
            ))

    return results


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------

def format_report(results: list[ShipmentResult]) -> str:
    """Format validation results as a human-readable report."""
    lines: list[str] = []

    total = len(results)
    passed = sum(1 for r in results if r.passed)
    failed = total - passed

    lines.append("=" * 72)
    lines.append("VALIDATION REPORT: Engine vs Spreadsheet")
    lines.append("=" * 72)
    lines.append("")
    lines.append("SUMMARY")
    lines.append(f"  Total shipments tested:  {total}")
    lines.append(f"  Passed (exact match):    {passed}")
    lines.append(f"  Failed (mismatches):     {failed}")
    lines.append(f"  Pass rate:               {passed/total*100:.1f}%")
    lines.append("")

    # Failed shipments detail
    failed_results = [r for r in results if not r.passed]
    if failed_results:
        lines.append("-" * 72)
        lines.append("FAILED SHIPMENTS")
        lines.append("-" * 72)

        for r in failed_results:
            lines.append("")
            lines.append(f"  Shipment {r.shipment_number} "
                         f"(Customer {r.customer_id}, {r.proc_model})")

            if r.error:
                lines.append(f"    ERROR: {r.error}")
                continue

            lines.append(f"    Expected rows: {r.expected_count}, "
                         f"Computed rows: {r.computed_count}")

            for c in r.comparisons:
                if c.status == "MATCH":
                    continue
                lines.append(f"    [{c.status}] {c.item} ({c.direction})")
                if c.status == "MISSING":
                    lines.append(f"      Expected: {c.expected_amount:,.2f} PKR "
                                 f"on {c.expected_date}")
                    lines.append(f"      Computed: <not produced by engine>")
                elif c.status == "AMOUNT_DIFF":
                    lines.append(f"      Expected: {c.expected_amount:,.2f} PKR")
                    lines.append(f"      Computed: {c.computed_amount:,.2f} PKR")
                    lines.append(f"      Diff:     {c.amount_diff:,.2f} PKR")
                elif c.status == "DATE_DIFF":
                    if not c.date_match:
                        lines.append(f"      Event date: expected {c.expected_date}, "
                                     f"got {c.computed_date}")
                    if not c.pay_date_match:
                        lines.append(f"      Payment date: expected {c.expected_pay_date}, "
                                     f"got {c.computed_pay_date}")

    # Passed shipments (brief)
    passed_results = [r for r in results if r.passed]
    if passed_results:
        lines.append("")
        lines.append("-" * 72)
        lines.append("PASSED SHIPMENTS")
        lines.append("-" * 72)
        for r in passed_results:
            lines.append(f"  Shipment {r.shipment_number:>3d} "
                         f"(Customer {r.customer_id}, {r.proc_model}) "
                         f"- {r.expected_count} rows matched")

    lines.append("")
    lines.append("=" * 72)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    results = validate_all()
    report = format_report(results)
    print(report)

    # Exit with non-zero status if any failures
    failed = sum(1 for r in results if not r.passed)
    sys.exit(1 if failed else 0)
