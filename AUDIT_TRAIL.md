# AUDIT_TRAIL.md — Auditability Assessment

*Last updated after commit `5aa0a63` (2026-03-09)*

## The auditability goal

For every PKR amount in the spreadsheet's cashflow output, a human should be able to answer:
- What inputs produced this number?
- What rule was applied?
- What assumptions were made?
- Can I reproduce it independently?

## What is transparent now

### Per-shipment outflow costs (15 line items)

For each of 213 shipments, the engine computes 15 outflow entries from explicit inputs:

```
PROCUREMENT (Partha):
  amount = partha_rate × weight_kg_net
  date   = CASH_DATE
  rule   = "procurement cost on cash out day"

PER_KG COST ITEMS (14 items: Slaughter, Animal_Trimming, Freight, etc.):
  amount = rate_per_kg × weight_kg_net
  date   = resolved from TIMING_EVENT (SLAUGHTER_START | SLAUGHTER_END | SLAUGHTER_END+1)
  rule   = "cost item fires on its timing event date"
```

Every `LedgerEntry` produced by the engine carries a `source_assumption` field that records the rate used (e.g. `"Freight=212/kg"`).

The 14 per-kg rates are loaded from `outflow_config.json`, which is a direct export of the spreadsheet's outflow config sheet. This is fully transparent — you can trace each rate back to its source.

### Per-shipment sale inflow (1 line item)

```
SALE:
  amount = weight_kg_net × price_usd_per_kg × usd_to_pkr
  date   = PK_RECEIVE_DATE
  credit = floor(avg_credit_days_for_month)
  price  = tier lookup using ceil(avg_credit_days_for_month)
```

The pricing tiers and credit terms are loaded from `strategy_control_raw.json` (Sections 2 and 4). The USD/PKR rate comes from Section 2 row 26. These are all traceable to the spreadsheet.

### Validation coverage

- **213/213 shipments match** the spreadsheet across all 16 cashflow rows per shipment
- Both SUPPLIER and INTERNAL procurement models covered
- Amounts, event dates, and payment dates all verified
- Maximum observed deviation: 0.01 PKR (float rounding, on amounts of ~17M PKR)

### Inputs that are traceable to source

| Input | Source | Loaded from |
|---|---|---|
| 14 outflow per-kg rates | Spreadsheet outflow config | `outflow_config.json` |
| Timing events per cost item | Spreadsheet outflow config | `outflow_config.json` |
| USD/PKR exchange rate | Strategy Control Section 2 | `strategy_control_raw.json` row 26 |
| Pricing tiers (USD/kg by credit bucket) | Strategy Control Section 2 | `strategy_control_raw.json` rows 21-24 |
| Customer credit terms (avg days by month) | Strategy Control Section 4 | `strategy_control_raw.json` rows 48-59 |
| Cycle dates and weights (per shipment) | Cycle Detail sheet | `cycle_detail_raw.json` |

## What is still opaque

### 1. Partha (procurement) rates — HARDCODED

The values `SUPPLIER=1110` and `INTERNAL=1000` PKR/kg are hardcoded in three places:
- `safi_engine/engine.py` (used at runtime)
- `tests/test_engine.py` (used in test setup)
- `validate_all_shipments.py` (used in validation)

**No one can tell from the code where these numbers come from.** They are not in `outflow_config.json` or `strategy_control_raw.json`. They may be in `control_raw.json` or somewhere else in the spreadsheet. Until they are traced and loaded from a fixture, this is an unauditable assumption.

### 2. Cycle date scheduling — NOT MODELLED

The engine takes dates as given inputs (CASH_DATE, SLAUGHTER_DATE, SLAUGHTER_END, KSA_SEND_DATE, PK_RECEIVE_DATE). It does not model *how* these dates are derived from:
- START_DATE
- LEAD_TIME
- PROC_TIME
- SLAUGHTER_DUR
- PAY_DAYS / PAY_LEAD

The scheduling rules are still inside the spreadsheet. If someone asks "why is shipment 42's slaughter date January 15th?", the engine cannot answer — it just reads the date from the fixture.

### 3. Monthly costs (Admin, Bank) — NOT COMPUTED

There are 26 rows in `cashflow_master.json` for Admin and Bank costs (2 per month × 13 months). These are `MONTHLY` rate type items in `outflow_config.json`. The engine skips them because it only processes `PER_KG` items.

The amounts in `cashflow_master.json` for these items appear to be the raw rates (15, 39) rather than computed amounts, which suggests the spreadsheet may handle them differently.

### 4. Weight allocation — NOT MODELLED

How does the model decide that shipment 1 gets 8000 kg while shipment 2 gets 4800 kg? The weights come from the cycle detail sheet, but the *rules* for allocating monthly tonnage targets across shipments and customers are not in the engine.

### 5. Summary and aggregation — NOT MODELLED

The spreadsheet contains multiple summary/dashboard sheets that aggregate cashflow data into monthly summaries, customer dashboards, working capital analysis, etc. None of this aggregation logic is in the engine. The 22 unused fixture files likely contain these outputs.

### 6. Permutation / scenario logic — NOT MODELLED

Files like `permutations.json`, `payment_permutations.json`, and `payment_rules.json` exist as fixtures but are not used. These likely represent the spreadsheet's scenario analysis capabilities (what-if on credit terms, pricing, etc.).

## The auditability chain today

```
CAN AUDIT:
  "Why is shipment 1's Freight cost 1,696,000 PKR?"
  → Because Freight rate is 212 PKR/kg (from outflow_config.json)
  → × 8000 kg (from cycle_detail_raw.json)
  → = 1,696,000 PKR
  → Fires on SLAUGHTER_END = 2026-01-05 (from cycle_detail_raw.json)
  ✓ Matches spreadsheet.

CAN AUDIT:
  "Why is shipment 1's SALE 12,813,600 PKR?"
  → Weight = 8000 kg (from cycle_detail_raw.json)
  → Jan-2026 avg credit days = 17.5 (from strategy_control_raw.json)
  → ceil(17.5) = 18, falls in 16-18 tier → 5.70 USD/kg
  → 8000 × 5.70 × 281 = 12,813,600 PKR
  → Payment date = PK_RECEIVE_DATE + floor(17.5) = 2026-01-15 + 17 = 2026-02-01
  ✓ Matches spreadsheet.

CANNOT AUDIT:
  "Why is shipment 1's procurement cost 8,880,000 PKR?"
  → Because partha_rate = 1110 PKR/kg × 8000 kg
  → But where does 1110 come from? → UNKNOWN (hardcoded)

CANNOT AUDIT:
  "Why does shipment 1 start on January 1st?"
  → The engine reads START_DATE from the fixture.
  → The scheduling logic is in the spreadsheet.

CANNOT AUDIT:
  "Why does customer A get 8000 kg in shipment 1?"
  → The engine reads WEIGHT_KG_NET from the fixture.
  → The weight allocation logic is in the spreadsheet.
```

## What needs to happen next

To make every output line fully explainable:

1. **Trace and load partha rates from fixtures** — eliminate the last hardcoded financial values
2. **Model cycle scheduling** — compute dates from START_DATE + timing rules, validate against fixture dates
3. **Model weight allocation** — compute shipment weights from monthly tonnage targets + customer counts
4. **Add monthly cost computation** — handle Admin/Bank monthly items
5. **Add profit/margin calculation** — outflows + inflows → net position per shipment, per month
6. **Build aggregation layer** — reproduce the summary sheets from individual shipment cashflows

Each step should follow the same pattern: implement the rule, validate against the spreadsheet fixture, and produce a test that proves the match.

---

## WHAT CHANGED IN THE LAST ITERATION

**Commit `5aa0a63`** — *Add full validation across all 213 shipments with SALE inflow engine*

**Files added:**
- `validate_all_shipments.py` — loads all fixtures, runs engine for every shipment, compares against cashflow_master, produces validation report
- `tests/test_validation.py` — 11 new tests for full validation, multi-shipment outflows, SALE pricing tiers

**New functionality:**
- SALE (inflow) computation: reverse-engineered the pricing rule (credit days → tier → USD/kg → PKR amount)
- Full fixture loading pipeline: parses `cycle_detail_raw.json` into 213 `ShipmentCycle` objects, loads strategy config from `strategy_control_raw.json`
- Comparison engine: matches computed entries against expected rows by (item, direction), checks amounts/dates/payment dates
- Human-readable report formatter

**Key discovery:**
- The pricing/credit day relationship is not a simple lookup — it uses `floor(avg_days)` for actual credit delay and `ceil(avg_days)` for pricing tier selection. This explains why Aug (avg=12.5) uses 5.80 USD/kg while Sep (avg=12.0) uses 5.90 USD/kg.

**Result:** Coverage expanded from 1 shipment to 213 shipments. Pass rate: 100%.
