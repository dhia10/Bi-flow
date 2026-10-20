from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.schemas.models import OntologyChunk


class OntologyChunker:
    """
    Deconstructs enterprise domain knowledge and data dictionaries into
    fine-grained, queryable OntologyChunk objects for dense and lexical indexing.
    """

    def __init__(self, kb_dir: Optional[Path] = None) -> None:
        self.kb_dir = Path(kb_dir) if kb_dir else Path(__file__).resolve().parents[2] / "bi_pipeline" / "knowledge_base"

    def chunk_all_domains(self) -> List[OntologyChunk]:
        chunks: List[OntologyChunk] = []
        if not self.kb_dir.is_dir():
            return chunks

        for file_path in sorted(self.kb_dir.glob("*.json")):
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            domain_id = data.get("domain_id", file_path.stem)
            domain_name = data.get("domain_name", domain_id)
            description = data.get("description", "")
            keywords = data.get("keywords", [])
            mapping_rules = data.get("column_mapping_rules", {})

            # 1. Chunk KPI templates
            for kpi in data.get("kpi_templates", []) + data.get("universal_kpi_templates", []):
                chunk_id = f"{domain_id}::{kpi['id']}"
                req_roles = kpi.get("required_roles", [])
                
                # Composite text enriched for dense embedding + lexical matching
                content_parts = [
                    f"Domain: {domain_name}",
                    f"Metric: {kpi.get('name', '')}",
                    f"Description: {kpi.get('description', '')}",
                    f"Required Semantic Roles: {' '.join(req_roles)}",
                    f"Keywords: {' '.join(keywords)}",
                ]
                for role in req_roles:
                    if role in mapping_rules:
                        content_parts.append(f"Synonyms for {role}: {' '.join(mapping_rules[role])}")

                chunks.append(
                    OntologyChunk(
                        chunk_id=chunk_id,
                        domain=domain_id,
                        entity_type="kpi",
                        name=kpi.get("name", ""),
                        content=" | ".join(content_parts),
                        sql_template=kpi.get("sql_template"),
                        required_roles=req_roles,
                        unit=kpi.get("unit"),
                        category=kpi.get("category", "financial"),
                        metadata={
                            "source_file": file_path.name,
                            "template_id": kpi["id"],
                        },
                    )
                )

            # 2. Chunk dimensional templates
            for dim in data.get("dimensional_templates", []) + data.get("universal_dimensional_templates", []):
                chunk_id = f"{domain_id}::{dim['id']}"
                req_roles = dim.get("required_roles", [])
                content_parts = [
                    f"Domain: {domain_name}",
                    f"Dimension Breakdown: {dim.get('dimension_name', '')}",
                    f"Description: {dim.get('description', '')}",
                    f"Required Roles: {' '.join(req_roles)}",
                ]
                chunks.append(
                    OntologyChunk(
                        chunk_id=chunk_id,
                        domain=domain_id,
                        entity_type="dimension",
                        name=dim.get("dimension_name", dim["id"]),
                        content=" | ".join(content_parts),
                        sql_template=dim.get("sql_template"),
                        required_roles=req_roles,
                        category="dimensional",
                        metadata={"source_file": file_path.name, "template_id": dim["id"]},
                    )
                )

            # 3. Chunk domain entity mapping rules
            if mapping_rules:
                for role, aliases in mapping_rules.items():
                    chunk_id = f"{domain_id}::rule::{role}"
                    content = f"Domain: {domain_name} | Concept: {role} | Known Column Aliases: {' '.join(aliases)}"
                    chunks.append(
                        OntologyChunk(
                            chunk_id=chunk_id,
                            domain=domain_id,
                            entity_type="mapping_rule",
                            name=f"Role: {role}",
                            content=content,
                            required_roles=[role],
                            category="ontology",
                            metadata={"aliases": aliases},
                        )
                    )

        return chunks
