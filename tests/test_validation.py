"""Tests that validate the engine against the full spreadsheet fixture data.

These tests use validate_all_shipments to compare engine-computed cashflows
against the spreadsheet's cashflow_master for all 213 shipments.
"""

import pytest

from validate_all_shipments import (
    load_cycle_details,
    load_expected_cashflows,
    load_outflow_config,
    load_strategy_config,
    compute_sale_entry,
    compare_shipment,
    validate_all,
)
from safi_engine.engine import compute_shipment_cashflow


# Run validation once and share across tests
@pytest.fixture(scope="module")
def validation_results():
    return validate_all()


@pytest.fixture(scope="module")
def cycles():
    return load_cycle_details()


class TestFullValidation:
    def test_all_213_shipments_present(self, validation_results):
        assert len(validation_results) == 213

    def test_all_shipments_pass(self, validation_results):
        failed = [r for r in validation_results if not r.passed]
        if failed:
            details = "\n".join(
                f"  Ship {r.shipment_number}: {r.error or 'mismatches'}"
                for r in failed[:10]
            )
            pytest.fail(f"{len(failed)} shipments failed:\n{details}")

    def test_no_engine_errors(self, validation_results):
        errors = [r for r in validation_results if r.error]
        assert errors == [], f"Engine errors: {[r.error for r in errors[:5]]}"

    def test_every_shipment_has_16_expected_rows(self, validation_results):
        """Each shipment should have 15 outflows + 1 SALE inflow = 16 rows."""
        for r in validation_results:
            assert r.expected_count == 16, (
                f"Shipment {r.shipment_number} has {r.expected_count} expected rows"
            )


class TestMultiShipmentOutflows:
    """Spot-check outflows for specific shipments beyond shipment 1."""

    @pytest.fixture(scope="class")
    def engine_inputs(self):
        cycles = load_cycle_details()
        outflow_config = load_outflow_config()
        strategy_config, credit_terms, pricing_tiers = load_strategy_config()
        cycle_by_num = {c.shipment_number: c for c in cycles}
        return cycle_by_num, strategy_config, outflow_config

    def _compute(self, engine_inputs, ship_num):
        cycle_by_num, strategy_config, outflow_config = engine_inputs
        cycle = cycle_by_num[ship_num]
        return compute_shipment_cashflow(cycle, strategy_config, outflow_config)

    def test_shipment_2_supplier_b(self, engine_inputs):
        """Shipment 2: Customer B, SUPPLIER, 4800 kg."""
        entries = self._compute(engine_inputs, 2)
        total = sum(e.amount_pkr for e in entries)
        # Expected from cashflow_master (sum of all OUT rows for ship 2)
        expected_total = (5328000 + 24000 + 184800 + 1017600 + 28800
                          + 11232 + 6192 + 9600 + 384 + 62064 + 45024
                          + 52560 + 6624 + 264000 + 4800)
        assert abs(total - expected_total) < 0.01

    def test_shipment_16_internal_g(self, engine_inputs):
        """Shipment 16: Customer G, INTERNAL model, ~7857 kg."""
        entries = self._compute(engine_inputs, 16)
        partha = next(e for e in entries if e.cost_type == "Partha")
        # INTERNAL rate = 1000 PKR/kg
        assert abs(partha.amount_pkr - 1000 * 7857.142857) < 0.01

    def test_shipment_6_supplier_c(self, engine_inputs):
        """Shipment 6: Customer C, SUPPLIER, 3200 kg."""
        entries = self._compute(engine_inputs, 6)
        by_type = {e.cost_type: e for e in entries}
        assert abs(by_type["Freight"].amount_pkr - 212 * 3200) < 0.01
        assert abs(by_type["Chilling"].amount_pkr - 55 * 3200) < 0.01


class TestSaleInflows:
    """Validate SALE inflow computation for shipments across different months."""

    @pytest.fixture(scope="class")
    def sale_inputs(self):
        cycles = load_cycle_details()
        strategy_config, credit_terms, pricing_tiers = load_strategy_config()
        expected = load_expected_cashflows()
        cycle_by_num = {c.shipment_number: c for c in cycles}
        return cycle_by_num, strategy_config, credit_terms, pricing_tiers, expected

    def _get_expected_sale(self, expected, ship_num):
        rows = expected[ship_num]
        return next(r for r in rows if r["Item"] == "SALE")

    def test_jan_sale_price_5_70(self, sale_inputs):
        """Jan shipments use 5.70 USD/kg (17 credit days -> 16-18 tier)."""
        cycle_by_num, config, ct, pt, expected = sale_inputs
        entry = compute_sale_entry(cycle_by_num[1], config, ct, pt)
        usd_per_kg = entry.amount_pkr / 8000 / 281
        assert abs(usd_per_kg - 5.70) < 0.001

    def test_apr_sale_price_5_80(self, sale_inputs):
        """Apr shipments use 5.80 USD/kg (15 credit days -> 13-15 tier)."""
        cycle_by_num, config, ct, pt, expected = sale_inputs
        entry = compute_sale_entry(cycle_by_num[42], config, ct, pt)
        usd_per_kg = entry.amount_pkr / cycle_by_num[42].weight_kg_net / 281
        assert abs(usd_per_kg - 5.80) < 0.001

    def test_sep_sale_price_5_90(self, sale_inputs):
        """Sep shipments use 5.90 USD/kg (12 credit days -> 10-12 tier)."""
        cycle_by_num, config, ct, pt, expected = sale_inputs
        entry = compute_sale_entry(cycle_by_num[156], config, ct, pt)
        usd_per_kg = entry.amount_pkr / cycle_by_num[156].weight_kg_net / 281
        assert abs(usd_per_kg - 5.90) < 0.001

    def test_sale_credit_days_vary_by_month(self, sale_inputs):
        """Credit days should differ between Jan (17d) and Oct (11d)."""
        cycle_by_num, config, ct, pt, expected = sale_inputs
        jan_entry = compute_sale_entry(cycle_by_num[1], config, ct, pt)
        oct_entry = compute_sale_entry(cycle_by_num[170], config, ct, pt)
        jan_credit = (jan_entry.payment_date - jan_entry.event_date).days
        oct_credit = (oct_entry.payment_date - oct_entry.event_date).days
        assert jan_credit == 17
        assert oct_credit == 11
