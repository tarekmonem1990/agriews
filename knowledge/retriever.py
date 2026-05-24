"""
knowledge/retriever.py
RAG retrieval module for AgriEWS.

Queries the ChromaDB vector database to find the most relevant
FAO/IFAD passages for a given crop, region, hazard, and growth stage.

Returns ranked passages with source citations that the LLM uses
to generate grounded, citable advisories.
"""

import os
import chromadb
from chromadb.utils import embedding_functions
import structlog

logger = structlog.get_logger()

KB_DIR     = os.getenv("KNOWLEDGE_BASE_DIR", "/app/knowledge_base")
CHROMA_DIR = os.path.join(KB_DIR, "chroma")

# Cache the collection connection
_collection = None


def get_collection():
    global _collection
    if _collection is not None:
        return _collection

    try:
        client = chromadb.PersistentClient(path=CHROMA_DIR)
        ef     = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name="all-MiniLM-L6-v2"
        )
        _collection = client.get_or_create_collection(
            name="agriews_knowledge",
            embedding_function=ef,
        )
        logger.info("kb_connected", chunks=_collection.count())
        return _collection
    except Exception as e:
        logger.error("kb_connection_failed", error=str(e))
        return None


def retrieve_knowledge(
    crop: str,
    region: str,
    hazard_level: str,
    growth_stage: str,
    topics: list[str] = None,
    n_results: int = 5,
) -> list[dict]:
    """
    Retrieve the most relevant FAO/IFAD passages for a farming situation.

    Builds a semantic query combining crop, hazard, growth stage, and topics,
    then returns the top n_results passages ranked by relevance.

    Each returned passage includes:
    - text: the passage content
    - source: FAO or IFAD
    - title: document title
    - url: source URL for citation
    - year: publication year
    - relevance_score: 0-1 (higher = more relevant)
    """
    collection = get_collection()

    if collection is None or collection.count() == 0:
        logger.warning("kb_empty_or_unavailable")
        return []

    # Build semantic query
    # The query combines the farming situation into natural language
    # so the embedding model can find semantically similar passages
    hazard_map = {
        "extreme": "severe critical emergency",
        "high":    "significant serious",
        "medium":  "moderate",
        "low":     "minor",
        "none":    "normal favourable",
    }
    stage_map = {
        "planting":    "planting sowing germination seedbed preparation",
        "vegetative":  "vegetative growth tillering canopy development",
        "flowering":   "flowering pollination anthesis reproductive stage",
        "grain_fill":  "grain filling pod filling seed development maturity",
        "harvest":     "harvest ripening maturity crop harvest",
        "post_harvest":"post-harvest storage grain drying threshing",
        "pre_season":  "land preparation soil tillage pre-season",
    }

    hazard_words = hazard_map.get(hazard_level, "")
    stage_words  = stage_map.get(growth_stage, growth_stage)
    topic_words  = " ".join(topics) if topics else "production management"

    query = (
        f"{crop} {stage_words} {hazard_words} {topic_words} "
        f"farmer advice recommendation management {region}"
    )

    logger.info("kb_querying",
                crop=crop, stage=growth_stage,
                hazard=hazard_level, query_len=len(query))

    try:
        results = collection.query(
            query_texts=[query],
            n_results=min(n_results, collection.count()),
            include=["documents", "metadatas", "distances"],
        )

        passages = []
        docs      = results["documents"][0]
        metas     = results["metadatas"][0]
        distances = results["distances"][0]

        for doc, meta, dist in zip(docs, metas, distances):
            # Convert distance to relevance score (0-1, higher = better)
            # ChromaDB uses L2 distance by default
            relevance = max(0.0, 1.0 - (dist / 2.0))

            # Only include sufficiently relevant passages
            if relevance < 0.2:
                continue

            passages.append({
                "text":      doc,
                "source":    meta.get("source", "FAO"),
                "title":     meta.get("title", ""),
                "url":       meta.get("url", ""),
                "year":      meta.get("year", ""),
                "page":      meta.get("page", ""),
                "doc_id":    meta.get("doc_id", ""),
                "relevance": round(relevance, 3),
            })

        logger.info("kb_results",
                    crop=crop, passages=len(passages))
        return passages

    except Exception as e:
        logger.error("kb_query_failed", error=str(e))
        return []


def format_context_for_llm(passages: list[dict]) -> str:
    """
    Format retrieved passages into a structured context block
    for the LLM prompt.

    Each passage is numbered and cited so the LLM can reference
    specific sources in its advisory.
    """
    if not passages:
        return "No FAO/IFAD knowledge base passages available for this query."

    lines = ["RELEVANT FAO/IFAD KNOWLEDGE BASE PASSAGES:", ""]

    for i, p in enumerate(passages, 1):
        citation = f"{p['source']} — {p['title']}"
        if p.get("year"):
            citation += f" ({p['year']})"
        if p.get("page"):
            citation += f", p.{p['page']}"

        lines.append(f"[{i}] Source: {citation}")
        lines.append(f"    {p['text']}")
        lines.append("")

    lines.append(
        "IMPORTANT: Base your advisory ONLY on the passages above. "
        "Cite the passage number [1], [2], etc. when making a recommendation. "
        "If the passages do not cover a specific situation, say so clearly."
    )

    return "\n".join(lines)


def is_kb_ready() -> bool:
    """Check if the knowledge base has been built and is ready to use."""
    collection = get_collection()
    return collection is not None and collection.count() > 0


def get_kb_size() -> int:
    """Return number of chunks in the knowledge base."""
    collection = get_collection()
    return collection.count() if collection else 0
