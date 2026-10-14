"""Retrieval layer (the "R" in RAG).

Two knowledge sources are indexed:
  * examples.json     - verified question -> SQL pairs (dynamic few-shot examples)
  * kpi_glossary.md   - business definitions (how "underperforming", "risk score", etc. are computed)

Backends:
  * ChromaDB vector store with sentence embeddings (default when installed)
  * TF-IDF cosine similarity (zero-dependency fallback, used in tests/CI)
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Doc:
    id: str
    text: str          # what gets embedded
    payload: dict      # what gets returned


@dataclass
class Hit:
    doc: Doc
    score: float       # higher = more similar, 0..1


def load_examples(path: Path) -> list[Doc]:
    data = json.loads(Path(path).read_text())
    return [Doc(f"ex-{i}", e["question"], e) for i, e in enumerate(data)]


def load_glossary(path: Path) -> list[Doc]:
    text = Path(path).read_text()
    chunks = re.split(r"\n(?=## )", text)
    docs = []
    for i, ch in enumerate(chunks):
        if not ch.startswith("## "):
            continue
        title, _, body = ch[3:].partition("\n")
        docs.append(Doc(f"kpi-{i}", f"{title}. {body}", {"title": title.strip(), "body": body.strip()}))
    return docs


class TfidfIndex:
    name = "tfidf"

    def __init__(self, docs: list[Doc]):
        from sklearn.feature_extraction.text import TfidfVectorizer

        self.docs = docs
        self.vec = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, stop_words="english")
        self.matrix = self.vec.fit_transform([d.text for d in docs])

    def search(self, query: str, k: int) -> list[Hit]:
        from sklearn.metrics.pairwise import cosine_similarity

        sims = cosine_similarity(self.vec.transform([query]), self.matrix)[0]
        order = sims.argsort()[::-1][:k]
        return [Hit(self.docs[i], float(sims[i])) for i in order]


class ChromaIndex:
    name = "chroma"

    def __init__(self, docs: list[Doc], collection: str, persist_dir: Path | None = None):
        import chromadb

        client = chromadb.PersistentClient(path=str(persist_dir)) if persist_dir else chromadb.EphemeralClient()
        # Rebuild on start: the knowledge base is small and this keeps it in sync with the files
        try:
            client.delete_collection(collection)
        except Exception:
            pass
        self.col = client.create_collection(collection, metadata={"hnsw:space": "cosine"})
        self.docs = {d.id: d for d in docs}
        self.col.add(ids=[d.id for d in docs], documents=[d.text for d in docs])

    def search(self, query: str, k: int) -> list[Hit]:
        res = self.col.query(query_texts=[query], n_results=min(k, len(self.docs)))
        return [Hit(self.docs[i], 1.0 - float(dist)) for i, dist in zip(res["ids"][0], res["distances"][0])]


def build_index(docs: list[Doc], collection: str, backend: str | None = None, persist_dir: Path | None = None):
    backend = (backend or os.getenv("RETRIEVER", "auto")).lower()
    if backend in ("auto", "chroma"):
        try:
            return ChromaIndex(docs, collection, persist_dir)
        except Exception:
            if backend == "chroma":
                raise
    return TfidfIndex(docs)


class KnowledgeBase:
    def __init__(self, knowledge_dir: Path, backend: str | None = None):
        self.examples = build_index(load_examples(knowledge_dir / "examples.json"), "examples", backend)
        self.glossary = build_index(load_glossary(knowledge_dir / "kpi_glossary.md"), "glossary", backend)

    @property
    def backend(self) -> str:
        return self.examples.name

    def retrieve(self, question: str, k_examples: int = 4, k_glossary: int = 4) -> tuple[list[Hit], list[Hit]]:
        return self.examples.search(question, k_examples), self.glossary.search(question, k_glossary)
