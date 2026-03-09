"""Tests for the rules engine against Shipment 1 fixture data."""

import datetime
import json
from pathlib import Path

from safi_engine.config import CreditDays, PricingTier, ScenarioOverrides, StrategyConfig
from safi_engine.cycle import ShipmentCycle
from safi_engine.engine import (
    CashflowEntry,
    compute_full_shipment_cashflow,
    compute_sale_entry,
    compute_shipment_cashflow,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _load_outflow_config() -> list[dict]:
    return json.loads((FIXTURES / "outflow_config.json").read_text())


def _shipment_1() -> ShipmentCycle:
    """Shipment 1 from cycle_detail_raw.json row 1."""
    return ShipmentCycle(
        proc_model="SUPPLIER",
        customer_id="A",
        shipment_number=1,
        cash_date=datetime.date(2026, 1, 1),
        slaughter_date=datetime.date(2026, 1, 4),
        slaughter_end_date=datetime.date(2026, 1, 5),
        send_date=datetime.date(2026, 1, 14),
        receive_date=datetime.date(2026, 1, 15),
        pay_days=9,
        weight_kg_net=8000.0,
    )


def _strategy_config() -> StrategyConfig:
    """Minimal StrategyConfig for outflow-only tests.

    Uses the canonical partha rates.  Does not populate pricing_tiers or
    customer_credit_days (not needed for outflow computation).
    """
    return StrategyConfig(
        usd_to_pkr=281,
        partha_rates={"SUPPLIER": 1110, "INTERNAL": 1000},
    )


def _full_strategy_config() -> StrategyConfig:
    """Fully-populated StrategyConfig for full cashflow tests.

    Values match strategy_control_raw.json January row.
    """
    return StrategyConfig(
        usd_to_pkr=281,
        partha_rates={"SUPPLIER": 1110, "INTERNAL": 1000},
        pricing_tiers=[
            PricingTier(credit_days_min=10, credit_days_max=12, price_usd_per_kg=5.90),
            PricingTier(credit_days_min=13, credit_days_max=15, price_usd_per_kg=5.80),
            PricingTier(credit_days_min=16, credit_days_max=18, price_usd_per_kg=5.70),
            PricingTier(credit_days_min=19, credit_days_max=20, price_usd_per_kg=5.65),
        ],
        customer_credit_days=[
            CreditDays(month="Jan-2026", min_days=15.0, max_days=20.0, avg_days=17.5),
        ],
    )


class TestShipment1Outflow:
    def test_total_outflow_matches_expected(self):
        entries = compute_shipment_cashflow(
            _shipment_1(), _strategy_config(), _load_outflow_config(),
        )
        total = sum(e.amount_pkr for e in entries)
        assert total == 11_742_800

    def test_entry_count(self):
        """Partha + 14 per-kg outflow items = 15 entries."""
        entries = compute_shipment_cashflow(
            _shipment_1(), _strategy_config(), _load_outflow_config(),
        )
        assert len(entries) == 15

    def test_partha_is_first_and_correct(self):
        entries = compute_shipment_cashflow(
            _shipment_1(), _strategy_config(), _load_outflow_config(),
        )
        partha = entries[0]
        assert partha.cost_type == "Partha"
        assert partha.amount_pkr == 1110 * 8000
        assert partha.event_date == datetime.date(2026, 1, 1)

    def test_all_entries_are_outflows(self):
        entries = compute_shipment_cashflow(
            _shipment_1(), _strategy_config(), _load_outflow_config(),
        )
        assert all(e.direction == "outflow" for e in entries)

    def test_slaughter_start_items_date(self):
        """Slaughter and Animal_Trimming fire on slaughter_date."""
        entries = compute_shipment_cashflow(
            _shipment_1(), _strategy_config(), _load_outflow_config(),
        )
        by_type = {e.cost_type: e for e in entries}
        assert by_type["Slaughter"].event_date == datetime.date(2026, 1, 4)
        assert by_type["Animal_Trimming"].event_date == datetime.date(2026, 1, 4)

    def test_slaughter_end_items_date(self):
        """Freight, Clearance, etc. fire on slaughter_end_date."""
        entries = compute_shipment_cashflow(
            _shipment_1(), _strategy_config(), _load_outflow_config(),
        )
        by_type = {e.cost_type: e for e in entries}
        assert by_type["Freight"].event_date == datetime.date(2026, 1, 5)
        assert by_type["Clearance"].event_date == datetime.date(2026, 1, 5)

    def test_slaughter_end_plus1_items_date(self):
        """TPT, Data_Logger, Chilling, Polysheet fire on slaughter_end + 1."""
        entries = compute_shipment_cashflow(
            _shipment_1(), _strategy_config(), _load_outflow_config(),
        )
        by_type = {e.cost_type: e for e in entries}
        expected = datetime.date(2026, 1, 6)
        assert by_type["TPT_Slaughter"].event_date == expected
        assert by_type["Data_Logger"].event_date == expected
        assert by_type["Chilling"].event_date == expected
        assert by_type["Polysheet"].event_date == expected

    def test_individual_amounts(self):
        """Spot-check a few line items."""
        entries = compute_shipment_cashflow(
            _shipment_1(), _strategy_config(), _load_outflow_config(),
        )
        by_type = {e.cost_type: e for e in entries}
        assert by_type["Freight"].amount_pkr == 212 * 8000  # 1,696,000
        assert by_type["Chilling"].amount_pkr == 55 * 8000  # 440,000
        assert by_type["Animal_Trimming"].amount_pkr == 38.5 * 8000  # 308,000


class TestFullShipmentCashflow:
    """Tests for compute_full_shipment_cashflow — the unified entry point."""

    def test_returns_16_entries(self):
        """15 outflows + 1 SALE inflow = 16 entries."""
        entries = compute_full_shipment_cashflow(
            _shipment_1(), _full_strategy_config(), _load_outflow_config(),
        )
        assert len(entries) == 16

    def test_has_one_inflow(self):
        entries = compute_full_shipment_cashflow(
            _shipment_1(), _full_strategy_config(), _load_outflow_config(),
        )
        inflows = [e for e in entries if e.direction == "inflow"]
        assert len(inflows) == 1
        assert inflows[0].cost_type == "SALE"

    def test_outflows_unchanged(self):
        """Full cashflow outflows match outflow-only computation."""
        outflow_only = compute_shipment_cashflow(
            _shipment_1(), _strategy_config(), _load_outflow_config(),
        )
        full = compute_full_shipment_cashflow(
            _shipment_1(), _full_strategy_config(), _load_outflow_config(),
        )
        full_outflows = [e for e in full if e.direction == "outflow"]
        assert len(full_outflows) == len(outflow_only)
        for a, b in zip(outflow_only, full_outflows):
            assert a.cost_type == b.cost_type
            assert a.amount_pkr == b.amount_pkr
            assert a.event_date == b.event_date

    def test_sale_amount_matches_spreadsheet(self):
        """SALE for shipment 1 = 12,813,600 PKR (8000 kg × 5.70 USD/kg × 281)."""
        entries = compute_full_shipment_cashflow(
            _shipment_1(), _full_strategy_config(), _load_outflow_config(),
        )
        sale = next(e for e in entries if e.cost_type == "SALE")
        assert sale.amount_pkr == 8000 * 5.70 * 281  # 12,813,600

    def test_sale_credit_days(self):
        """Jan avg_days=17.5 → floor=17 → payment 17 days after receive."""
        entries = compute_full_shipment_cashflow(
            _shipment_1(), _full_strategy_config(), _load_outflow_config(),
        )
        sale = next(e for e in entries if e.cost_type == "SALE")
        assert sale.event_date == datetime.date(2026, 1, 15)
        assert sale.payment_date == datetime.date(2026, 2, 1)
        assert (sale.payment_date - sale.event_date).days == 17

    def test_sale_source_assumption_is_explicit(self):
        """The source_assumption should record the price and credit days used."""
        entries = compute_full_shipment_cashflow(
            _shipment_1(), _full_strategy_config(), _load_outflow_config(),
        )
        sale = next(e for e in entries if e.cost_type == "SALE")
        assert "5.7" in sale.source_assumption
        assert "17" in sale.source_assumption


class TestProvenance:
    """Verify structured provenance metadata on CashflowEntry objects."""

    def test_all_entries_are_cashflow_entries(self):
        entries = compute_full_shipment_cashflow(
            _shipment_1(), _full_strategy_config(), _load_outflow_config(),
        )
        for e in entries:
            assert isinstance(e, CashflowEntry)

    def test_supplier_outflow_partha_provenance(self):
        """Partha entry for SUPPLIER model has correct provenance."""
        entries = compute_shipment_cashflow(
            _shipment_1(), _strategy_config(), _load_outflow_config(),
        )
        partha = entries[0]
        assert partha.model_type == "SUPPLIER"
        assert partha.rule_name == "partha_procurement"
        assert partha.rate_used == 1110
        assert partha.timing_basis == "CASH_OUT"
        assert partha.inputs_used["partha_rate"] == 1110
        assert partha.inputs_used["weight_kg_net"] == 8000.0
        assert "partha_rate" in partha.formula_description
        assert "weight_kg_net" in partha.formula_description

    def test_supplier_outflow_per_kg_provenance(self):
        """Per-kg outflow items have correct provenance metadata."""
        entries = compute_shipment_cashflow(
            _shipment_1(), _strategy_config(), _load_outflow_config(),
        )
        freight = next(e for e in entries if e.cost_type == "Freight")
        assert freight.model_type == "SUPPLIER"
        assert freight.rule_name == "per_kg_outflow"
        assert freight.rate_used == 212
        assert freight.timing_basis == "SLAUGHTER_END"
        assert freight.inputs_used["rate_pkr_per_kg"] == 212
        assert freight.inputs_used["weight_kg_net"] == 8000.0
        assert "credit_days" in freight.inputs_used

    def test_internal_outflow_partha_provenance(self):
        """Partha entry for INTERNAL model uses 1000 PKR/kg rate."""
        internal_cycle = ShipmentCycle(
            proc_model="INTERNAL",
            customer_id="G",
            shipment_number=99,
            cash_date=datetime.date(2026, 1, 1),
            slaughter_date=datetime.date(2026, 1, 4),
            slaughter_end_date=datetime.date(2026, 1, 5),
            send_date=datetime.date(2026, 1, 14),
            receive_date=datetime.date(2026, 1, 15),
            pay_days=9,
            weight_kg_net=5000.0,
        )
        config = StrategyConfig(
            usd_to_pkr=281,
            partha_rates={"SUPPLIER": 1110, "INTERNAL": 1000},
        )
        entries = compute_shipment_cashflow(internal_cycle, config, _load_outflow_config())
        partha = entries[0]
        assert partha.model_type == "INTERNAL"
        assert partha.rule_name == "partha_procurement"
        assert partha.rate_used == 1000
        assert partha.inputs_used["partha_rate"] == 1000
        assert partha.amount_pkr == 5_000_000

    def test_sale_inflow_provenance(self):
        """SALE inflow has complete provenance with pricing tier and credit info."""
        entry = compute_sale_entry(_shipment_1(), _full_strategy_config())
        assert entry.model_type == "SUPPLIER"
        assert entry.rule_name == "sale_inflow"
        assert entry.rate_used == 5.70
        assert entry.timing_basis == "RECEIVE_DATE"
        assert entry.inputs_used["weight_kg_net"] == 8000.0
        assert entry.inputs_used["price_usd_per_kg"] == 5.70
        assert entry.inputs_used["usd_to_pkr"] == 281
        assert entry.inputs_used["avg_credit_days"] == 17.5
        assert entry.inputs_used["credit_days_applied"] == 17
        assert entry.inputs_used["pricing_tier"] == "16-18"
        assert entry.inputs_used["receive_month"] == "Jan-2026"
        assert "weight_kg_net" in entry.formula_description
        assert "price_usd_per_kg" in entry.formula_description
        assert "usd_to_pkr" in entry.formula_description
        assert "16-18" in entry.notes

    def test_every_entry_has_provenance(self):
        """All entries from compute_full_shipment_cashflow have non-empty provenance."""
        entries = compute_full_shipment_cashflow(
            _shipment_1(), _full_strategy_config(), _load_outflow_config(),
        )
        for e in entries:
            assert e.model_type, f"{e.cost_type} missing model_type"
            assert e.rule_name, f"{e.cost_type} missing rule_name"
            assert e.formula_description, f"{e.cost_type} missing formula_description"
            assert e.inputs_used, f"{e.cost_type} missing inputs_used"
            assert e.rate_used is not None, f"{e.cost_type} missing rate_used"
            assert e.timing_basis, f"{e.cost_type} missing timing_basis"


class TestScenarioOverrides:
    """Verify that ScenarioOverrides change outputs and are tracked in provenance."""

    def test_no_overrides_matches_baseline(self):
        """Passing overrides=None produces identical results to no-arg call."""
        cycle = _shipment_1()
        config = _full_strategy_config()
        outflow_config = _load_outflow_config()

        baseline = compute_full_shipment_cashflow(cycle, config, outflow_config)
        with_none = compute_full_shipment_cashflow(cycle, config, outflow_config, overrides=None)

        assert len(baseline) == len(with_none)
        for b, w in zip(baseline, with_none):
            assert b.amount_pkr == w.amount_pkr
            assert b.event_date == w.event_date
            assert b.payment_date == w.payment_date
            assert w.overrides_applied == []

    def test_empty_overrides_matches_baseline(self):
        """ScenarioOverrides() with all-None fields produces baseline results."""
        cycle = _shipment_1()
        config = _full_strategy_config()
        outflow_config = _load_outflow_config()

        baseline = compute_full_shipment_cashflow(cycle, config, outflow_config)
        with_empty = compute_full_shipment_cashflow(
            cycle, config, outflow_config, overrides=ScenarioOverrides(),
        )

        for b, w in zip(baseline, with_empty):
            assert b.amount_pkr == w.amount_pkr
            assert w.overrides_applied == []

    def test_fx_override_changes_sale_only(self):
        """Overriding usd_to_pkr changes SALE amount but not outflows."""
        cycle = _shipment_1()
        config = _full_strategy_config()
        outflow_config = _load_outflow_config()

        baseline = compute_full_shipment_cashflow(cycle, config, outflow_config)
        scenario = compute_full_shipment_cashflow(
            cycle, config, outflow_config,
            overrides=ScenarioOverrides(usd_to_pkr=300),
        )

        # Outflows should be identical (FX doesn't affect PKR outflows)
        baseline_out = [e for e in baseline if e.direction == "outflow"]
        scenario_out = [e for e in scenario if e.direction == "outflow"]
        for b, s in zip(baseline_out, scenario_out):
            assert b.amount_pkr == s.amount_pkr
            assert s.overrides_applied == []

        # SALE should differ
        baseline_sale = next(e for e in baseline if e.cost_type == "SALE")
        scenario_sale = next(e for e in scenario if e.cost_type == "SALE")

        expected_sale = 8000 * 5.70 * 300
        assert scenario_sale.amount_pkr == expected_sale
        assert scenario_sale.amount_pkr != baseline_sale.amount_pkr
        assert scenario_sale.inputs_used["usd_to_pkr"] == 300
        assert any("usd_to_pkr: 281 -> 300" in o for o in scenario_sale.overrides_applied)

    def test_sale_price_override_via_pricing_tiers(self):
        """Overriding pricing_tiers changes the SALE price."""
        cycle = _shipment_1()
        config = _full_strategy_config()
        outflow_config = _load_outflow_config()

        new_tiers = [
            PricingTier(credit_days_min=16, credit_days_max=18, price_usd_per_kg=6.00),
        ]
        scenario = compute_full_shipment_cashflow(
            cycle, config, outflow_config,
            overrides=ScenarioOverrides(pricing_tiers=new_tiers),
        )

        sale = next(e for e in scenario if e.cost_type == "SALE")
        expected = 8000 * 6.00 * 281
        assert sale.amount_pkr == expected
        assert sale.rate_used == 6.00
        assert any("pricing_tiers" in o for o in sale.overrides_applied)

    def test_outflow_rate_override(self):
        """Overriding a specific outflow rate changes that line item only."""
        cycle = _shipment_1()
        config = _strategy_config()
        outflow_config = _load_outflow_config()

        baseline = compute_shipment_cashflow(cycle, config, outflow_config)
        scenario = compute_shipment_cashflow(
            cycle, config, outflow_config,
            overrides=ScenarioOverrides(outflow_rate_overrides={"Freight": 250}),
        )

        baseline_freight = next(e for e in baseline if e.cost_type == "Freight")
        scenario_freight = next(e for e in scenario if e.cost_type == "Freight")

        assert baseline_freight.amount_pkr == 212 * 8000
        assert scenario_freight.amount_pkr == 250 * 8000
        assert scenario_freight.rate_used == 250
        assert any("rate(Freight): 212" in o for o in scenario_freight.overrides_applied)

        # Other items should be unchanged
        baseline_chilling = next(e for e in baseline if e.cost_type == "Chilling")
        scenario_chilling = next(e for e in scenario if e.cost_type == "Chilling")
        assert baseline_chilling.amount_pkr == scenario_chilling.amount_pkr
        assert scenario_chilling.overrides_applied == []

    def test_partha_rate_override(self):
        """Overriding partha rates changes procurement cost."""
        cycle = _shipment_1()
        config = _full_strategy_config()
        outflow_config = _load_outflow_config()

        scenario = compute_full_shipment_cashflow(
            cycle, config, outflow_config,
            overrides=ScenarioOverrides(partha_rates={"SUPPLIER": 1200, "INTERNAL": 1000}),
        )

        partha = scenario[0]
        assert partha.cost_type == "Partha"
        assert partha.amount_pkr == 1200 * 8000
        assert partha.rate_used == 1200
        assert any("partha_rate: 1110 -> 1200" in o for o in partha.overrides_applied)

    def test_credit_days_override(self):
        """Overriding customer credit days changes SALE payment date."""
        cycle = _shipment_1()
        config = _full_strategy_config()
        outflow_config = _load_outflow_config()

        # Override to 12 avg days (falls in 10-12 tier -> 5.90 USD/kg)
        new_credit = [CreditDays(month="Jan-2026", min_days=10, max_days=14, avg_days=12.0)]
        scenario = compute_full_shipment_cashflow(
            cycle, config, outflow_config,
            overrides=ScenarioOverrides(customer_credit_days=new_credit),
        )

        sale = next(e for e in scenario if e.cost_type == "SALE")
        assert (sale.payment_date - sale.event_date).days == 12
        assert sale.rate_used == 5.90  # different tier
        assert sale.amount_pkr == 8000 * 5.90 * 281
        assert any("customer_credit_days" in o for o in sale.overrides_applied)

    def test_proc_model_override(self):
        """Overriding proc_model changes partha rate and is tracked."""
        cycle = _shipment_1()  # SUPPLIER by default
        config = _full_strategy_config()
        outflow_config = _load_outflow_config()

        scenario = compute_full_shipment_cashflow(
            cycle, config, outflow_config,
            overrides=ScenarioOverrides(proc_model="INTERNAL"),
        )

        partha = scenario[0]
        assert partha.model_type == "INTERNAL"
        assert partha.rate_used == 1000  # INTERNAL rate
        assert partha.amount_pkr == 1000 * 8000
        assert any("proc_model: SUPPLIER -> INTERNAL" in o for o in partha.overrides_applied)

    def test_combined_overrides(self):
        """Multiple overrides can be applied simultaneously."""
        cycle = _shipment_1()
        config = _full_strategy_config()
        outflow_config = _load_outflow_config()

        scenario = compute_full_shipment_cashflow(
            cycle, config, outflow_config,
            overrides=ScenarioOverrides(
                usd_to_pkr=300,
                partha_rates={"SUPPLIER": 1200, "INTERNAL": 1050},
                outflow_rate_overrides={"Freight": 250},
            ),
        )

        partha = scenario[0]
        assert partha.amount_pkr == 1200 * 8000

        freight = next(e for e in scenario if e.cost_type == "Freight")
        assert freight.amount_pkr == 250 * 8000

        sale = next(e for e in scenario if e.cost_type == "SALE")
        assert sale.amount_pkr == 8000 * 5.70 * 300

    def test_baseline_entries_have_empty_overrides(self):
        """Baseline entries always have overrides_applied == []."""
        entries = compute_full_shipment_cashflow(
            _shipment_1(), _full_strategy_config(), _load_outflow_config(),
        )
        for e in entries:
            assert e.overrides_applied == [], (
                f"{e.cost_type} has unexpected overrides: {e.overrides_applied}"
            )
