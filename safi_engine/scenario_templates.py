"""Scenario templates — reusable assumption packs for the analytical workspace.

A ScenarioTemplate bundles a name, description, rationale, and a set of
ScenarioOverrides into a reusable building block.  Templates are composed
from low-level AssumptionComponents so that future risk dimensions (buyer
default probability, recovery rate, payment delay risk, etc.) can be added
as new components without redesigning the API.

TemplateLibrary holds a registry of templates and provides listing,
inspection, and scenario-creation helpers.

Public API:
    AssumptionComponent           — low-level reusable override fragment
    ScenarioTemplate              — named template composed from components
    TemplateLibrary               — registry of templates
    BUILT_IN_COMPONENTS           — dict of default assumption components
    BUILT_IN_TEMPLATES            — dict of default template packs
    default_library()             — TemplateLibrary with built-in templates

Dataclasses for query results:
    ListTemplatesResult
    InspectTemplateResult
    CreateScenarioFromTemplateResult
"""

from __future__ import annotations

from dataclasses import dataclass, field

from safi_engine.config import CreditDays, PricingTier, ScenarioOverrides


# ---------------------------------------------------------------------------
# Core dataclasses
# ---------------------------------------------------------------------------


@dataclass
class AssumptionComponent:
    """A low-level reusable assumption fragment.

    Each component contributes a partial ScenarioOverrides.  Templates
    are composed from one or more components, merging their overrides.

    The ``dimension`` field groups components into categories (e.g.
    "procurement", "freight", "pricing", "credit_terms") so that future
    risk dimensions can be added and queried by category.
    """

    name: str
    dimension: str  # e.g. "procurement", "freight", "pricing", "credit_terms"
    description: str
    overrides: ScenarioOverrides = field(default_factory=ScenarioOverrides)


@dataclass
class ScenarioTemplate:
    """A named, composable scenario template / assumption pack.

    Built from one or more AssumptionComponents.  The ``merged_overrides``
    property returns the union of all component overrides.
    """

    name: str
    description: str
    rationale: str
    components: list[AssumptionComponent] = field(default_factory=list)
    notes: str = ""

    @property
    def merged_overrides(self) -> ScenarioOverrides:
        """Merge all component overrides into a single ScenarioOverrides."""
        merged = ScenarioOverrides()
        for comp in self.components:
            ov = comp.overrides
            if ov.usd_to_pkr is not None:
                merged.usd_to_pkr = ov.usd_to_pkr
            if ov.partha_rates is not None:
                if merged.partha_rates is None:
                    merged.partha_rates = {}
                merged.partha_rates.update(ov.partha_rates)
            if ov.outflow_rate_overrides is not None:
                if merged.outflow_rate_overrides is None:
                    merged.outflow_rate_overrides = {}
                merged.outflow_rate_overrides.update(ov.outflow_rate_overrides)
            if ov.pricing_tiers is not None:
                merged.pricing_tiers = ov.pricing_tiers
            if ov.customer_credit_days is not None:
                merged.customer_credit_days = ov.customer_credit_days
            if ov.proc_model is not None:
                merged.proc_model = ov.proc_model
        return merged

    @property
    def component_names(self) -> list[str]:
        return [c.name for c in self.components]

    @property
    def dimensions(self) -> list[str]:
        seen: list[str] = []
        for c in self.components:
            if c.dimension not in seen:
                seen.append(c.dimension)
        return seen


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ListTemplatesResult:
    templates: list[ScenarioTemplate] = field(default_factory=list)


@dataclass
class InspectTemplateResult:
    name: str
    found: bool
    template: ScenarioTemplate | None = None


@dataclass
class CreateScenarioFromTemplateResult:
    template_name: str
    scenario_name: str
    created: bool
    message: str = ""


# ---------------------------------------------------------------------------
# Built-in assumption components
# ---------------------------------------------------------------------------


# Procurement: partha rates stressed upward (~10% increase)
_PROCUREMENT_COST_UP = AssumptionComponent(
    name="procurement_cost_up",
    dimension="procurement",
    description="Partha procurement rates increase ~10%",
    overrides=ScenarioOverrides(
        partha_rates={"SUPPLIER": 1220, "INTERNAL": 1100},
    ),
)

# Procurement: partha rates favourable (~5% decrease)
_PROCUREMENT_COST_DOWN = AssumptionComponent(
    name="procurement_cost_down",
    dimension="procurement",
    description="Partha procurement rates decrease ~5%",
    overrides=ScenarioOverrides(
        partha_rates={"SUPPLIER": 1055, "INTERNAL": 950},
    ),
)

# Freight: freight rate increase (~15%)
_FREIGHT_STRESS = AssumptionComponent(
    name="freight_stress",
    dimension="freight",
    description="Freight cost increases ~15% (212 → 244 PKR/kg)",
    overrides=ScenarioOverrides(
        outflow_rate_overrides={"Freight": 244.0},
    ),
)

# Freight: freight rate decrease (~10%)
_FREIGHT_FAVOURABLE = AssumptionComponent(
    name="freight_favourable",
    dimension="freight",
    description="Freight cost decreases ~10% (212 → 191 PKR/kg)",
    overrides=ScenarioOverrides(
        outflow_rate_overrides={"Freight": 191.0},
    ),
)

# Pricing pressure: all USD pricing tiers reduced by ~$0.20/kg
# Tiers cover 7–25 credit days to remain compatible with credit_extended/tightened
_PRICING_PRESSURE = AssumptionComponent(
    name="pricing_pressure",
    dimension="pricing",
    description="All USD pricing tiers reduced by $0.20/kg",
    overrides=ScenarioOverrides(
        pricing_tiers=[
            PricingTier(credit_days_min=7, credit_days_max=9, price_usd_per_kg=5.80),
            PricingTier(credit_days_min=10, credit_days_max=12, price_usd_per_kg=5.70),
            PricingTier(credit_days_min=13, credit_days_max=15, price_usd_per_kg=5.60),
            PricingTier(credit_days_min=16, credit_days_max=18, price_usd_per_kg=5.50),
            PricingTier(credit_days_min=19, credit_days_max=22, price_usd_per_kg=5.45),
            PricingTier(credit_days_min=23, credit_days_max=25, price_usd_per_kg=5.40),
        ],
    ),
)

# Pricing improvement: all USD pricing tiers up by $0.15/kg
# Tiers cover 7–25 credit days to remain compatible with credit_extended/tightened
_PRICING_IMPROVEMENT = AssumptionComponent(
    name="pricing_improvement",
    dimension="pricing",
    description="All USD pricing tiers increased by $0.15/kg",
    overrides=ScenarioOverrides(
        pricing_tiers=[
            PricingTier(credit_days_min=7, credit_days_max=9, price_usd_per_kg=6.15),
            PricingTier(credit_days_min=10, credit_days_max=12, price_usd_per_kg=6.05),
            PricingTier(credit_days_min=13, credit_days_max=15, price_usd_per_kg=5.95),
            PricingTier(credit_days_min=16, credit_days_max=18, price_usd_per_kg=5.85),
            PricingTier(credit_days_min=19, credit_days_max=22, price_usd_per_kg=5.80),
            PricingTier(credit_days_min=23, credit_days_max=25, price_usd_per_kg=5.75),
        ],
    ),
)

# Credit terms: customer credit days extended (longer payment)
# All 12 months covered; ~5 days added to baseline avg_days
_CREDIT_EXTENDED = AssumptionComponent(
    name="credit_extended",
    dimension="credit_terms",
    description="Customer credit days extended by ~5 days",
    overrides=ScenarioOverrides(
        customer_credit_days=[
            CreditDays(month="Jan-2026", min_days=20.0, max_days=25.0, avg_days=22.5),
            CreditDays(month="Feb-2026", min_days=20.0, max_days=25.0, avg_days=22.0),
            CreditDays(month="Mar-2026", min_days=20.0, max_days=25.0, avg_days=22.0),
            CreditDays(month="Apr-2026", min_days=17.0, max_days=23.0, avg_days=20.0),
            CreditDays(month="May-2026", min_days=17.0, max_days=23.0, avg_days=19.0),
            CreditDays(month="Jun-2026", min_days=17.0, max_days=23.0, avg_days=19.0),
            CreditDays(month="Jul-2026", min_days=17.0, max_days=23.0, avg_days=18.0),
            CreditDays(month="Aug-2026", min_days=15.0, max_days=20.0, avg_days=17.5),
            CreditDays(month="Sep-2026", min_days=15.0, max_days=20.0, avg_days=17.0),
            CreditDays(month="Oct-2026", min_days=15.0, max_days=20.0, avg_days=16.5),
            CreditDays(month="Nov-2026", min_days=15.0, max_days=20.0, avg_days=16.0),
            CreditDays(month="Dec-2026", min_days=15.0, max_days=20.0, avg_days=16.0),
        ],
    ),
)

# Credit terms: tighter payment terms
# All 12 months covered; ~3-5 days reduced from baseline avg_days
_CREDIT_TIGHTENED = AssumptionComponent(
    name="credit_tightened",
    dimension="credit_terms",
    description="Customer credit days reduced by ~3-5 days",
    overrides=ScenarioOverrides(
        customer_credit_days=[
            CreditDays(month="Jan-2026", min_days=10.0, max_days=15.0, avg_days=12.5),
            CreditDays(month="Feb-2026", min_days=10.0, max_days=15.0, avg_days=12.0),
            CreditDays(month="Mar-2026", min_days=10.0, max_days=15.0, avg_days=12.0),
            CreditDays(month="Apr-2026", min_days=8.0, max_days=13.0, avg_days=10.0),
            CreditDays(month="May-2026", min_days=8.0, max_days=13.0, avg_days=10.0),
            CreditDays(month="Jun-2026", min_days=8.0, max_days=13.0, avg_days=10.0),
            CreditDays(month="Jul-2026", min_days=8.0, max_days=13.0, avg_days=10.0),
            CreditDays(month="Aug-2026", min_days=7.0, max_days=12.0, avg_days=9.0),
            CreditDays(month="Sep-2026", min_days=7.0, max_days=12.0, avg_days=8.0),
            CreditDays(month="Oct-2026", min_days=7.0, max_days=12.0, avg_days=8.0),
            CreditDays(month="Nov-2026", min_days=7.0, max_days=12.0, avg_days=8.0),
            CreditDays(month="Dec-2026", min_days=7.0, max_days=12.0, avg_days=8.0),
        ],
    ),
)

# Operational overhead: chilling + slaughter costs increase
_OPERATIONAL_STRESS = AssumptionComponent(
    name="operational_stress",
    dimension="operations",
    description="Chilling (+10%) and slaughter (+20%) costs increase",
    overrides=ScenarioOverrides(
        outflow_rate_overrides={"Chilling": 60.5, "Slaughter": 6.0},
    ),
)

# Operational efficiency: chilling + slaughter costs decrease
_OPERATIONAL_EFFICIENCY = AssumptionComponent(
    name="operational_efficiency",
    dimension="operations",
    description="Chilling (-5%) and slaughter (-10%) costs decrease",
    overrides=ScenarioOverrides(
        outflow_rate_overrides={"Chilling": 52.25, "Slaughter": 4.5},
    ),
)


BUILT_IN_COMPONENTS: dict[str, AssumptionComponent] = {
    c.name: c for c in [
        _PROCUREMENT_COST_UP,
        _PROCUREMENT_COST_DOWN,
        _FREIGHT_STRESS,
        _FREIGHT_FAVOURABLE,
        _PRICING_PRESSURE,
        _PRICING_IMPROVEMENT,
        _CREDIT_EXTENDED,
        _CREDIT_TIGHTENED,
        _OPERATIONAL_STRESS,
        _OPERATIONAL_EFFICIENCY,
    ]
}


# ---------------------------------------------------------------------------
# Built-in template packs
# ---------------------------------------------------------------------------


BUILT_IN_TEMPLATES: dict[str, ScenarioTemplate] = {}


def _register(t: ScenarioTemplate) -> ScenarioTemplate:
    BUILT_IN_TEMPLATES[t.name] = t
    return t


_register(ScenarioTemplate(
    name="baseline",
    description="No overrides — matches validated baseline cashflows",
    rationale="Reference point for all comparisons",
    components=[],
    notes="Empty overrides; engine uses StrategyConfig defaults.",
))

_register(ScenarioTemplate(
    name="total_upside",
    description="Best-case operational & commercial assumptions",
    rationale=(
        "Combines lower procurement costs, cheaper freight, higher pricing, "
        "tighter credit terms, and operational efficiency to show maximum "
        "upside potential under non-FX assumptions."
    ),
    components=[
        _PROCUREMENT_COST_DOWN,
        _FREIGHT_FAVOURABLE,
        _PRICING_IMPROVEMENT,
        _CREDIT_TIGHTENED,
        _OPERATIONAL_EFFICIENCY,
    ],
    notes="FX rate is unchanged. This represents the best realistic operating scenario.",
))

_register(ScenarioTemplate(
    name="total_downside",
    description="Worst-case operational & commercial assumptions",
    rationale=(
        "Combines higher procurement costs, expensive freight, pricing pressure, "
        "extended credit terms, and operational stress to show maximum downside "
        "exposure under non-FX assumptions."
    ),
    components=[
        _PROCUREMENT_COST_UP,
        _FREIGHT_STRESS,
        _PRICING_PRESSURE,
        _CREDIT_EXTENDED,
        _OPERATIONAL_STRESS,
    ],
    notes="FX rate is unchanged. This represents the worst realistic operating scenario.",
))

_register(ScenarioTemplate(
    name="procurement_cost_stress",
    description="Procurement costs increase ~10%",
    rationale=(
        "Tests sensitivity to partha rate increases, e.g. due to livestock "
        "price inflation or supply shortages."
    ),
    components=[_PROCUREMENT_COST_UP],
))

_register(ScenarioTemplate(
    name="freight_stress",
    description="Freight costs increase ~15%",
    rationale=(
        "Tests sensitivity to freight rate increases, e.g. due to fuel "
        "price spikes or logistics disruptions."
    ),
    components=[_FREIGHT_STRESS],
))

_register(ScenarioTemplate(
    name="pricing_pressure",
    description="Export pricing reduced by $0.20/kg across all tiers",
    rationale=(
        "Tests sensitivity to buyer price negotiations or market softening "
        "that compresses USD revenue per kg."
    ),
    components=[_PRICING_PRESSURE],
))

_register(ScenarioTemplate(
    name="working_capital_stress",
    description="Extended credit terms + higher operational costs",
    rationale=(
        "Tests working capital strain from customers paying later while "
        "operational costs increase, widening the funding gap."
    ),
    components=[_CREDIT_EXTENDED, _OPERATIONAL_STRESS],
    notes="Combines credit extension with operational cost increases.",
))


# ---------------------------------------------------------------------------
# Template library
# ---------------------------------------------------------------------------


class TemplateLibrary:
    """Registry of ScenarioTemplates with inspection and creation helpers."""

    def __init__(self) -> None:
        self._templates: dict[str, ScenarioTemplate] = {}

    def register(self, template: ScenarioTemplate) -> None:
        """Add or replace a template in the library."""
        self._templates[template.name] = template

    def get(self, name: str) -> ScenarioTemplate | None:
        return self._templates.get(name)

    def list_templates(self) -> list[ScenarioTemplate]:
        return list(self._templates.values())

    def template_names(self) -> list[str]:
        return list(self._templates.keys())

    def __len__(self) -> int:
        return len(self._templates)

    def __contains__(self, name: str) -> bool:
        return name in self._templates


def default_library() -> TemplateLibrary:
    """Create a TemplateLibrary pre-loaded with all built-in templates."""
    lib = TemplateLibrary()
    for t in BUILT_IN_TEMPLATES.values():
        lib.register(t)
    return lib


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def format_template_list(result: ListTemplatesResult) -> str:
    if not result.templates:
        return "No scenario templates available."
    lines = [f"Available scenario templates ({len(result.templates)}):"]
    for t in result.templates:
        dims = ", ".join(t.dimensions) if t.dimensions else "none"
        lines.append(f"  - {t.name}: {t.description} [{dims}]")
    return "\n".join(lines)


def format_inspect_template(result: InspectTemplateResult) -> str:
    if not result.found or result.template is None:
        return f"Template '{result.name}' not found."
    t = result.template
    lines = [
        "=" * 60,
        f"TEMPLATE: {t.name}",
        "=" * 60,
        f"  Description: {t.description}",
        f"  Rationale:   {t.rationale}",
    ]
    if t.notes:
        lines.append(f"  Notes:       {t.notes}")
    lines.append(f"  Dimensions:  {', '.join(t.dimensions) if t.dimensions else 'none'}")
    if t.components:
        lines.append(f"  Components ({len(t.components)}):")
        for comp in t.components:
            lines.append(f"    - {comp.name} [{comp.dimension}]: {comp.description}")
    else:
        lines.append("  Components: none (uses baseline defaults)")
    ov = t.merged_overrides
    overrides_parts = _describe_overrides(ov)
    if overrides_parts:
        lines.append("  Merged overrides:")
        for p in overrides_parts:
            lines.append(f"    - {p}")
    else:
        lines.append("  Merged overrides: none")
    return "\n".join(lines)


def format_create_from_template(result: CreateScenarioFromTemplateResult) -> str:
    if result.created:
        return (
            f"Created scenario '{result.scenario_name}' from template "
            f"'{result.template_name}'."
        )
    return result.message


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
        desc.append(f"customer_credit_days overridden ({len(ov.customer_credit_days)} months)")
    if ov.proc_model is not None:
        desc.append(f"proc_model = {ov.proc_model}")
    return desc
