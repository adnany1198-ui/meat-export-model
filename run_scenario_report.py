"""CLI entry point for scenario comparison reports.

Usage:
    python run_scenario_report.py                  # all-shipment summary with default scenario
    python run_scenario_report.py --shipment 1     # single shipment comparison
    python run_scenario_report.py --fx 300         # override FX rate
    python run_scenario_report.py --partha 1200    # override SUPPLIER partha rate
    python run_scenario_report.py --freight 250    # override freight rate
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
from safi_engine.scenario_analysis import (
    compare_all_shipments,
    compare_shipment_scenario,
    format_aggregate_summary,
    format_shipment_comparison,
    scenario_summary,
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
    parser = argparse.ArgumentParser(description="Scenario comparison report")
    parser.add_argument("--shipment", type=int, help="Single shipment number to compare")
    parser.add_argument("--fx", type=float, default=None, help="Override USD/PKR rate (baseline: 281)")
    parser.add_argument("--partha", type=float, default=None, help="Override SUPPLIER partha rate (baseline: 1110)")
    parser.add_argument("--freight", type=float, default=None, help="Override freight rate (baseline: 212)")
    args = parser.parse_args()

    overrides = build_overrides(args)

    # Check if any override was specified
    has_overrides = any([
        overrides.usd_to_pkr is not None,
        overrides.partha_rates is not None,
        overrides.outflow_rate_overrides is not None,
    ])
    if not has_overrides:
        # Default demo scenario: FX 281 -> 300
        overrides = ScenarioOverrides(usd_to_pkr=300)
        print("(No overrides specified — using default demo: usd_to_pkr=300)\n")

    cycles = load_cycle_details()
    config = load_strategy_config()
    outflow_config = load_outflow_config()

    if args.shipment is not None:
        cycle = next((c for c in cycles if c.shipment_number == args.shipment), None)
        if cycle is None:
            print(f"Shipment {args.shipment} not found.")
            sys.exit(1)
        comp = compare_shipment_scenario(cycle, config, outflow_config, overrides)
        print(format_shipment_comparison(comp))
    else:
        comparisons = compare_all_shipments(cycles, config, outflow_config, overrides)
        summary = scenario_summary(comparisons, overrides)
        print(format_aggregate_summary(summary))


if __name__ == "__main__":
    main()
