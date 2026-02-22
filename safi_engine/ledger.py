"""Ledger builder — converts a shipment fixture into flat ledger entries."""

from datetime import datetime


def _parse_date(iso_str):
    """Parse an ISO 8601 date string to a datetime object."""
    return datetime.fromisoformat(iso_str.replace("Z", "+00:00"))


def _credit_days(event_date_str, payment_date_str):
    """Return the number of calendar days between event and payment dates."""
    event = _parse_date(event_date_str)
    payment = _parse_date(payment_date_str)
    return (payment - event).days


def build_ledger(fixture):
    """Build a list of ledger entry dicts from a shipment fixture.

    Each cashflow row becomes one ledger entry with:
        shipment_id, customer_id, cost_type, direction, amount_pkr,
        event_date, payment_date, credit_days, source_sheet, source_assumption
    """
    cycle = fixture["cycle"]
    strategy = fixture["strategy"]
    entries = []

    for row in fixture["cashflow"]:
        entries.append({
            "shipment_id": row["Shipment"],
            "customer_id": row["Customer_ID"],
            "cost_type": row["Item"],
            "direction": row["Direction"],
            "amount_pkr": row["Amount_PKR"],
            "event_date": row["Date"],
            "payment_date": row["Payment_Date_After_Credit"],
            "credit_days": _credit_days(row["Date"], row["Payment_Date_After_Credit"]),
            "source_sheet": cycle["PROC_MODEL"],
            "source_assumption": f"usd_to_pkr={strategy['usd_to_pkr']}",
        })

    return entries
