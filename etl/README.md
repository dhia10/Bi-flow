# intelligent_etl_agent — BI-FLOW ETL Agent (V4: Star + Snowflake)

**A self-checking ETL / analytical-modeling agent with an optional local LLM, validated Star/Snowflake modeling, and automatically generated PNG/SVG diagrams.**

Its goal is to make **evidence-based ETL decisions on unfamiliar tabular datasets**, not to memorize a collection of industries. It does not promise to infer every possible business rule from column names alone.

## Windows: install and run (exact commands)

1. Extract the ZIP. Open the **`intelligent_etl_agent`** folder containing `main.py` in VS Code.
2. Open **Terminal → New Terminal** (PowerShell). Run:

   ```powershell
   .\setup_windows.bat
   ```

3. Install Ollama from https://ollama.com (if not installed) and in a separate terminal run:

   ```powershell
   ollama pull qwen2.5:1.5b
   ollama serve
   ```

   **Important:** If Ollama is already serving, do NOT start another server. Running `ollama list` can check that the model is installed. Smaller Qwen is intentionally the default for limited GPU memory.

4. In the project terminal, run a **real LLM-enabled test**:

   ```powershell
   .\.venv\Scripts\python.exe main.py --example car_rental
   ```

   To test without the LLM (deterministic fallback only):

   ```powershell
   .\.venv\Scripts\python.exe main.py --example car_rental --no-llm
   ```

5. Inspect `data/output/car_rental/star_schema.png`, `etl_plan.json`, `etl_report.json`, and `handoff_manifest.json`.

## Run on YOUR input files

Put CSV / XLSX / JSON files **in `data/input/`**. This directory must contain only the tables for this run.

```powershell
.\.venv\Scripts\python.exe main.py --input data/input --output data/output/my_run
```

Optional alternative model: `--model qwen2.5:7b` (only if your hardware can run it). Or set `OLLAMA_MODEL` / `OLLAMA_BASE_URL` environment variables. Change no project code.

**Included regression examples:** `car_rental`, `logistics`, `restaurant`, `energy`, `hotel`, `retail`. Test one directly: `python main.py --example energy --no-llm`.

## NEW — Choose Star, Snowflake, or Auto (Windows PowerShell)

**The original Star Schema remains the default.** All previous commands work as before.

```powershell
# Original behavior — denormalized star model and star_schema.png
.\.venv\Scripts\python.exe main.py --example energy --schema star --no-llm

# NEW: physically normalized dimension hierarchy and snowflake_schema.png
.\.venv\Scripts\python.exe main.py --example energy --schema snowflake --no-llm

# NEW: select Snowflake only when validated dimension-to-dimension joins exist
.\.venv\Scripts\python.exe main.py --example energy --schema auto --no-llm

# Test your own files, keeping each run in a separate output folder
.\.venv\Scripts\python.exe main.py --input data/input --output data/output/my_snowflake_test --schema auto
```

Or double-click `run_snowflake_test.bat` for a no-LLM demonstration.

**Energy example — actual physical Snowflake Schema:**

```
fact_electricity_readings --meter_id--> dim_meter --tariff_code--> dim_tariff
                |
                +--date_key--> dim_date
```

`tariff_code` remains in `dim_meter` instead of being copied into the fact table. The fact can still contain `estimated_energy_cost`, calculated during ETL by safely reading the required lookup values. In **Star mode**, `tariff_code` is projected into the fact table, matching the earlier version.

**Files created:** `snowflake_schema.png` and `snowflake_schema.svg` when a validated hierarchy exists. For Star, `star_schema.png` and `star_schema.svg`. The result and reports include `schema_type`, `schema_reason`, and `relationship_mapping`, which now represents physical dimension-to-dimension links for Snowflake.

**Important:** Selecting `--schema snowflake` never invents a hierarchy. If the input has no validated dimension-to-dimension relationship, the agent produces a Star Schema (or fact-only schema), records the reason, and keeps the correct diagram. The **Auto** mode uses this same evidence-based decision rule. This is not a general-purpose star/snowflake performance optimizer; the choice follows visible relationship structure and keeps the single-fact-per-run scope.

### Updating an older installation

**Recommended:** back up your current `intelligent_etl_agent` folder and replace it with the complete V4 project ZIP. Your CSV input files and old output runs should be copied into the new project afterward as needed.

Alternatively, extract `intelligent_etl_agent_snowflake_patch.zip` into the **existing** `intelligent_etl_agent` root, allowing updated Python files to overwrite the corresponding ones. The patch also adds tests, this README and `run_snowflake_test.bat`. Restart the Python process after replacing files.

## V4 domain recognition upgrade (October 2026)

The new `etl_agent/domain_detector.py` adds **open-vocabulary domain classification**:

- Sends a bounded summary of **all input tables**, not just the selected fact/joins, to the local LLM.
- Merges synonyms and parent/subdomain labels (for example, `online_retail_orders` + `retail` → `retail` / `ecommerce`).
- Allows **new domain names** when supported by at least two real source identifiers or clear schema name evidence, rather than restricting classification to the old keyword list.
- Checks evidence against real table/column names, preserves uncertainty on unsupported claims, and avoids inventing numeric confidence probabilities.
- Outputs `domain`, `domain_subdomain`, `domain_source`, `domain_confidence`, `domain_evidence`, and `business_processes` in the plan, report and handoff.

**Test on any input dataset:**

```powershell
.\.venv\Scripts\python.exe main.py --input data/input --output data/output/domain_test --schema auto
```

Requires local Ollama running for recognition of **unfamiliar** domains. `--no-llm` uses the existing limited deterministic cues; it cannot claim to recognize all industries. Inspect `data/output/domain_test/etl_report.json` for the evidence, and `llm_debug.json` for the actual model interactions.

**Scope:** This patch improves domain understanding **only**. It does not add multi-fact / Galaxy Schema modeling or solve Olist's many-to-many or differing-grain joins; a result with domain `retail` can still be an incomplete warehouse. No system can guarantee classification of *every* ambiguous CSV.

## What this agent actually does

1. **Data input & profiling** — loads CSV/XLSX/JSON; collects nulls, types, bounded sample values, unique ratios, date parsing evidence. Duration columns such as `rental_days` are **not** treated as dates.
2. **Discover relationships** — checks key names, sample FK coverage, and unique lookup keys. Non-unique lookup keys are NOT auto-joined. Joins are many-to-one verified at execution. Supports up to two intermediate lookup hops for snowflake data.
3. **LLM semantic analyst** — Qwen receives the profiles (not full datasets); suggests a domain and justified measures. A domain label is a *hint*, not a hard-coded required enum. If Qwen and schema evidence conflict, the agent reports `unknown` instead of silently overriding.
4. **Self-correction** — parses typed JSON, rejects invented arithmetic, gives the LLM explicit feedback for up to 3 semantic attempts, and uses validated rules if Ollama is unavailable. `measure_sources` distinguishes `llm_validated` from `validated_rule_fallback`.
5. **Guarded ETL** — joins only when needed for accepted measures or for an indirect FK, never multiplies fact rows silently; preserves source fact grain; creates fact/dim/date tables and estimated measures only when compatible units are evident. In Snowflake mode it retains true dimension-to-dimension keys instead of forcing all dimensional keys into the fact.
6. **Post-execution validation** — tests fact grain, derived-column existence, dimension uniqueness, FK coverage and nulls; separates blocking errors from warnings.
7. **Warehouse & visualization** — saves CSVs, DuckDB if installed, or a clearly labeled SQLite fallback; automatically creates actual `star_schema.png`/`star_schema.svg` or `snowflake_schema.png`/`snowflake_schema.svg` using **Matplotlib (no external Graphviz executable required on Windows)**. Diagrams mark primary/foreign keys, column types, and measures, based on output schema metadata.
8. **BI-FLOW handoff** — writes `etl_report.json`, `etl_plan.json`, `profile.json`, `llm_debug.json`, `lineage.json`, `handoff_manifest.json`, `state.json`.

## Important safety and limitations

- An LLM can propose **invalid assumptions**. Only supported, unit-consistent multiplication of a quantity/duration/usage field by an appropriate per-unit rate is **automatically executed**. Arbitrary arithmetic and unfamiliar pricing rules require human approval and further implementation. `estimated_...` columns are **not guaranteed invoices** (taxes, price history, discounts, minimum fees may matter).
- The ETL fact is currently **one selected central transaction table per run**, with up to two lookup hops. Complex systems containing several legitimate facts, slowly changing dimensions, nested JSON objects, and many-to-many bridge tables need a separate modeling workflow. If no trustworthy dimensions are detected, the diagram is correctly labeled **fact only**, not a valid star.
- This is an **in-memory Pandas implementation**. Massive Kaggle data should be sampled first; true out-of-core / Spark-scale operations are not yet implemented.
- Do not send sensitive columns to a remote model without approval. Default Ollama is local at `localhost:11434`; the LLM receives samples of rows (up to 4 samples/field) and metadata.
- **DuckDB:** `setup_windows.bat` installs `duckdb`. If it is not installed, the current engine explicitly uses `sqlite_fallback`. Check `saved.database_engine` in the result.
- Without Ollama or with an unsupported LLM answer, the agent still runs using deterministic, explained, safe fallback logic. A fallback-generated measure is not evidence of LLM understanding.

## Testing

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests
```

These tests use a **fake Qwen client** to test feedback and rejection paths; they do not prove your actual local Qwen answers correctly. Test with `python main.py --example car_rental` to observe real Ollama behavior via `llm_debug.json`.

## Files by responsibility

| File | Responsibility |
|---|---|
| `main.py` | CLI (supports `--input`, `--output`, `--example`, `--no-llm`, `--model`) |
| `etl_agent/profiler.py` | Input loading and bounded semantic profiling |
| `etl_agent/relationships.py` | Conservative FK→unique-key discovery and safe join tree |
| `etl_agent/semantic.py` | Domain evidence and generalized unit-compatible candidates |
| `etl_agent/planner.py` | Qwen reasoning, schema validation, corrective feedback, safe fallback |
| `etl_agent/llm_client.py` | Local Ollama Qwen client (JSON schema + retries) |
| `etl_agent/executor.py` | Pandas fact grain, selective joins, transformations, date/dim tables |
| `etl_agent/validator.py` | Post-ETL quality checks and warnings |
| `etl_agent/schema_visualizer.py` | PNG/SVG rendering of the *actual* chosen schema |
| `etl_agent/storage.py` | DuckDB/SQLite and CSV outputs |
| `etl_agent/reporter.py` | Audits, lineage, KPI handoff |
| `etl_agent/state_manager.py` | Shared state: running / success / failed |
| `app.py` | Optional FastAPI connector to n8n/other BI-FLOW components |

## API

Run `run_api.bat`, then go to `http://127.0.0.1:8000/docs`. `POST /etl/run` accepts uploaded files and persists output under `data/output/api_runs/<run_id>/`. `GET /health` checks server availability. For large files, prefer CLI.
