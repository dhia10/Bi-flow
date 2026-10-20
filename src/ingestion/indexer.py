from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

from src.chunking.ontology_chunker import OntologyChunker
from src.lexical.bm25_index import BM25LexicalIndex
from src.schemas.models import OntologyChunk
from src.vector_db.vector_store import FAISSVectorStore

log = logging.getLogger(__name__)


class KnowledgeIndexer:
    """
    Offline/Online pipeline to load, chunk, and index domain ontologies
    into both FAISS dense and BM25 lexical search engines.
    """

    def __init__(
        self,
        kb_dir: Optional[Path] = None,
        embedding_version: str = "v1.2.0",
    ) -> None:
        self.chunker = OntologyChunker(kb_dir=kb_dir)
        self.vector_store = FAISSVectorStore(embedding_version=embedding_version)
        self.lexical_index = BM25LexicalIndex()
        self.chunks: List[OntologyChunk] = []

    def run_indexing(self) -> int:
        self.chunks = self.chunker.chunk_all_domains()
        self.vector_store.build_index(self.chunks)
        self.lexical_index.build_index(self.chunks)
        log.info("Indexed %d total ontology chunks across dense and lexical stores", len(self.chunks))
        return len(self.chunks)
