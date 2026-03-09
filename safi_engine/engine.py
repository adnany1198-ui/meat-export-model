"""Rules engine — computes cashflow from first principles.

Public API:
    compute_full_shipment_cashflow()  — returns outflows + SALE inflow
    compute_shipment_cashflow()       — returns outflows only (kept for compatibility)
    compute_sale_entry()              — returns the single SALE inflow entry
"""

from __future__ import annotations

import datetime
import math
from dataclasses import dataclass

from safi_engine.config import CreditDays, PricingTier, StrategyConfig
from safi_engine.cycle import ShipmentCycle


@dataclass
class LedgerEntry:
    """One cashflow ledger line produced by the engine."""

    shipment_id: int
    customer_id: str
    cost_type: str
    direction: str  # "outflow" or "inflow"
    amount_pkr: float
    event_date: datetime.date
    payment_date: datetime.date
    source_assumption: str


# ---------------------------------------------------------------------------
# Outflow computation
# ---------------------------------------------------------------------------


def _resolve_event_date(timing: str, cycle: ShipmentCycle) -> datetime.date:
    """Map a TIMING_EVENT string to a concrete date on the cycle."""
    t = timing.strip().upper()
    if t == "CASH_OUT":
        return cycle.cash_date
    if t == "SLAUGHTER_START":
        return cycle.slaughter_date
    if t == "SLAUGHTER_END":
        return cycle.slaughter_end_date
    if t in ("SLAUGHTER_END+1", "SLAUGHTER_END +1"):
        return cycle.slaughter_end_date + datetime.timedelta(days=1)
    raise ValueError(f"Unknown TIMING_EVENT: {timing!r}")


def compute_shipment_cashflow(
    cycle: ShipmentCycle,
    config: StrategyConfig,
    outflow_config: list[dict],
) -> list[LedgerEntry]:
    """Compute all outflow ledger entries for one shipment from first principles.

    Handles both SUPPLIER and INTERNAL procurement models:
      1. Partha (procurement) = partha_rate × weight_kg_net
      2. Each active PER_KG item from outflow_config × weight_kg_net
    """
    entries: list[LedgerEntry] = []
    model_key = cycle.proc_model.strip().upper()

    # --- 1. Procurement (Partha) -------------------------------------------
    partha_rate = config.partha_rates[model_key]
    entries.append(LedgerEntry(
        shipment_id=cycle.shipment_number,
        customer_id=cycle.customer_id,
        cost_type="Partha",
        direction="outflow",
        amount_pkr=partha_rate * cycle.weight_kg_net,
        event_date=cycle.cash_date,
        payment_date=cycle.cash_date,
        source_assumption=f"partha_rate={partha_rate}/kg",
    ))

    # --- 2. Per-kg outflow items from outflow_config -----------------------
    for item in outflow_config:
        # Keys in the fixture have trailing spaces — normalise once.
        code = item.get("COST_CODE", "").strip()
        active = item.get("ACTIVE?", "").strip().upper()
        rate_type = item.get("RATE_TYPE", "").strip().upper()
        applies_to = item.get("APPLIES_TO_PROC_MODEL", "").strip().upper()

        if not code or active != "TRUE":
            continue
        if rate_type != "PER_KG":
            continue  # skip MONTHLY items (Admin, Bank) for per-shipment calc
        if applies_to not in ("ALL", model_key):
            continue

        rate = float(item.get("RATE_PKR ", item.get("RATE_PKR", "0")).strip())
        timing = item.get("TIMING_EVENT", "").strip()
        credit_days = int(
            float(item.get("DEFAULT_CREDIT_DAYS ", item.get("DEFAULT_CREDIT_DAYS", "0")).strip() or "0")
        )

        event_date = _resolve_event_date(timing, cycle)
        payment_date = event_date + datetime.timedelta(days=credit_days)

        entries.append(LedgerEntry(
            shipment_id=cycle.shipment_number,
            customer_id=cycle.customer_id,
            cost_type=code,
            direction="outflow",
            amount_pkr=rate * cycle.weight_kg_net,
            event_date=event_date,
            payment_date=payment_date,
            source_assumption=f"{code}={rate}/kg",
        ))

    return entries


# ---------------------------------------------------------------------------
# SALE (inflow) computation
# ---------------------------------------------------------------------------


def _get_credit_days_for_month(
    receive_date: datetime.date,
    customer_credit_days: list[CreditDays],
) -> CreditDays:
    """Look up the CreditDays entry for the month of receive_date."""
    month_str = receive_date.strftime("%b-%Y")  # e.g. "Jan-2026"
    for cd in customer_credit_days:
        if cd.month == month_str:
            return cd
    raise ValueError(f"No credit terms for month {month_str}")


def _get_price_usd_per_kg(
    avg_days: float,
    pricing_tiers: list[PricingTier],
) -> float:
    """Look up USD/kg price using ceil of avg_days against pricing tiers."""
    lookup_days = math.ceil(avg_days)
    for tier in pricing_tiers:
        if tier.credit_days_min <= lookup_days <= tier.credit_days_max:
            return tier.price_usd_per_kg
    raise ValueError(f"No pricing tier for {lookup_days} credit days (avg={avg_days})")


def compute_sale_entry(
    cycle: ShipmentCycle,
    config: StrategyConfig,
) -> LedgerEntry:
    """Compute the SALE inflow entry for a shipment.

    Uses config.customer_credit_days and config.pricing_tiers to determine:
      - credit_days = floor(avg_days) for the shipment's receive month
      - price_usd   = tier lookup using ceil(avg_days)
      - amount_pkr  = weight × price_usd × usd_to_pkr
    """
    cd = _get_credit_days_for_month(cycle.receive_date, config.customer_credit_days)

    credit_days = int(cd.avg_days)  # floor for actual payment delay
    price_usd = _get_price_usd_per_kg(cd.avg_days, config.pricing_tiers)
    amount_pkr = cycle.weight_kg_net * price_usd * config.usd_to_pkr

    return LedgerEntry(
        shipment_id=cycle.shipment_number,
        customer_id=cycle.customer_id,
        cost_type="SALE",
        direction="inflow",
        amount_pkr=amount_pkr,
        event_date=cycle.receive_date,
        payment_date=cycle.receive_date + datetime.timedelta(days=credit_days),
        source_assumption=f"price={price_usd}USD/kg, credit={credit_days}d",
    )


# ---------------------------------------------------------------------------
# Unified entry point
# ---------------------------------------------------------------------------


def compute_full_shipment_cashflow(
    cycle: ShipmentCycle,
    config: StrategyConfig,
    outflow_config: list[dict],
) -> list[LedgerEntry]:
    """Compute the complete cashflow for one shipment: outflows + SALE inflow.

    Returns a list of LedgerEntry objects:
      - 15 outflow entries (Partha + 14 per-kg cost items)
      - 1 SALE inflow entry
    """
    entries = compute_shipment_cashflow(cycle, config, outflow_config)
    entries.append(compute_sale_entry(cycle, config))
    return entries
