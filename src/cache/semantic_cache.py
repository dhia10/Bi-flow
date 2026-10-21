from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

log = logging.getLogger(__name__)


class SemanticCache:
    """
    Local SQLite semantic cache preventing redundant LLM and RAG executions
    for identical schema signatures and query parameters.
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        if db_path is None:
            self.db_path = Path(__file__).resolve().parents[2] / "data" / "cache" / "semantic_cache.sqlite"
        else:
            self.db_path = Path(db_path)

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS semantic_cache (
                    cache_key TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    hit_count INTEGER DEFAULT 1
                )
                """
            )
            con.commit()

    def _compute_key(
        self,
        schema_dict: Dict[str, str],
        sample_rows: Any,
        query: str,
    ) -> str:
        h = hashlib.sha256()
        # Canonicalize schema
        schema_str = json.dumps(sorted(schema_dict.items()), sort_keys=True, default=str)
        h.update(schema_str.encode("utf-8"))
        # Sample signature
        samples_str = json.dumps(str(sample_rows), sort_keys=True, default=str)
        h.update(samples_str.encode("utf-8"))
        # Query string
        h.update(query.strip().lower().encode("utf-8"))
        return h.hexdigest()

    def get(
        self,
        schema_dict: Dict[str, str],
        sample_rows: Any,
        query: str,
    ) -> Tuple[bool, Optional[Dict[str, Any]]]:
        cache_key = self._compute_key(schema_dict, sample_rows, query)
        try:
            with sqlite3.connect(self.db_path) as con:
                row = con.execute(
                    "SELECT payload_json, hit_count FROM semantic_cache WHERE cache_key = ?",
                    (cache_key,),
                ).fetchone()
                if row:
                    payload = json.loads(row[0])
                    con.execute(
                        "UPDATE semantic_cache SET hit_count = hit_count + 1 WHERE cache_key = ?",
                        (cache_key,),
                    )
                    con.commit()
                    log.info("Semantic cache HIT (key=%s, total_hits=%d)", cache_key[:10], row[1] + 1)
                    return True, payload
        except Exception as e:
            log.warning("Cache read failed: %s", e)

        return False, None

    def clear(self) -> int:
        """Clears all cached query results."""
        try:
            with sqlite3.connect(self.db_path) as con:
                cursor = con.execute("DELETE FROM semantic_cache")
                count = cursor.rowcount
                con.commit()
                log.info("Semantic cache cleared (%d entries removed)", count)
                return count
        except Exception as e:
            log.warning("Cache clear failed: %s", e)
            return 0

    def set(
        self,
        schema_dict: Dict[str, str],
        sample_rows: Any,
        query: str,
        payload: Dict[str, Any],
    ) -> None:
        cache_key = self._compute_key(schema_dict, sample_rows, query)
        try:
            with sqlite3.connect(self.db_path) as con:
                con.execute(
                    """
                    INSERT INTO semantic_cache (cache_key, payload_json, created_at, hit_count)
                    VALUES (?, ?, ?, 1)
                    ON CONFLICT(cache_key) DO UPDATE SET
                        payload_json = excluded.payload_json,
                        created_at = excluded.created_at
                    """,
                    (cache_key, json.dumps(payload, default=str), time.time()),
                )
                con.commit()
                log.debug("Semantic cache entry stored (key=%s)", cache_key[:10])
        except Exception as e:
            log.warning("Cache write failed: %s", e)
