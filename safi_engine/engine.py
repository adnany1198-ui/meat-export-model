"""Rules engine — computes cashflow from first principles."""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from safi_engine.config import StrategyConfig
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

    Currently handles the SUPPLIER procurement model:
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
