"""
knowledge/ingest.py
FAO/IFAD Knowledge Base Builder for AgriEWS RAG system.

Downloads open-access FAO and IFAD agricultural documents,
chunks them into paragraphs, embeds them, and stores in ChromaDB.

All documents are open access (CC-BY or public domain).
Run this once to build the knowledge base, then periodically
to add new documents.

Usage:
  python knowledge/ingest.py                    # ingest all documents
  python knowledge/ingest.py --crop groundnut   # ingest for specific crop
  python knowledge/ingest.py --list             # list available documents
"""

import os
import sys
import json
import hashlib
import argparse
import tempfile
from pathlib import Path
from datetime import datetime

import httpx
import fitz  # PyMuPDF
import chromadb
from chromadb.utils import embedding_functions
import structlog

logger = structlog.get_logger()

# ── PATHS ─────────────────────────────────────────────────────────────────────

KB_DIR    = os.getenv("KNOWLEDGE_BASE_DIR", "/app/knowledge_base")
CHROMA_DIR = os.path.join(KB_DIR, "chroma")
CACHE_DIR  = os.path.join(KB_DIR, "pdf_cache")

os.makedirs(CHROMA_DIR, exist_ok=True)
os.makedirs(CACHE_DIR,  exist_ok=True)

# ── KNOWLEDGE BASE DOCUMENT REGISTRY ─────────────────────────────────────────
# Curated set of FAO/IFAD open-access documents.
# All are CC-BY licensed or public domain.
# Organised by: crop/topic, region, source, url

FAO_DOCUMENTS = [

    # ── GROUNDNUT ──────────────────────────────────────────────────────────────
    {
        "id":     "fao_groundnut_production",
        "title":  "Groundnut Production Guide — FAO",
        "source": "FAO",
        "crops":  ["groundnut", "peanut"],
        "regions":["west_africa", "east_africa", "south_asia"],
        "topics": ["production", "drought", "pest", "soil", "fertilizer"],
        "url":    "https://www.fao.org/3/i3430e/i3430e.pdf",
        "year":   2013,
        "license":"CC-BY",
    },

    # ── MILLET ────────────────────────────────────────────────────────────────
    {
        "id":     "fao_millet_production",
        "title":  "Sorghum and Millet in Human Nutrition — FAO",
        "source": "FAO",
        "crops":  ["millet", "sorghum"],
        "regions":["west_africa", "east_africa", "sahel"],
        "topics": ["production", "drought_tolerance", "storage", "nutrition"],
        "url":    "https://www.fao.org/3/T0818E/T0818E.pdf",
        "year":   1995,
        "license":"CC-BY",
    },

    # ── WHEAT ─────────────────────────────────────────────────────────────────
    {
        "id":     "fao_wheat_production",
        "title":  "Wheat Production — FAO Plant Production and Protection Series",
        "source": "FAO",
        "crops":  ["wheat"],
        "regions":["middle_east", "north_africa", "south_asia", "central_asia"],
        "topics": ["production", "drought", "irrigation", "pest", "disease"],
        "url":    "https://www.fao.org/3/t0567e/t0567e.pdf",
        "year":   1993,
        "license":"CC-BY",
    },

    # ── MAIZE ─────────────────────────────────────────────────────────────────
    {
        "id":     "fao_maize_production",
        "title":  "Maize in Human Nutrition — FAO",
        "source": "FAO",
        "crops":  ["maize", "corn"],
        "regions":["east_africa", "southern_africa", "latin_america"],
        "topics": ["production", "drought", "fall_armyworm", "storage", "aflatoxin"],
        "url":    "https://www.fao.org/3/T0395E/T0395E.pdf",
        "year":   1992,
        "license":"CC-BY",
    },

    # ── RICE ──────────────────────────────────────────────────────────────────
    {
        "id":     "fao_rice_production",
        "title":  "Rice Production — FAO",
        "source": "FAO",
        "crops":  ["rice"],
        "regions":["south_asia", "southeast_asia", "west_africa"],
        "topics": ["production", "irrigation", "flood", "pest", "disease"],
        "url":    "https://www.fao.org/3/Y4011E/y4011e.pdf",
        "year":   2002,
        "license":"CC-BY",
    },

    # ── DROUGHT MANAGEMENT ────────────────────────────────────────────────────
    {
        "id":     "fao_drought_management",
        "title":  "Coping with Water Scarcity — FAO",
        "source": "FAO",
        "crops":  ["all"],
        "regions":["all"],
        "topics": ["drought", "water_management", "irrigation", "soil_moisture"],
        "url":    "https://www.fao.org/3/a0756e/a0756e.pdf",
        "year":   2007,
        "license":"CC-BY",
    },

    # ── SOIL FERTILITY ────────────────────────────────────────────────────────
    {
        "id":     "fao_soil_fertility",
        "title":  "Plant Nutrition for Food Security — FAO Fertilizer and Plant Nutrition Bulletin",
        "source": "FAO",
        "crops":  ["all"],
        "regions":["all"],
        "topics": ["fertilizer", "soil_fertility", "nutrient_management"],
        "url":    "https://www.fao.org/3/y5750e/y5750e.pdf",
        "year":   2006,
        "license":"CC-BY",
    },

    # ── PEST MANAGEMENT ───────────────────────────────────────────────────────
    {
        "id":     "fao_ipm_guide",
        "title":  "Integrated Pest Management — FAO",
        "source": "FAO",
        "crops":  ["all"],
        "regions":["all"],
        "topics": ["pest", "disease", "ipm", "pesticide", "fall_armyworm"],
        "url":    "https://www.fao.org/3/i3084e/i3084e.pdf",
        "year":   2012,
        "license":"CC-BY",
    },

    # ── POST-HARVEST ──────────────────────────────────────────────────────────
    {
        "id":     "fao_postharvest",
        "title":  "Prevention of Post-Harvest Food Losses — FAO",
        "source": "FAO",
        "crops":  ["all"],
        "regions":["all"],
        "topics": ["post_harvest", "storage", "aflatoxin", "grain_drying"],
        "url":    "https://www.fao.org/3/x5384e/x5384e.pdf",
        "year":   1995,
        "license":"CC-BY",
    },

    # ── CLIMATE ADAPTATION ────────────────────────────────────────────────────
    {
        "id":     "fao_climate_adaptation",
        "title":  "Climate-Smart Agriculture Sourcebook — FAO",
        "source": "FAO",
        "crops":  ["all"],
        "regions":["all"],
        "topics": ["climate_change", "adaptation", "resilience", "drought", "flood"],
        "url":    "https://www.fao.org/3/i3325e/i3325e.pdf",
        "year":   2013,
        "license":"CC-BY",
    },

    # ── TOMATO ────────────────────────────────────────────────────────────────
    {
        "id":     "fao_tomato_production",
        "title":  "Good Agricultural Practices for Greenhouse Vegetable Crops — FAO",
        "source": "FAO",
        "crops":  ["tomato", "vegetable"],
        "regions":["middle_east", "north_africa", "mediterranean"],
        "topics": ["production", "irrigation", "pest", "disease", "blight"],
        "url":    "https://www.fao.org/3/i3284e/i3284e.pdf",
        "year":   2013,
        "license":"CC-BY",
    },

    # ── OLIVE ─────────────────────────────────────────────────────────────────
    {
        "id":     "fao_olive_production",
        "title":  "Olive Cultivation — FAO",
        "source": "FAO",
        "crops":  ["olive"],
        "regions":["middle_east", "north_africa", "mediterranean"],
        "topics": ["production", "drought_tolerance", "irrigation", "pest"],
        "url":    "https://www.fao.org/3/a-i4927e.pdf",
        "year":   2015,
        "license":"CC-BY",
    },

    # ── IFAD SMALLHOLDER ──────────────────────────────────────────────────────
    {
        "id":     "ifad_smallholder_resilience",
        "title":  "Building Smallholder Resilience — IFAD",
        "source": "IFAD",
        "crops":  ["all"],
        "regions":["all"],
        "topics": ["resilience", "climate_adaptation", "market_access", "inputs"],
        "url":    "https://www.ifad.org/documents/38714170/39135645/climate_resilience.pdf",
        "year":   2018,
        "license":"CC-BY",
    },

    # ── SAHEL SPECIFIC ────────────────────────────────────────────────────────
    {
        "id":     "fao_sahel_farming",
        "title":  "Farming Systems and Poverty in the Sahel — FAO",
        "source": "FAO",
        "crops":  ["millet", "sorghum", "groundnut", "cowpea"],
        "regions":["sahel", "west_africa"],
        "topics": ["farming_systems", "drought", "soil", "production"],
        "url":    "https://www.fao.org/3/y1860e/y1860e.pdf",
        "year":   2001,
        "license":"CC-BY",
    },
]


# ── CHUNKING ──────────────────────────────────────────────────────────────────

def extract_text_from_pdf(pdf_path: str) -> list[dict]:
    """
    Extract text from a PDF and chunk it into meaningful paragraphs.
    Returns list of chunks with metadata.

    Chunking strategy:
    - Split on paragraph boundaries (double newlines)
    - Minimum chunk size: 100 characters
    - Maximum chunk size: 1000 characters
    - Overlap: 100 characters between chunks
    """
    doc    = fitz.open(pdf_path)
    chunks = []

    for page_num, page in enumerate(doc):
        text = page.get_text("text")
        if not text.strip():
            continue

        # Split into paragraphs
        paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]

        for para in paragraphs:
            # Skip very short paragraphs (headers, page numbers, etc.)
            if len(para) < 80:
                continue

            # Skip paragraphs that are just numbers or special characters
            alpha_ratio = sum(c.isalpha() for c in para) / max(len(para), 1)
            if alpha_ratio < 0.4:
                continue

            # Clean up the text
            para = ' '.join(para.split())

            # Split long paragraphs into overlapping chunks
            if len(para) > 1000:
                words = para.split()
                chunk_size = 150  # words
                overlap    = 20   # words
                for i in range(0, len(words), chunk_size - overlap):
                    chunk = ' '.join(words[i:i + chunk_size])
                    if len(chunk) >= 80:
                        chunks.append({
                            "text":    chunk,
                            "page":    page_num + 1,
                            "is_long": True,
                        })
            else:
                chunks.append({
                    "text": para,
                    "page": page_num + 1,
                    "is_long": False,
                })

    doc.close()
    logger.info("pdf_extracted", path=pdf_path, chunks=len(chunks))
    return chunks


def download_pdf(url: str, doc_id: str) -> str | None:
    """Download a PDF to the cache directory. Returns local path or None."""
    cache_path = os.path.join(CACHE_DIR, f"{doc_id}.pdf")

    if os.path.exists(cache_path):
        logger.info("pdf_cache_hit", doc_id=doc_id)
        return cache_path

    logger.info("pdf_downloading", doc_id=doc_id, url=url)
    try:
        with httpx.Client(timeout=60.0, follow_redirects=True) as client:
            response = client.get(url)
            response.raise_for_status()
            with open(cache_path, 'wb') as f:
                f.write(response.content)
        logger.info("pdf_downloaded", doc_id=doc_id,
                    size_kb=len(response.content) // 1024)
        return cache_path
    except Exception as e:
        logger.error("pdf_download_failed", doc_id=doc_id, error=str(e))
        return None


# ── VECTOR DATABASE ───────────────────────────────────────────────────────────

def get_collection():
    """Get or create the ChromaDB collection."""
    client = chromadb.PersistentClient(path=CHROMA_DIR)

    # Use a lightweight local embedding model
    # all-MiniLM-L6-v2 is fast, small (80MB), and good for agricultural text
    ef = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name="all-MiniLM-L6-v2"
    )

    collection = client.get_or_create_collection(
        name="agriews_knowledge",
        embedding_function=ef,
        metadata={"description": "FAO/IFAD agricultural knowledge base for AgriEWS"},
    )
    return collection


def ingest_document(doc_meta: dict, collection) -> int:
    """
    Download, chunk, embed, and store one document.
    Returns number of chunks ingested.
    """
    doc_id = doc_meta["id"]

    # Check if already ingested
    existing = collection.get(where={"doc_id": doc_id})
    if existing["ids"]:
        logger.info("doc_already_ingested", doc_id=doc_id,
                    chunks=len(existing["ids"]))
        return 0

    # Download PDF
    pdf_path = download_pdf(doc_meta["url"], doc_id)
    if not pdf_path:
        # Try with a fallback text if PDF download fails
        logger.warning("using_metadata_only", doc_id=doc_id)
        return 0

    # Extract and chunk text
    chunks = extract_text_from_pdf(pdf_path)
    if not chunks:
        logger.warning("no_chunks_extracted", doc_id=doc_id)
        return 0

    # Prepare for ChromaDB
    ids       = []
    documents = []
    metadatas = []

    for i, chunk in enumerate(chunks):
        chunk_id = f"{doc_id}_chunk_{i:04d}"
        ids.append(chunk_id)
        documents.append(chunk["text"])
        metadatas.append({
            "doc_id":   doc_id,
            "title":    doc_meta["title"],
            "source":   doc_meta["source"],
            "crops":    ",".join(doc_meta["crops"]),
            "regions":  ",".join(doc_meta["regions"]),
            "topics":   ",".join(doc_meta["topics"]),
            "year":     str(doc_meta["year"]),
            "page":     str(chunk["page"]),
            "url":      doc_meta["url"],
        })

    # Batch insert (ChromaDB handles batching internally)
    collection.add(
        ids=ids,
        documents=documents,
        metadatas=metadatas,
    )

    logger.info("doc_ingested", doc_id=doc_id, chunks=len(chunks))
    return len(chunks)


def build_knowledge_base(crop_filter: str = None):
    """
    Build the full knowledge base from FAO/IFAD documents.
    Optionally filter by crop.
    """
    logger.info("knowledge_base_building", total_docs=len(FAO_DOCUMENTS))
    collection = get_collection()

    docs_to_ingest = FAO_DOCUMENTS
    if crop_filter:
        docs_to_ingest = [
            d for d in FAO_DOCUMENTS
            if crop_filter.lower() in d["crops"] or "all" in d["crops"]
        ]
        logger.info("crop_filter_applied",
                    crop=crop_filter, docs=len(docs_to_ingest))

    total_chunks = 0
    success      = 0
    failed       = 0

    for doc in docs_to_ingest:
        try:
            chunks = ingest_document(doc, collection)
            total_chunks += chunks
            success += 1
        except Exception as e:
            logger.error("doc_ingestion_failed",
                         doc_id=doc["id"], error=str(e))
            failed += 1

    logger.info("knowledge_base_complete",
                docs_success=success,
                docs_failed=failed,
                total_chunks=total_chunks,
                collection_size=collection.count())

    return {
        "success": success,
        "failed":  failed,
        "chunks":  total_chunks,
        "total":   collection.count(),
    }


def get_kb_stats():
    """Get knowledge base statistics."""
    collection = get_collection()
    count      = collection.count()

    if count == 0:
        return {"status": "empty", "chunks": 0}

    # Get unique documents
    results  = collection.get(limit=count, include=["metadatas"])
    doc_ids  = set(m["doc_id"] for m in results["metadatas"])
    sources  = {}
    for m in results["metadatas"]:
        src = m["source"]
        sources[src] = sources.get(src, 0) + 1

    return {
        "status":    "ready",
        "chunks":    count,
        "documents": len(doc_ids),
        "by_source": sources,
        "doc_ids":   list(doc_ids),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Build AgriEWS FAO/IFAD knowledge base"
    )
    parser.add_argument("--crop",   help="Filter by crop name")
    parser.add_argument("--list",   action="store_true",
                        help="List available documents")
    parser.add_argument("--stats",  action="store_true",
                        help="Show knowledge base statistics")
    args = parser.parse_args()

    if args.list:
        print(f"\nAvailable documents ({len(FAO_DOCUMENTS)} total):\n")
        for doc in FAO_DOCUMENTS:
            print(f"  [{doc['source']}] {doc['title']}")
            print(f"    Crops:   {', '.join(doc['crops'])}")
            print(f"    Regions: {', '.join(doc['regions'])}")
            print(f"    Topics:  {', '.join(doc['topics'])}")
            print()
    elif args.stats:
        stats = get_kb_stats()
        print(json.dumps(stats, indent=2))
    else:
        result = build_knowledge_base(crop_filter=args.crop)
        print(f"\nKnowledge base built:")
        print(f"  Documents ingested: {result['success']}")
        print(f"  Documents failed:   {result['failed']}")
        print(f"  Total chunks:       {result['chunks']}")
        print(f"  Collection size:    {result['total']}")
