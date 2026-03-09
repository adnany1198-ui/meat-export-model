"""Tests for scenario templates — template listing, inspection, creation,
consistency, and FX-unchanged verification.
"""

from __future__ import annotations

import unittest

from safi_engine.config import ScenarioOverrides
from safi_engine.query_model import (
    CompareNamedScenariosQuery,
    CreateScenarioFromTemplateQuery,
    InspectScenarioTemplateQuery,
    ListScenarioTemplatesQuery,
    ScenarioSummaryQuery,
)
from safi_engine.query_runner import QueryContext
from safi_engine.scenario_templates import (
    BUILT_IN_COMPONENTS,
    BUILT_IN_TEMPLATES,
    AssumptionComponent,
    ScenarioTemplate,
    TemplateLibrary,
    default_library,
)
from safi_engine.workspace import AnalyticalWorkspace

from validate_all_shipments import (
    load_cycle_details,
    load_outflow_config,
    load_strategy_config,
)


def _make_workspace() -> AnalyticalWorkspace:
    ctx = QueryContext(
        cycles=load_cycle_details(),
        config=load_strategy_config(),
        outflow_config=load_outflow_config(),
    )
    return AnalyticalWorkspace(ctx)


class TestTemplateLibrary(unittest.TestCase):
    """Low-level TemplateLibrary behaviour."""

    def test_default_library_not_empty(self):
        lib = default_library()
        self.assertGreater(len(lib), 0)

    def test_all_built_in_templates_registered(self):
        lib = default_library()
        for name in BUILT_IN_TEMPLATES:
            self.assertIn(name, lib)

    def test_get_existing(self):
        lib = default_library()
        t = lib.get("total_upside")
        self.assertIsNotNone(t)
        self.assertEqual(t.name, "total_upside")

    def test_get_missing(self):
        lib = default_library()
        self.assertIsNone(lib.get("nonexistent_template"))

    def test_custom_template_registration(self):
        lib = default_library()
        custom = ScenarioTemplate(
            name="custom_test",
            description="Test template",
            rationale="Testing extensibility",
            components=[BUILT_IN_COMPONENTS["freight_stress"]],
        )
        lib.register(custom)
        self.assertIn("custom_test", lib)
        self.assertEqual(lib.get("custom_test").name, "custom_test")


class TestTemplateContent(unittest.TestCase):
    """Template content and structure validation."""

    def test_required_built_in_names(self):
        required = {
            "baseline", "total_upside", "total_downside",
            "procurement_cost_stress", "freight_stress",
            "pricing_pressure", "working_capital_stress",
        }
        self.assertTrue(required.issubset(set(BUILT_IN_TEMPLATES.keys())))

    def test_all_templates_have_description(self):
        for name, t in BUILT_IN_TEMPLATES.items():
            self.assertTrue(t.description, f"Template '{name}' has no description")

    def test_all_templates_have_rationale(self):
        for name, t in BUILT_IN_TEMPLATES.items():
            self.assertTrue(t.rationale, f"Template '{name}' has no rationale")

    def test_baseline_has_no_components(self):
        t = BUILT_IN_TEMPLATES["baseline"]
        self.assertEqual(len(t.components), 0)

    def test_baseline_merged_overrides_empty(self):
        t = BUILT_IN_TEMPLATES["baseline"]
        ov = t.merged_overrides
        self.assertIsNone(ov.usd_to_pkr)
        self.assertIsNone(ov.partha_rates)
        self.assertIsNone(ov.outflow_rate_overrides)
        self.assertIsNone(ov.pricing_tiers)
        self.assertIsNone(ov.customer_credit_days)
        self.assertIsNone(ov.proc_model)

    def test_total_upside_has_multiple_components(self):
        t = BUILT_IN_TEMPLATES["total_upside"]
        self.assertGreater(len(t.components), 3)

    def test_total_downside_has_multiple_components(self):
        t = BUILT_IN_TEMPLATES["total_downside"]
        self.assertGreater(len(t.components), 3)

    def test_total_upside_dimensions(self):
        t = BUILT_IN_TEMPLATES["total_upside"]
        dims = t.dimensions
        self.assertIn("procurement", dims)
        self.assertIn("pricing", dims)
        self.assertIn("freight", dims)

    def test_total_downside_dimensions(self):
        t = BUILT_IN_TEMPLATES["total_downside"]
        dims = t.dimensions
        self.assertIn("procurement", dims)
        self.assertIn("pricing", dims)
        self.assertIn("freight", dims)

    def test_component_names_property(self):
        t = BUILT_IN_TEMPLATES["working_capital_stress"]
        names = t.component_names
        self.assertIn("credit_extended", names)
        self.assertIn("operational_stress", names)


class TestFxUnchanged(unittest.TestCase):
    """Confirm that all built-in templates do NOT change usd_to_pkr."""

    def test_no_built_in_template_changes_fx(self):
        for name, t in BUILT_IN_TEMPLATES.items():
            ov = t.merged_overrides
            self.assertIsNone(
                ov.usd_to_pkr,
                f"Template '{name}' unexpectedly overrides usd_to_pkr",
            )

    def test_no_built_in_component_changes_fx(self):
        for name, c in BUILT_IN_COMPONENTS.items():
            self.assertIsNone(
                c.overrides.usd_to_pkr,
                f"Component '{name}' unexpectedly overrides usd_to_pkr",
            )


class TestMergedOverrides(unittest.TestCase):
    """Verify that component merging works correctly."""

    def test_single_component_passthrough(self):
        t = BUILT_IN_TEMPLATES["procurement_cost_stress"]
        ov = t.merged_overrides
        self.assertIsNotNone(ov.partha_rates)
        self.assertIsNone(ov.outflow_rate_overrides)
        self.assertIsNone(ov.pricing_tiers)

    def test_freight_stress_overrides_freight(self):
        t = BUILT_IN_TEMPLATES["freight_stress"]
        ov = t.merged_overrides
        self.assertIn("Freight", ov.outflow_rate_overrides)

    def test_total_upside_merges_all_dimensions(self):
        ov = BUILT_IN_TEMPLATES["total_upside"].merged_overrides
        self.assertIsNotNone(ov.partha_rates)
        self.assertIsNotNone(ov.outflow_rate_overrides)
        self.assertIsNotNone(ov.pricing_tiers)
        self.assertIsNotNone(ov.customer_credit_days)

    def test_total_downside_merges_all_dimensions(self):
        ov = BUILT_IN_TEMPLATES["total_downside"].merged_overrides
        self.assertIsNotNone(ov.partha_rates)
        self.assertIsNotNone(ov.outflow_rate_overrides)
        self.assertIsNotNone(ov.pricing_tiers)
        self.assertIsNotNone(ov.customer_credit_days)

    def test_working_capital_stress_merges_credit_and_ops(self):
        ov = BUILT_IN_TEMPLATES["working_capital_stress"].merged_overrides
        self.assertIsNotNone(ov.customer_credit_days)
        self.assertIsNotNone(ov.outflow_rate_overrides)
        self.assertIn("Chilling", ov.outflow_rate_overrides)


class TestListTemplatesQuery(unittest.TestCase):
    """Test listing templates through the workspace."""

    def test_list_templates(self):
        ws = _make_workspace()
        result, text = ws.execute(ListScenarioTemplatesQuery())
        self.assertGreater(len(result.templates), 0)
        self.assertIn("Available scenario templates", text)

    def test_list_includes_all_built_in(self):
        ws = _make_workspace()
        result, text = ws.execute(ListScenarioTemplatesQuery())
        names = [t.name for t in result.templates]
        for required in ["baseline", "total_upside", "total_downside"]:
            self.assertIn(required, names)

    def test_list_format_shows_dimensions(self):
        ws = _make_workspace()
        _, text = ws.execute(ListScenarioTemplatesQuery())
        # total_downside should show dimensions in brackets
        self.assertIn("[", text)


class TestInspectTemplateQuery(unittest.TestCase):
    """Test inspecting a template through the workspace."""

    def test_inspect_existing(self):
        ws = _make_workspace()
        result, text = ws.execute(InspectScenarioTemplateQuery(name="total_upside"))
        self.assertTrue(result.found)
        self.assertIn("TEMPLATE: total_upside", text)
        self.assertIn("Components", text)

    def test_inspect_shows_overrides(self):
        ws = _make_workspace()
        _, text = ws.execute(InspectScenarioTemplateQuery(name="total_downside"))
        self.assertIn("Merged overrides", text)
        self.assertIn("partha_rates", text)

    def test_inspect_nonexistent(self):
        ws = _make_workspace()
        result, text = ws.execute(InspectScenarioTemplateQuery(name="no_such"))
        self.assertFalse(result.found)
        self.assertIn("not found", text)

    def test_inspect_baseline(self):
        ws = _make_workspace()
        result, text = ws.execute(InspectScenarioTemplateQuery(name="baseline"))
        self.assertTrue(result.found)
        self.assertIn("none", text.lower())  # no components or no overrides


class TestCreateFromTemplate(unittest.TestCase):
    """Test creating named scenarios from templates."""

    def test_create_scenario(self):
        ws = _make_workspace()
        result, text = ws.execute(CreateScenarioFromTemplateQuery(
            template_name="total_downside",
            scenario_name="my_downside",
        ))
        self.assertTrue(result.created)
        self.assertIn("Created scenario", text)
        self.assertIn("my_downside", text)

    def test_created_scenario_is_retrievable(self):
        ws = _make_workspace()
        ws.execute(CreateScenarioFromTemplateQuery(
            template_name="freight_stress",
            scenario_name="freight_test",
        ))
        sc = ws.get_scenario("freight_test")
        self.assertIsNotNone(sc)
        self.assertIn("Freight", sc.overrides.outflow_rate_overrides)

    def test_create_from_nonexistent_template(self):
        ws = _make_workspace()
        result, text = ws.execute(CreateScenarioFromTemplateQuery(
            template_name="does_not_exist",
            scenario_name="test",
        ))
        self.assertFalse(result.created)
        self.assertIn("not found", text)

    def test_create_baseline_name_fails(self):
        ws = _make_workspace()
        result, text = ws.execute(CreateScenarioFromTemplateQuery(
            template_name="total_upside",
            scenario_name="baseline",
        ))
        self.assertFalse(result.created)

    def test_created_scenario_has_description(self):
        ws = _make_workspace()
        ws.execute(CreateScenarioFromTemplateQuery(
            template_name="pricing_pressure",
            scenario_name="pp_scenario",
            description="Custom description",
        ))
        sc = ws.get_scenario("pp_scenario")
        self.assertEqual(sc.description, "Custom description")

    def test_default_description_from_template(self):
        ws = _make_workspace()
        ws.execute(CreateScenarioFromTemplateQuery(
            template_name="pricing_pressure",
            scenario_name="pp_auto",
        ))
        sc = ws.get_scenario("pp_auto")
        self.assertIn("pricing_pressure", sc.description)


class TestTemplateConsistency(unittest.TestCase):
    """Verify that template-generated scenarios match direct overrides."""

    def test_template_matches_direct_overrides(self):
        """A scenario from template should have identical overrides to
        manually constructing the same ScenarioOverrides."""
        ws = _make_workspace()
        t = BUILT_IN_TEMPLATES["procurement_cost_stress"]
        expected_ov = t.merged_overrides

        ws.execute(CreateScenarioFromTemplateQuery(
            template_name="procurement_cost_stress",
            scenario_name="from_template",
        ))
        sc = ws.get_scenario("from_template")
        actual_ov = sc.overrides

        self.assertEqual(actual_ov.partha_rates, expected_ov.partha_rates)
        self.assertEqual(actual_ov.usd_to_pkr, expected_ov.usd_to_pkr)

    def test_template_scenario_runs_same_as_inline(self):
        """Running a scenario created from a template should produce the
        same result as passing inline overrides."""
        ws = _make_workspace()
        t = BUILT_IN_TEMPLATES["freight_stress"]
        inline_ov = t.merged_overrides

        # Create scenario from template
        ws.execute(CreateScenarioFromTemplateQuery(
            template_name="freight_stress",
            scenario_name="freight_tmpl",
        ))

        # Run summary via named scenario
        r1, _ = ws.execute(ScenarioSummaryQuery(scenario_name="freight_tmpl"))
        # Run summary via inline overrides
        r2, _ = ws.execute(ScenarioSummaryQuery(overrides=inline_ov))

        s1 = r1.summary
        s2 = r2.summary
        self.assertAlmostEqual(s1.total_baseline_net, s2.total_baseline_net, places=2)
        self.assertAlmostEqual(s1.total_scenario_net, s2.total_scenario_net, places=2)
        self.assertAlmostEqual(s1.total_net_delta, s2.total_net_delta, places=2)


class TestUpsideVsDownside(unittest.TestCase):
    """Compare total_upside vs total_downside to verify directionality."""

    def test_upside_better_than_downside(self):
        ws = _make_workspace()

        # Create both scenarios
        ws.execute(CreateScenarioFromTemplateQuery(
            template_name="total_upside",
            scenario_name="upside",
        ))
        ws.execute(CreateScenarioFromTemplateQuery(
            template_name="total_downside",
            scenario_name="downside",
        ))

        r_up, _ = ws.execute(ScenarioSummaryQuery(scenario_name="upside"))
        r_down, _ = ws.execute(ScenarioSummaryQuery(scenario_name="downside"))

        # Upside should have higher net cashflow than downside
        self.assertGreater(
            r_up.summary.total_scenario_net,
            r_down.summary.total_scenario_net,
        )

    def test_upside_downside_comparison_text(self):
        ws = _make_workspace()
        ws.execute(CreateScenarioFromTemplateQuery(
            template_name="total_upside", scenario_name="upside",
        ))
        ws.execute(CreateScenarioFromTemplateQuery(
            template_name="total_downside", scenario_name="downside",
        ))
        _, text = ws.execute(CompareNamedScenariosQuery(
            scenario_a="upside", scenario_b="downside",
        ))
        self.assertIn("Comparing 'upside' vs 'downside'", text)
        self.assertIn("Net Cashflow", text)

    def test_both_differ_from_baseline(self):
        ws = _make_workspace()
        ws.execute(CreateScenarioFromTemplateQuery(
            template_name="total_upside", scenario_name="upside",
        ))
        ws.execute(CreateScenarioFromTemplateQuery(
            template_name="total_downside", scenario_name="downside",
        ))

        r_up, _ = ws.execute(ScenarioSummaryQuery(scenario_name="upside"))
        r_down, _ = ws.execute(ScenarioSummaryQuery(scenario_name="downside"))

        # Both should differ from baseline
        self.assertNotAlmostEqual(r_up.summary.total_net_delta, 0.0, places=0)
        self.assertNotAlmostEqual(r_down.summary.total_net_delta, 0.0, places=0)

        # Upside delta should be positive, downside negative
        self.assertGreater(r_up.summary.total_net_delta, 0)
        self.assertLess(r_down.summary.total_net_delta, 0)


class TestExtensibility(unittest.TestCase):
    """Verify the template system is extensible for future risk dimensions."""

    def test_custom_component_new_dimension(self):
        """A new risk dimension (e.g. buyer_default) can be added
        as a component without modifying existing code."""
        # Future: buyer_default_risk could use a new ScenarioOverrides field
        # For now, demonstrate that custom components work
        custom_comp = AssumptionComponent(
            name="buyer_default_mild",
            dimension="buyer_risk",
            description="Mild buyer default risk — longer credit, lower pricing",
            overrides=ScenarioOverrides(
                customer_credit_days=[],  # placeholder
                pricing_tiers=[],         # placeholder
            ),
        )
        custom_template = ScenarioTemplate(
            name="buyer_risk_mild",
            description="Mild buyer default scenario",
            rationale="Tests resilience to buyer payment issues",
            components=[custom_comp],
        )
        lib = default_library()
        lib.register(custom_template)
        self.assertIn("buyer_risk_mild", lib)
        self.assertEqual(lib.get("buyer_risk_mild").dimensions, ["buyer_risk"])

    def test_compose_built_in_with_custom(self):
        """Custom components can be combined with built-in ones."""
        custom = AssumptionComponent(
            name="premium_pricing",
            dimension="pricing",
            description="Premium pricing for niche market",
            overrides=ScenarioOverrides(pricing_tiers=[]),
        )
        t = ScenarioTemplate(
            name="premium_with_freight_risk",
            description="Premium pricing offset by freight risk",
            rationale="Niche market with logistics exposure",
            components=[
                custom,
                BUILT_IN_COMPONENTS["freight_stress"],
            ],
        )
        self.assertEqual(len(t.components), 2)
        dims = t.dimensions
        self.assertIn("pricing", dims)
        self.assertIn("freight", dims)


class TestExistingTestsUnbroken(unittest.TestCase):
    """Verify workspace still works for non-template operations."""

    def test_workspace_still_handles_scenarios(self):
        ws = _make_workspace()
        ws.save_scenario("test_sc", ScenarioOverrides(partha_rates={"SUPPLIER": 1200}))
        sc = ws.get_scenario("test_sc")
        self.assertIsNotNone(sc)

    def test_workspace_still_resolves_named_scenarios(self):
        ws = _make_workspace()
        ws.save_scenario("test_sc", ScenarioOverrides(
            partha_rates={"SUPPLIER": 1200, "INTERNAL": 1100},
        ))
        r, _ = ws.execute(ScenarioSummaryQuery(scenario_name="test_sc"))
        self.assertIsNotNone(r.summary)


if __name__ == "__main__":
    unittest.main()
