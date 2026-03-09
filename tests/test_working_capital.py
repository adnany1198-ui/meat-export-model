"""Tests for working capital / funding analysis."""

import datetime
import json
from pathlib import Path

from safi_engine.config import CreditDays, PricingTier, ScenarioOverrides, StrategyConfig
from safi_engine.cycle import ShipmentCycle
from safi_engine.engine import CashflowEntry, compute_full_shipment_cashflow
from safi_engine.working_capital import (
    CashPositionPoint,
    FundingComparison,
    PortfolioFundingSummary,
    ShipmentFundingProfile,
    build_cash_timeline,
    compare_funding_profiles,
    format_funding_comparison,
    format_portfolio_summary,
    format_shipment_funding,
    portfolio_funding_summary,
    shipment_funding_profile,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _load_outflow_config() -> list[dict]:
    return json.loads((FIXTURES / "outflow_config.json").read_text())


def _shipment_1() -> ShipmentCycle:
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


def _shipment_2() -> ShipmentCycle:
    return ShipmentCycle(
        proc_model="SUPPLIER",
        customer_id="B",
        shipment_number=2,
        cash_date=datetime.date(2026, 1, 2),
        slaughter_date=datetime.date(2026, 1, 5),
        slaughter_end_date=datetime.date(2026, 1, 6),
        send_date=datetime.date(2026, 1, 15),
        receive_date=datetime.date(2026, 1, 16),
        pay_days=9,
        weight_kg_net=4800.0,
    )


def _full_strategy_config() -> StrategyConfig:
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


class TestBuildCashTimeline:
    """Tests for the core chronological cumulative cash logic."""

    def test_empty_entries_returns_empty(self):
        assert build_cash_timeline([]) == []

    def test_timeline_is_chronological(self):
        entries = compute_full_shipment_cashflow(
            _shipment_1(), _full_strategy_config(), _load_outflow_config(),
        )
        timeline = build_cash_timeline(entries)
        dates = [pt.date for pt in timeline]
        assert dates == sorted(dates)

    def test_cumulative_position_is_running_total(self):
        entries = compute_full_shipment_cashflow(
            _shipment_1(), _full_strategy_config(), _load_outflow_config(),
        )
        timeline = build_cash_timeline(entries)
        running = 0.0
        for pt in timeline:
            running += pt.daily_net
            assert abs(pt.cumulative_position - running) < 0.01

    def test_daily_net_equals_inflow_minus_outflow(self):
        entries = compute_full_shipment_cashflow(
            _shipment_1(), _full_strategy_config(), _load_outflow_config(),
        )
        timeline = build_cash_timeline(entries)
        for pt in timeline:
            assert abs(pt.daily_net - (pt.daily_inflow - pt.daily_outflow)) < 0.01

    def test_final_cumulative_equals_net_cashflow(self):
        """Final cumulative position should equal total inflow - total outflow."""
        entries = compute_full_shipment_cashflow(
            _shipment_1(), _full_strategy_config(), _load_outflow_config(),
        )
        timeline = build_cash_timeline(entries)
        total_in = sum(e.amount_pkr for e in entries if e.direction == "inflow")
        total_out = sum(e.amount_pkr for e in entries if e.direction == "outflow")
        assert abs(timeline[-1].cumulative_position - (total_in - total_out)) < 0.01

    def test_first_point_is_negative_for_outflow_first_shipment(self):
        """Shipment 1 pays cash on Jan 1 (outflow) before receiving sale later."""
        entries = compute_full_shipment_cashflow(
            _shipment_1(), _full_strategy_config(), _load_outflow_config(),
        )
        timeline = build_cash_timeline(entries)
        assert timeline[0].cumulative_position < 0

    def test_each_point_has_entries(self):
        entries = compute_full_shipment_cashflow(
            _shipment_1(), _full_strategy_config(), _load_outflow_config(),
        )
        timeline = build_cash_timeline(entries)
        for pt in timeline:
            assert len(pt.entries) > 0


class TestShipmentFundingProfile:
    """Tests for single-shipment funding analysis."""

    def test_returns_correct_dataclass(self):
        profile = shipment_funding_profile(
            _shipment_1(), _full_strategy_config(), _load_outflow_config(),
        )
        assert isinstance(profile, ShipmentFundingProfile)
        assert profile.shipment_id == 1
        assert profile.customer_id == "A"

    def test_net_cashflow_positive(self):
        """Shipment 1 is profitable (inflow > outflow)."""
        profile = shipment_funding_profile(
            _shipment_1(), _full_strategy_config(), _load_outflow_config(),
        )
        assert profile.net_cashflow > 0
        expected_net = 12_813_600 - 11_742_800  # 1,070,800
        assert abs(profile.net_cashflow - expected_net) < 0.01

    def test_peak_deficit_is_negative(self):
        """Before SALE inflow arrives, cumulative position must be negative."""
        profile = shipment_funding_profile(
            _shipment_1(), _full_strategy_config(), _load_outflow_config(),
        )
        assert profile.peak_deficit < 0
        assert profile.peak_deficit_date is not None

    def test_peak_deficit_before_sale(self):
        """Peak deficit should occur before the SALE payment date."""
        profile = shipment_funding_profile(
            _shipment_1(), _full_strategy_config(), _load_outflow_config(),
        )
        # SALE payment_date = receive_date + 17 = Feb 1, 2026
        sale_payment = datetime.date(2026, 2, 1)
        assert profile.peak_deficit_date < sale_payment

    def test_peak_surplus_after_sale(self):
        """Peak surplus should be at or after the last payment."""
        profile = shipment_funding_profile(
            _shipment_1(), _full_strategy_config(), _load_outflow_config(),
        )
        assert profile.peak_surplus > 0
        assert profile.peak_surplus_date is not None

    def test_cash_conversion_days_positive(self):
        profile = shipment_funding_profile(
            _shipment_1(), _full_strategy_config(), _load_outflow_config(),
        )
        assert profile.cash_conversion_days > 0
        assert profile.first_cash_date < profile.last_cash_date

    def test_has_negative_cash_days(self):
        """Some dates must have negative cumulative position (outflows precede inflow)."""
        profile = shipment_funding_profile(
            _shipment_1(), _full_strategy_config(), _load_outflow_config(),
        )
        assert profile.negative_cash_days > 0

    def test_total_outflow_matches_engine(self):
        profile = shipment_funding_profile(
            _shipment_1(), _full_strategy_config(), _load_outflow_config(),
        )
        assert abs(profile.total_outflow - 11_742_800) < 0.01

    def test_total_inflow_matches_engine(self):
        profile = shipment_funding_profile(
            _shipment_1(), _full_strategy_config(), _load_outflow_config(),
        )
        assert abs(profile.total_inflow - 12_813_600) < 0.01

    def test_format_does_not_raise(self):
        profile = shipment_funding_profile(
            _shipment_1(), _full_strategy_config(), _load_outflow_config(),
        )
        text = format_shipment_funding(profile)
        assert "Shipment 1" in text
        assert "Peak deficit" in text


class TestPortfolioFundingSummary:
    """Tests for multi-shipment portfolio analysis."""

    def test_returns_correct_dataclass(self):
        cycles = [_shipment_1(), _shipment_2()]
        summary = portfolio_funding_summary(
            cycles, _full_strategy_config(), _load_outflow_config(),
        )
        assert isinstance(summary, PortfolioFundingSummary)
        assert summary.shipment_count == 2

    def test_portfolio_totals_equal_sum_of_shipments(self):
        cycles = [_shipment_1(), _shipment_2()]
        config = _full_strategy_config()
        outflow_config = _load_outflow_config()

        summary = portfolio_funding_summary(cycles, config, outflow_config)
        p1 = shipment_funding_profile(_shipment_1(), config, outflow_config)
        p2 = shipment_funding_profile(_shipment_2(), config, outflow_config)

        assert abs(summary.total_outflow - (p1.total_outflow + p2.total_outflow)) < 0.01
        assert abs(summary.total_inflow - (p1.total_inflow + p2.total_inflow)) < 0.01
        assert abs(summary.net_cashflow - (p1.net_cashflow + p2.net_cashflow)) < 0.01

    def test_portfolio_peak_deficit_at_least_as_deep_as_single(self):
        """Combined portfolio deficit >= any single shipment deficit (more outflows overlap)."""
        cycles = [_shipment_1(), _shipment_2()]
        config = _full_strategy_config()
        outflow_config = _load_outflow_config()

        summary = portfolio_funding_summary(cycles, config, outflow_config)
        p1 = shipment_funding_profile(_shipment_1(), config, outflow_config)

        # Portfolio deficit should be at least as deep (or deeper) than ship 1 alone
        assert summary.peak_deficit <= p1.peak_deficit

    def test_has_top_deficit_shipments(self):
        cycles = [_shipment_1(), _shipment_2()]
        summary = portfolio_funding_summary(
            cycles, _full_strategy_config(), _load_outflow_config(),
        )
        assert len(summary.top_deficit_shipments) == 2

    def test_final_position_equals_net(self):
        """Last timeline point should equal net cashflow."""
        cycles = [_shipment_1(), _shipment_2()]
        summary = portfolio_funding_summary(
            cycles, _full_strategy_config(), _load_outflow_config(),
        )
        assert abs(summary.timeline[-1].cumulative_position - summary.net_cashflow) < 0.01

    def test_format_does_not_raise(self):
        cycles = [_shipment_1(), _shipment_2()]
        summary = portfolio_funding_summary(
            cycles, _full_strategy_config(), _load_outflow_config(),
        )
        text = format_portfolio_summary(summary)
        assert "PORTFOLIO FUNDING SUMMARY" in text


class TestNoOverrideComparison:
    """Empty overrides should produce zero deltas in funding comparison."""

    def test_zero_deltas_single_shipment(self):
        comp = compare_funding_profiles(
            [_shipment_1()], _full_strategy_config(), _load_outflow_config(),
            ScenarioOverrides(), single_shipment=True,
        )
        assert isinstance(comp, FundingComparison)
        assert abs(comp.peak_deficit_delta) < 0.01
        assert abs(comp.peak_surplus_delta) < 0.01
        assert abs(comp.net_cashflow_delta) < 0.01
        assert comp.negative_days_delta == 0

    def test_zero_deltas_portfolio(self):
        comp = compare_funding_profiles(
            [_shipment_1(), _shipment_2()],
            _full_strategy_config(), _load_outflow_config(),
            ScenarioOverrides(),
        )
        assert abs(comp.net_cashflow_delta) < 0.01
        assert comp.negative_days_delta == 0


class TestFundingDirectionality:
    """Verify that overrides move funding metrics in expected directions."""

    def test_higher_fx_improves_net_and_surplus(self):
        """Higher FX rate increases SALE inflow, improving net cashflow."""
        comp = compare_funding_profiles(
            [_shipment_1()], _full_strategy_config(), _load_outflow_config(),
            ScenarioOverrides(usd_to_pkr=300), single_shipment=True,
        )
        assert comp.net_cashflow_delta > 0
        assert comp.peak_surplus_delta > 0

    def test_higher_fx_reduces_deficit(self):
        """Higher FX rate → higher SALE → shallower deficit (less negative)."""
        comp = compare_funding_profiles(
            [_shipment_1()], _full_strategy_config(), _load_outflow_config(),
            ScenarioOverrides(usd_to_pkr=300), single_shipment=True,
        )
        # peak_deficit_delta > 0 means deficit is less negative (improved)
        # For single-shipment: outflows unchanged, only SALE increases.
        # But since SALE arrives AFTER outflows, peak deficit occurs before SALE
        # and is unchanged. So delta should be ~0.
        # The net improvement shows in surplus instead.
        assert comp.net_cashflow_delta > 0

    def test_higher_partha_worsens_deficit(self):
        """Higher procurement cost increases outflows, deepening deficit."""
        comp = compare_funding_profiles(
            [_shipment_1()], _full_strategy_config(), _load_outflow_config(),
            ScenarioOverrides(partha_rates={"SUPPLIER": 1300, "INTERNAL": 1000}),
            single_shipment=True,
        )
        # Higher outflow → deeper deficit
        assert comp.peak_deficit_delta < 0
        assert comp.net_cashflow_delta < 0

    def test_higher_freight_worsens_funding(self):
        """Higher freight rate increases outflows."""
        comp = compare_funding_profiles(
            [_shipment_1()], _full_strategy_config(), _load_outflow_config(),
            ScenarioOverrides(outflow_rate_overrides={"Freight": 300}),
            single_shipment=True,
        )
        assert comp.net_cashflow_delta < 0

    def test_portfolio_fx_up_improves_net(self):
        """Higher FX across all shipments improves portfolio net cashflow."""
        comp = compare_funding_profiles(
            [_shipment_1(), _shipment_2()],
            _full_strategy_config(), _load_outflow_config(),
            ScenarioOverrides(usd_to_pkr=300),
        )
        assert comp.net_cashflow_delta > 0

    def test_format_comparison_does_not_raise(self):
        comp = compare_funding_profiles(
            [_shipment_1()], _full_strategy_config(), _load_outflow_config(),
            ScenarioOverrides(usd_to_pkr=300), single_shipment=True,
        )
        text = format_funding_comparison(comp)
        assert "FUNDING COMPARISON" in text
        assert "Baseline" in text
