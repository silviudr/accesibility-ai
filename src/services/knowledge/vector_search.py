"""Utility wrapper around the Chroma vector store for semantic retrieval."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import chromadb
from chromadb.utils import embedding_functions


class VectorSearcher:
    """Simple semantic search helper backed by a persistent Chroma collection."""

    def __init__(
        self,
        persist_dir: Path | str = Path("data/vectorstore"),
        collection_name: str = "accessible_services",
        embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2",
    ) -> None:
        self.persist_dir = Path(persist_dir)
        self.collection_name = collection_name
        self.embedding_model = embedding_model

        self.persist_dir.mkdir(parents=True, exist_ok=True)
        embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(model_name=embedding_model)
        client = chromadb.PersistentClient(path=str(self.persist_dir))
        self.collection = client.get_or_create_collection(
            name=self.collection_name,
            embedding_function=embedding_fn,
            metadata={"hnsw:space": "cosine"},
        )

    def search(
        self,
        query: str,
        language: Optional[str] = None,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        if not query.strip():
            return []
        n_results = max(1, min(limit, 20))
        where_filter = {"language": language} if language else None
        response = self.collection.query(
            query_texts=[query],
            n_results=n_results,
            where=where_filter,
        )

        documents = response.get("documents", [[]])[0]
        metadatas = response.get("metadatas", [[]])[0]
        distances = response.get("distances", [[]])[0]

        results: List[Dict[str, Any]] = []
        for doc, meta, distance in zip(documents, metadatas, distances):
            results.append(
                {
                    "document": doc,
                    "metadata": meta,
                    "distance": distance,
                }
            )
        return results
