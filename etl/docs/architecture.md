# Architecture and verification

`input → profile → unique-key relationship inference → hybrid semantic planner → bounded correction → selective Pandas execution → quality gate → DuckDB/SQLite → Star/Snowflake PNG/SVG visualization → handoff/state`

The LLM never runs arbitrary Python, generates SQL to execute, or edits the source data. It may suggest structured operations; automatic numeric formulas are limited to verified unit/rate pairs. The deterministic portion remains intentionally auditable.

The image is generated from final in-memory fact/dim DataFrames and validated relationship mappings. Matplotlib replaces Graphviz to avoid requiring the Windows Graphviz binary.

**Scope:** single fact per run, either the original Star projection or physically normalized Snowflake dimension links (up to two lookup hops), plain CSV/XLSX/flat JSON. A detected business-domain label is not a prerequisite for transformations. Complex OLAP schemas, streaming/incremental ingestion, formal unit ontologies and huge-dataset processing remain future extensions.

**Qwen contribution:** inspect `measure_sources`, `llm_debug.json` and `semantic_notes`. `validated_rule_fallback` means Python generated the measure, even if Qwen was unavailable; `llm_validated` means Qwen proposed a measure which validators approved.

**Warnings vs failures:** `state.json` records each run. Validation errors block storage. FK mismatches and null-heavy columns are warnings and should be investigated before KPI use.

## Star vs Snowflake physical semantics

- `--schema star` (default): project indirect dimension keys into the fact so every dimension is reachable directly from the fact; original behavior remains intact.
- `--schema snowflake`: if an input lookup table has a validated FK to another unique-key lookup table, keep that FK in the **parent dimension**, not in the fact. The fact keeps its original grain, and the ETL can still join selectively to calculate validated measures. Output relationship mappings refer to a `source_table` and `source_column` and a target `dimension_table` and `dimension_column`.
- `--schema auto`: use Snowflake for such hierarchies, else Star. No manufactured dimensions or links.
- The validator checks FK integrity on both fact→dimension and dimension→dimension links; diagrams are drawn only from the resulting actual tables.
- There is still one central fact per run. This does not support galaxy schemas, arbitrary hierarchy depths, or slowly changing dimension versioning.
