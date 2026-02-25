"""Data structure for a single shipment cycle from Cycle Detail."""

from __future__ import annotations

import datetime
from dataclasses import dataclass


@dataclass
class ShipmentCycle:
    """One row from the Cycle Detail sheet.

    Dates are stored as ``datetime.date``; weights in kg; durations in days.
    """

    proc_model: str  # "SUPPLIER" or "INTERNAL"
    customer_id: str  # e.g. "A", "B", "C"
    shipment_number: int
    cash_date: datetime.date
    slaughter_date: datetime.date
    send_date: datetime.date  # KSA_SEND_DATE
    receive_date: datetime.date  # PK_RECEIVE_DATE
    pay_days: int
    weight_kg_net: float
