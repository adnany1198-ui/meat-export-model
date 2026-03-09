"""Data structures for Strategy Control Panel parameters."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MonthlyTonnage:
    """One row from Section 1: Monthly Tonnage Targets."""

    month: str  # e.g. "Jan-2026"
    target_tonnes: float
    active_customers: int
    avg_tonnes_per_customer: float


@dataclass
class PricingTier:
    """One row from Section 2: Pricing Strategy."""

    credit_days_min: int  # lower bound of credit-day bucket
    credit_days_max: int  # upper bound of credit-day bucket
    price_usd_per_kg: float


@dataclass
class CreditDays:
    """One row from Section 4: Credit Terms Evolution."""

    month: str
    min_days: float
    max_days: float
    avg_days: float


@dataclass
class StrategyConfig:
    """All Strategy Control Panel parameters needed by the rules engine."""

    monthly_tonnage: list[MonthlyTonnage] = field(default_factory=list)
    pricing_tiers: list[PricingTier] = field(default_factory=list)
    usd_to_pkr: float = 0.0
    customer_credit_days: list[CreditDays] = field(default_factory=list)
    supplier_credit_days: list[CreditDays] = field(default_factory=list)
    # Procurement cost per kg by model, from control_raw OUTFLOWS section
    # e.g. {"SUPPLIER": 1110, "INTERNAL": 1000}
    partha_rates: dict[str, float] = field(default_factory=dict)


@dataclass
class ScenarioOverrides:
    """Optional overrides for running counterfactual scenarios.

    Any field left as None means "use the baseline value from StrategyConfig".
    Only non-None fields are applied, and provenance metadata records which
    values were overridden.

    Fields:
        usd_to_pkr:              Override the FX rate
        pricing_tiers:           Override all sale pricing tiers
        customer_credit_days:    Override customer credit terms
        partha_rates:            Override procurement rates by model
        outflow_rate_overrides:  Override specific outflow rates by cost code
                                 e.g. {"Freight": 250, "Chilling": 60}
        proc_model:              Override the procurement model for a shipment
                                 e.g. "INTERNAL" to simulate switching a
                                 SUPPLIER shipment to internal procurement
    """

    usd_to_pkr: float | None = None
    pricing_tiers: list[PricingTier] | None = None
    customer_credit_days: list[CreditDays] | None = None
    partha_rates: dict[str, float] | None = None
    outflow_rate_overrides: dict[str, float] | None = None
    proc_model: str | None = None
