"""CLI entry point for working capital / funding analysis reports.

Usage:
    python run_working_capital_report.py                      # all-shipment funding summary
    python run_working_capital_report.py --shipment 1         # single shipment profile
    python run_working_capital_report.py --compare            # baseline vs scenario comparison
    python run_working_capital_report.py --fx 300             # override FX rate
    python run_working_capital_report.py --partha 1200        # override SUPPLIER partha rate
    python run_working_capital_report.py --shipment 1 --compare --fx 300
"""

from __future__ import annotations

import argparse
import sys

from validate_all_shipments import (
    load_cycle_details,
    load_outflow_config,
    load_strategy_config,
)
from safi_engine.config import ScenarioOverrides
from safi_engine.working_capital import (
    compare_funding_profiles,
    format_funding_comparison,
    format_portfolio_summary,
    format_shipment_funding,
    portfolio_funding_summary,
    shipment_funding_profile,
)


def build_overrides(args: argparse.Namespace) -> ScenarioOverrides:
    """Build ScenarioOverrides from CLI arguments."""
    partha_rates = None
    if args.partha is not None:
        partha_rates = {"SUPPLIER": args.partha, "INTERNAL": 1000}

    outflow_overrides = None
    if args.freight is not None:
        outflow_overrides = {"Freight": args.freight}

    return ScenarioOverrides(
        usd_to_pkr=args.fx,
        partha_rates=partha_rates,
        outflow_rate_overrides=outflow_overrides,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Working capital / funding analysis")
    parser.add_argument("--shipment", type=int, help="Single shipment number")
    parser.add_argument("--compare", action="store_true", help="Compare baseline vs scenario")
    parser.add_argument("--fx", type=float, default=None, help="Override USD/PKR rate (baseline: 281)")
    parser.add_argument("--partha", type=float, default=None, help="Override SUPPLIER partha rate (baseline: 1110)")
    parser.add_argument("--freight", type=float, default=None, help="Override freight rate (baseline: 212)")
    args = parser.parse_args()

    overrides = build_overrides(args)
    has_overrides = any([
        overrides.usd_to_pkr is not None,
        overrides.partha_rates is not None,
        overrides.outflow_rate_overrides is not None,
    ])

    cycles = load_cycle_details()
    config = load_strategy_config()
    outflow_config = load_outflow_config()

    if args.compare:
        if not has_overrides:
            overrides = ScenarioOverrides(usd_to_pkr=300)
            print("(No overrides specified — using default demo: usd_to_pkr=300)\n")

        if args.shipment is not None:
            cycle = next((c for c in cycles if c.shipment_number == args.shipment), None)
            if cycle is None:
                print(f"Shipment {args.shipment} not found.")
                sys.exit(1)
            comp = compare_funding_profiles(
                [cycle], config, outflow_config, overrides, single_shipment=True,
            )
        else:
            comp = compare_funding_profiles(cycles, config, outflow_config, overrides)
        print(format_funding_comparison(comp))

    elif args.shipment is not None:
        cycle = next((c for c in cycles if c.shipment_number == args.shipment), None)
        if cycle is None:
            print(f"Shipment {args.shipment} not found.")
            sys.exit(1)
        ov = overrides if has_overrides else None
        profile = shipment_funding_profile(cycle, config, outflow_config, ov)
        print(format_shipment_funding(profile))

    else:
        ov = overrides if has_overrides else None
        summary = portfolio_funding_summary(cycles, config, outflow_config, ov)
        print(format_portfolio_summary(summary))


if __name__ == "__main__":
    main()
