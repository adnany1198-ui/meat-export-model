# STATUS.md — Project State Report

*Last updated after commit `5aa0a63` (2026-03-09)*

## Purpose

Extract the financial logic of a complex Google Sheets livestock export model into a transparent, testable Python rules engine. The goal is **auditability**: every number the spreadsheet produces should be reproducible from explicit inputs and rules in code.

## Architecture

```
Google Sheet (live)
      │
      ▼
export_fixtures.py ──► tests/fixtures/*.json  (27 fixture files, point-in-time snapshot)
                              │
                              ▼
                     validate_all_shipments.py
                              │
                      ┌───────┴───────┐
                      ▼               ▼
              safi_engine/        cashflow_master.json
              engine.py           (expected output)
              cycle.py                    │
              config.py                   │
                      │                   │
                      ▼                   ▼
              computed entries ◄── compare ──► expected rows
                                     │
                                     ▼
                             VALIDATION REPORT
```

### File inventory

| File | Role |
|---|---|
| `connect_sheets.py` | Connects to live Google Sheet via service account, lists worksheets |
| `export_fixtures.py` | Exports every worksheet as JSON to `tests/fixtures/` |
| `safi_engine/__init__.py` | Empty package init |
| `safi_engine/config.py` | `StrategyConfig` dataclass + `PricingTier`, `CreditDays`, `MonthlyTonnage` dataclasses |
| `safi_engine/cycle.py` | `ShipmentCycle` dataclass — one row of the Cycle Detail sheet |
| `safi_engine/engine.py` | `compute_shipment_cashflow()` — rules engine for per-shipment outflows. Also defines `LedgerEntry` |
| `safi_engine/ledger.py` | `build_ledger()` — converts the `shipment_1.json` fixture into flat ledger dicts. Not used by the validation pipeline |
| `validate_all_shipments.py` | Full validation: loads all fixtures, runs engine for all 213 shipments, compares against spreadsheet output |
| `reference/VALIDATION_REPORT.GS` | Shell commands that were used to save the GAS source (not actual GAS code — see note below) |
| `requirements.txt` | Python dependencies (gspread + auth libraries) |
| `.gitignore` | Excludes credentials, pycache, venv |

### Test inventory

| Test file | Tests | What it validates |
|---|---|---|
| `tests/test_engine.py` | 8 | Outflow computation for shipment 1 — totals, counts, dates, amounts |
| `tests/test_ledger.py` | 4 | `build_ledger()` against shipment_1.json fixture — totals, dates, credit days |
| `tests/test_validation.py` | 11 | Full 213-shipment validation, multi-shipment outflows, SALE pricing across months |

**Total: 23 tests, all passing.**

### Fixture inventory

**Actually used by code (5 files):**

| Fixture | Used by | Contains |
|---|---|---|
| `cycle_detail_raw.json` | `validate_all_shipments.py` | 2D grid of all 213 shipment cycle rows |
| `cashflow_master.json` | `validate_all_shipments.py` | 3434 rows — the spreadsheet's computed cashflow output (expected values) |
| `outflow_config.json` | `engine.py`, `validate_all_shipments.py` | 20 cost items with rates, timing, model applicability |
| `strategy_control_raw.json` | `validate_all_shipments.py` | 2D grid with tonnage targets, pricing tiers, credit terms, FX rate |
| `shipment_1.json` | `test_ledger.py` | Pre-built fixture for shipment 1 only (cycle + cashflow rows) |

**Not used (22 files):** `cashflow_summary_customer.json`, `cashflow_summary_master.json`, `control.json`, `control_raw.json`, `customer_dashboard.json`, `customer_payment_ranges.json`, `customer_tonnage.json`, `cycle_calendar.json`, `cycle_detail.json`, `days.json`, `debug_weightengine.json`, `executive_dashboard.json`, `month_month.json`, `monthly_audit.json`, `monthly_dashboard.json`, `monthly_procurement_plan.json`, `payment_permutations.json`, `payment_rules.json`, `permutations.json`, `strategy_control.json`, `validation_report.json`, `working_capital_analysis.json`

## What has been implemented

### Outflow engine (`engine.py`)
- **Procurement cost (Partha):** `partha_rate × weight_kg_net`, fires on `CASH_DATE`
- **14 per-kg cost items:** each item's `rate × weight_kg_net`, timed to `SLAUGHTER_START`, `SLAUGHTER_END`, or `SLAUGHTER_END+1`
- Works for both SUPPLIER and INTERNAL procurement models

### SALE inflow engine (`validate_all_shipments.py`)
- **Amount:** `weight × price_usd_per_kg × usd_to_pkr`
- **Event date:** `PK_RECEIVE_DATE` from cycle detail
- **Credit days:** `floor(avg_days)` from strategy control Section 4
- **Price lookup:** `ceil(avg_days)` mapped against pricing tiers

### Validation pipeline
- Parses all 213 shipments from raw fixtures
- Computes 16 cashflow rows per shipment (15 outflows + 1 SALE inflow)
- Compares amounts (within 0.02 PKR tolerance), event dates, and payment dates against spreadsheet

## What has been validated

- **213/213 shipments produce cashflow rows matching the spreadsheet** across amounts, event dates, and payment dates
- Both SUPPLIER (majority) and INTERNAL procurement models
- Sale pricing at 5.70/5.80/5.90 USD/kg tiers validated across all 12 months
- Credit days validated: 17d (Jan) → 11d (Dec), matching strategy control Section 4
- Outflow timing: CASH_OUT, SLAUGHTER_START, SLAUGHTER_END, SLAUGHTER_END+1 all produce correct dates

## Known assumptions and hardcoded values

| Item | Location | Value | Issue |
|---|---|---|---|
| Partha rates | `engine.py` line 55, `validate_all_shipments.py` line 87, `test_engine.py` line 37 | SUPPLIER=1110, INTERNAL=1000 | Hardcoded in 3 places. Source not traced to any fixture. These rates are not in `outflow_config.json` or `strategy_control_raw.json`. |
| Cycle detail column indices | `validate_all_shipments.py` lines 40-50 | `row[0]`, `row[2]`, `row[8]`, etc. | Positional indexing into raw 2D grid. Fragile — breaks if spreadsheet columns change. |
| Strategy control row indices | `validate_all_shipments.py` lines 80-84 | `raw[26]`, `raw[48:60]`, `raw[21:25]` | Hardcoded row positions for USD/PKR, credit terms, pricing tiers. |
| Float tolerance | `validate_all_shipments.py` line 276 | `< 0.02` | 13 shipments have 0.01 PKR rounding diffs. Tolerated but not root-caused. |
| `PROCUREMENT_SUPPLIER` → `Partha` name mapping | `validate_all_shipments.py` lines 253-256 | String replacement | The spreadsheet uses `PROCUREMENT_SUPPLIER`/`PROCUREMENT_INTERNAL` but the engine uses `Partha`. |

## Structural issues found

1. **`config.py` defines dataclasses that are not used.** `StrategyConfig` has fields for `monthly_tonnage`, `pricing_tiers`, `customer_credit_days`, `supplier_credit_days` — all left empty. `validate_all_shipments.py` defines its own `CreditTerms` and `PricingTier` classes and returns them as a separate tuple alongside `StrategyConfig`.

2. **`ledger.py` is an orphan.** It converts `shipment_1.json` into ledger dicts, but this code path is not used by the validation pipeline. `test_ledger.py` tests it but it serves a different purpose from `engine.py`.

3. **`reference/VALIDATION_REPORT.GS` contains shell commands, not GAS code.** The filename suggests it should contain the Google Apps Script source but it's actually the terminal commands used to save/commit the file.

4. **SALE inflow logic lives in `validate_all_shipments.py`, not in the engine.** The `compute_sale_entry()` function should arguably be in `safi_engine/engine.py` alongside `compute_shipment_cashflow()`.

5. **26 Admin/Bank monthly rows in `cashflow_master.json` are not validated.** They have `Amount_PKR` of 15 and 39 (the raw per-kg rates, not actual computed amounts). The engine skips `MONTHLY` rate type items.

## Open gaps

1. **Monthly cost items (Admin, Bank) not computed or validated.** 26 rows in cashflow_master are ignored.
2. **No single entry point that produces a complete cashflow.** Outflows come from `engine.py`, SALE inflow from `validate_all_shipments.py` — no unified `compute_full_shipment()` function.
3. **Partha rates not loaded from data.** Must be traced to their source in the spreadsheet and loaded from fixtures.
4. **Cycle scheduling logic (how dates are derived) is not modelled.** The engine takes dates as inputs from the fixture. The *rules* that produce CASH_DATE, SLAUGHTER_DATE, etc. from START_DATE + lead times are still in the spreadsheet.
5. **No profit/margin computation.** The engine can compute outflows and sale inflows but doesn't compute net position, working capital, or any summary metrics.
6. **Fixture data is a static snapshot.** No mechanism to re-export and diff against a changed spreadsheet.
7. **22 fixture files are exported but never used.** Some may contain data needed for future features; others may be redundant.

## Recommended next 3 tasks

1. **Consolidate the engine.** Move `compute_sale_entry()` into `safi_engine/engine.py`. Make `load_strategy_config()` populate the existing `StrategyConfig` dataclass fields (remove duplicate local classes). Create a single `compute_full_shipment_cashflow()` that returns outflows + inflow.

2. **Extract partha rates from fixtures.** Find where 1110 and 1000 live in the spreadsheet (likely in `control_raw.json` or a section of `strategy_control_raw.json`), load them dynamically, and eliminate the hardcoded values.

3. **Model the cycle scheduling rules.** Given a START_DATE, procurement model, and customer parameters, compute all intermediate dates (CASH_DATE, SLAUGHTER_DATE, SLAUGHTER_END, KSA_SEND_DATE, PK_RECEIVE_DATE). This is the next major block of spreadsheet logic to extract.
