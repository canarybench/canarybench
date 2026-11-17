# `canarybench`

**Contamination-free deterministic AI evaluation harness for compliance, financial, medical, and regulatory extraction agents.**

Built on a **4-Engine × 5-Pack** horizontal/vertical matrix, `canarybench` pairs zero-LLM `decimal.Decimal` (`ROUND_HALF_UP`) oracles with multimodal PDF, XML/JSON wire, OCR-noise, and contradictory-context traps—minted weekly with cryptographic canary watermarks so benchmarks never leak into pretraining sets.

---

## Why `canarybench`?

Static public benchmarks saturate and leak into foundation-model pretraining data within weeks. Meanwhile, enterprise compliance agents fail silently on stateful ledger math, multi-source document overrides, statutory exclusion cascades, and strict wire schemas.

`canarybench` eliminates both blind spots:
- **Zero-LLM Oracles:** Ground truth is computed deterministically via `decimal.Decimal` (`ROUND_HALF_UP`) and statutory/contractual rule trees—never LLM-as-a-judge.
- **Strict Float Rejection (`StrictDecimal`):** Rejects Python `float`, `bool`, `NaN`, and `Infinity`; all monetary and rate fields serialize as fixed-point decimal strings.
- **4 Horizontal Failure-Archetype Engines (`canarybench.engines`):**
  1. **`ledger-math`** — Stateful financial, tax-bucket, carry-forward, penny-rounding, pro-rata, compounding CPI, and Art. 91 FX arithmetic.
  2. **`doc-reconcile`** — Multi-source contradiction resolution (authoritative CMR/amendment/endorsement vs. draft emails) and OCR/NBSP/ZWSP normalization.
  3. **`rule-triage`** — Hierarchical classification, statutory threshold gating, exclusion cascades, and hard-fail anti-gaming guards.
  4. **`wire-protocol`** — Strict schema, code-list, CMS NPI Luhn, ICD-10-CM pointers, X12-837P JSON/XML, and EN 16931 UBL 2.1 validation.

---

## 5 Vertical Domain Packs (`canarybench.packs`)

| Pack ID | Domain & Regulatory Scope | Supported Engines | Public Teaser |
|---|---|---|---|
| `eu-vat-2027` | EU VAT Directive 2006/112/EC, Art. 141 triangulation, Art. 44/196 B2B services, Art. 138 CMR transport proof, 380/381 credit notes, Dir. 2020/285 SMEs, EN 16931 UBL 2.1 | `ledger-math`, `doc-reconcile`, `rule-triage`, `wire-protocol` | `public_25.jsonl` (25 traps) |
| `cre-lease` | Commercial Real Estate CAM reconciliation, 95% occupancy variable gross-up, CapEx/mgmt-fee caps, base-year expense stops, compounding CPI caps/floors, executed amendments | `ledger-math`, `doc-reconcile` | `public_10.jsonl` (10 traps) |
| `customs-cbam` | WTO GRI 1 / 3(b) / 3(c) BOM classification, FTA CTH / MaxNOM preferential origin, de minimis & <50t mass exemptions, EU CBAM embedded emissions & carbon credits | `rule-triage`, `ledger-math` | `public_10.jsonl` (10 traps) |
| `med-coding` | CMS NCCI PTP Column 1/2 bundling (CCMI `0` vs `1` + `-25`/`-59`/`XS`/`XU`), MUE unit caps, `80840` NPI Luhn, ICD-10-CM pointers, X12-837P JSON/XML validation | `rule-triage`, `wire-protocol` | `public_10.jsonl` (10 traps) |
| `claims-adjudication` | P&C 5-tier claim waterfall: policy period & retroactive cutoff, excluded perils & overlapping sub-limits, fixed/`% TIV` deductibles, co-insurance penalties, ACV vs. RCV holdbacks | `ledger-math`, `rule-triage` | `public_10.jsonl` (10 traps) |

---

## Architecture

```
+-----------------------------------------------------------------------+
|                       canarybench CLI (Typer + Rich)                  |
|  list-engines | list-packs [--engine] | run [--pack / --engine]       |
|  grade [--pack / --engine] | inspect (--validate-xml)                 |
+-----------------------------------+-----------------------------------+
                                    |
                                    v
+-----------------------------------------------------------------------+
|                     Core Harness (src/canarybench/core/)              |
|  - BaseEngine / BasePack ABCs & EngineRegistry / PackRegistry         |
|  - StrictDecimal Pydantic v2 schemas (rejects float/NaN/Inf)          |
|  - BenchmarkRunner (strict isolation: AgentAdapter never sees Truth)  |
+-------------------+-------------------------------+-------------------+
                    |                               |
                    v                               v
+-----------------------------------+   +-------------------------------+
|  4 Horizontal Engines             |   |  5 Vertical Domain Packs      |
|  - ledger-math   - doc-reconcile  |   |  - eu-vat-2027  - cre-lease   |
|  - rule-triage   - wire-protocol  |   |  - customs-cbam - med-coding  |
+-----------------------------------+   |  - claims-adjudication        |
                                        +-------------------------------+
```

---

## 3-Step Quickstart

### 1. Install
```bash
pip install canarybench
```

### 2. Discover engines/packs & inspect a scenario
```bash
canarybench list-engines
canarybench list-packs
canarybench list-packs --engine wire-protocol
canarybench inspect --pack eu-vat-2027 --scenario EU-VAT-0003 --validate-xml
canarybench inspect --pack med-coding --scenario MED-0001 --validate-xml
```

### 3. Run or grade benchmarks
```bash
# Single-pack run against any OpenAI-compatible endpoint
export OPENAI_API_KEY="sk-..."
canarybench run --pack eu-vat-2027 \
  --endpoint https://api.openai.com/v1 \
  --model gpt-4.1-mini \
  --output report.json \
  --fail-under 0.85

# Cross-pack horizontal engine evaluation (runs all packs supporting ledger-math)
canarybench run --engine ledger-math --baseline-mock naive

# Combined pack + engine slice
canarybench run --pack cre-lease --engine doc-reconcile --baseline-mock naive

# Grade pre-computed offline predictions (JSON/JSONL)
canarybench grade --pack customs-cbam --predictions my_agent_preds.jsonl --verbose
```

Any hard-fail gate violation sets scenario `score = 0.0000` and `passed = False`, blocking zero-amount or default-category gaming across all 5 packs.

---

## Weekly Contamination-Free CI Streams (Team `$399/mo` vs. Lab `$899/mo`)

Running public teasers in local dev? For production CI/CD regression gates, subscribe to weekly deterministic drops minted every Sunday at 02:00 UTC with per-subscriber O(1) RFC 9562 UUIDv8 / PDF metadata / cosmetic-seed canary attribution:

- **Team Tier (`$399/mo` — Single-Pack CI Gate):**
  - **500 fresh, watermarked traps/week** for your chosen domain pack (`private/drops/team/<pack>/<drop_id>/drop.jsonl`).
  - Ideal for vertical AP/AR, CRE, customs, medical billing, or P&C claims teams (`canarybench grade --pack <slug> --dataset drops/latest/drop.jsonl --fail-under 0.95`).
- **Lab Tier (`$899/mo` — Full 4-Engine × 5-Pack Matrix):**
  - **500+ fresh, watermarked traps/week** distributed deterministically across **all 5 packs and all 4 failure-archetype engines** (`private/drops/lab/<drop_id>/packs/<pack>/drop.jsonl`).
  - Ideal for foundation-model labs and multi-agent platform teams benchmarking horizontal reasoning across ledger math, doc reconciliation, rule triage, and wire protocols.

---

## Development

```bash
uv venv --python 3.12 .venv
uv pip install -e ".[dev]"
.venv/bin/pytest -v
.venv/bin/ruff check .
.venv/bin/mypy --strict src private tests
.venv/bin/python -m build
```
