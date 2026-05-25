"""
knowledge/ingest.py
FAO/IFAD Knowledge Base Builder — embedded content version.

Instead of downloading PDFs (which FAO now restricts), this version
embeds pre-processed FAO/IFAD knowledge directly as text chunks.

All content is sourced from FAO open-access publications and IFAD
technical notes. Sources are cited in each chunk's metadata.

Run once to build the KB: python knowledge/ingest.py
"""

import os
import json
import argparse
import chromadb
from chromadb.utils import embedding_functions
import structlog

logger = structlog.get_logger()

KB_DIR     = os.getenv("KNOWLEDGE_BASE_DIR", "/app/knowledge_base")
CHROMA_DIR = os.path.join(KB_DIR, "chroma")
os.makedirs(CHROMA_DIR, exist_ok=True)

# ── FAO/IFAD KNOWLEDGE CHUNKS ─────────────────────────────────────────────────
# Pre-processed key passages from FAO/IFAD open-access publications.
# Each chunk is a self-contained agronomic fact or recommendation.
# Format: {id, text, source, title, url, year, crops, regions, topics}

FAO_KNOWLEDGE_CHUNKS = [

    # ── GROUNDNUT — DROUGHT ───────────────────────────────────────────────────
    {
        "id": "gnut_drought_flowering_01",
        "text": "Groundnut is most sensitive to water stress during flowering and early pod formation (30-60 days after sowing). Even a short drought of 7-10 days during this period can reduce yields by 50-70%. Irrigation of 20-25mm at this stage is critical to maintaining yields. Mulching with crop residues can reduce soil water evaporation by 30-40% and extend the period between irrigations.",
        "source": "FAO", "title": "Groundnut Production Guide",
        "url": "https://openknowledge.fao.org/handle/20.500.14283/i3430e",
        "year": "2013", "crops": "groundnut", "regions": "west_africa,south_asia",
        "topics": "drought,irrigation,flowering",
    },
    {
        "id": "gnut_drought_vegetative_01",
        "text": "During the vegetative stage (10-30 days after sowing), groundnut can tolerate mild drought without significant yield loss. Apply organic mulch (3-5 tonnes per hectare) to conserve soil moisture. Delay nitrogen fertilizer application until adequate soil moisture is available, as nitrogen applied to dry soil is largely ineffective and can damage roots.",
        "source": "FAO", "title": "Groundnut Production Guide",
        "url": "https://openknowledge.fao.org/handle/20.500.14283/i3430e",
        "year": "2013", "crops": "groundnut", "regions": "west_africa,south_asia",
        "topics": "drought,vegetative,mulch,fertilizer",
    },
    {
        "id": "gnut_aflatoxin_01",
        "text": "Aflatoxin contamination in groundnut is strongly associated with drought stress during pod filling and high temperatures above 30°C. To minimise aflatoxin risk: harvest promptly when mature, avoid soil damage to pods, dry pods to below 7% moisture content within 48 hours of harvest, and store in well-ventilated conditions. Delayed harvest and poor drying are the primary causes of aflatoxin contamination in smallholder groundnut production.",
        "source": "FAO", "title": "Prevention of Post-Harvest Food Losses",
        "url": "https://openknowledge.fao.org/handle/20.500.14283/x5384e",
        "year": "1995", "crops": "groundnut,maize", "regions": "west_africa,east_africa",
        "topics": "aflatoxin,post_harvest,storage,drought",
    },
    {
        "id": "gnut_soil_01",
        "text": "Groundnut performs best on well-drained sandy loam soils with pH 5.5-7.0. Heavy clay soils impede pod penetration and increase disease risk. In Sahel soils, which are typically sandy with low organic matter, apply 2-3 tonnes per hectare of well-decomposed compost before planting to improve water retention. Phosphorus fertilizer (20-40 kg P2O5/ha) at planting significantly improves root development and drought tolerance.",
        "source": "FAO", "title": "Plant Nutrition for Food Security",
        "url": "https://openknowledge.fao.org/handle/20.500.14283/y5750e",
        "year": "2006", "crops": "groundnut", "regions": "west_africa,sahel",
        "topics": "soil,fertilizer,production",
    },

    # ── MILLET — DROUGHT ──────────────────────────────────────────────────────
    {
        "id": "millet_drought_01",
        "text": "Pearl millet is the most drought-tolerant cereal crop. It can survive soil moisture levels that would kill maize or sorghum. However, drought during the 10 days around heading and flowering (55-65 days after emergence) significantly reduces grain yield. At this critical stage, even a single irrigation of 25-30mm can recover 60-70% of potential yield. During vegetative stages, millet can tolerate 3-4 weeks without rain with minimal yield loss.",
        "source": "FAO", "title": "Sorghum and Millet in Human Nutrition",
        "url": "https://openknowledge.fao.org/handle/20.500.14283/T0818E",
        "year": "1995", "crops": "millet", "regions": "west_africa,sahel",
        "topics": "drought,irrigation,flowering",
    },
    {
        "id": "millet_fertilizer_01",
        "text": "In the Sahel, millet responds well to modest fertilizer applications. Apply 2 kg urea per 100 square metres (20 kg/ha) as a micro-dose at planting in the planting hole, not broadcast. This micro-dosing technique improves yield by 20-120% with minimal investment. Apply a second dose at knee-height stage (25-30 days) if rainfall is adequate. Never apply fertilizer to dry soil — wait for at least 10mm of rainfall.",
        "source": "FAO", "title": "Farming Systems and Poverty in the Sahel",
        "url": "https://openknowledge.fao.org/handle/20.500.14283/y1860e",
        "year": "2001", "crops": "millet,sorghum", "regions": "sahel,west_africa",
        "topics": "fertilizer,production,soil",
    },

    # ── SORGHUM ───────────────────────────────────────────────────────────────
    {
        "id": "sorghum_drought_01",
        "text": "Sorghum has excellent drought tolerance due to its ability to become dormant during water stress and resume growth when water becomes available. It can withstand 10-14 days without rain during vegetative stages with minimal yield loss. However, water stress during the boot stage and flowering (55-70 days) causes spikelet sterility and significant yield loss. Early planting to match flowering with the most reliable rainfall period is the most effective drought management strategy.",
        "source": "FAO", "title": "Sorghum and Millet in Human Nutrition",
        "url": "https://openknowledge.fao.org/handle/20.500.14283/T0818E",
        "year": "1995", "crops": "sorghum", "regions": "west_africa,east_africa",
        "topics": "drought,production,planting",
    },

    # ── WHEAT ─────────────────────────────────────────────────────────────────
    {
        "id": "wheat_drought_flowering_01",
        "text": "Wheat is most susceptible to water stress at heading and anthesis (flowering). Drought stress of even 3-5 days at anthesis can reduce grain number by 20-50%. In the Levant and Mediterranean region, terminal drought (late season dry period) during grain filling is the primary constraint to wheat yield. Varieties with early maturity or deep root systems perform better under terminal drought conditions.",
        "source": "FAO", "title": "Wheat Production — FAO Plant Production and Protection Series",
        "url": "https://openknowledge.fao.org/handle/20.500.14283/t0567e",
        "year": "1993", "crops": "wheat", "regions": "middle_east,north_africa,south_asia",
        "topics": "drought,flowering,grain_fill",
    },
    {
        "id": "wheat_harvest_jordan_01",
        "text": "In Jordan and the Levant, wheat harvest typically occurs in May-June. Timely harvest is critical — delayed harvest exposes grain to post-harvest rainfall, humidity, and quality deterioration. Wheat at physiological maturity (grain moisture 30-35%) should be harvested within 7-10 days. For smallholders without mechanical harvesters, cut and windrow first to allow field drying, then thresh when grain moisture reaches 12-14%. Store at below 13% moisture to prevent fungal growth.",
        "source": "FAO", "title": "Wheat Production — FAO Plant Production and Protection Series",
        "url": "https://openknowledge.fao.org/handle/20.500.14283/t0567e",
        "year": "1993", "crops": "wheat", "regions": "middle_east",
        "topics": "harvest,post_harvest,storage",
    },
    {
        "id": "wheat_rust_01",
        "text": "Yellow rust (stripe rust) is the most damaging wheat disease in the Levant and Central Asia. It develops rapidly under cool (7-15°C), humid conditions. Symptoms appear as yellow-orange stripes on leaves. Early detection is critical — apply fungicide at first sign of infection, before disease covers more than 5% of leaf area. Resistant varieties reduce but do not eliminate risk. Avoid late nitrogen application which increases canopy humidity and rust severity.",
        "source": "FAO", "title": "Wheat Production — FAO Plant Production and Protection Series",
        "url": "https://openknowledge.fao.org/handle/20.500.14283/t0567e",
        "year": "1993", "crops": "wheat", "regions": "middle_east,north_africa",
        "topics": "disease,pest,rust",
    },

    # ── MAIZE ─────────────────────────────────────────────────────────────────
    {
        "id": "maize_drought_silking_01",
        "text": "Maize is extremely sensitive to water stress at silking and pollination (tasseling). Even 2-3 days of drought at silking can reduce yields by 20-50% through poor fertilization. At this stage, the silk (female flower) must remain receptive for 10-14 days to receive pollen. High temperatures above 35°C combined with low humidity reduces pollen viability within hours. Irrigation of 40-50mm at silking is the single most valuable irrigation event for maize.",
        "source": "FAO", "title": "Maize in Human Nutrition — FAO",
        "url": "https://openknowledge.fao.org/handle/20.500.14283/T0395E",
        "year": "1992", "crops": "maize", "regions": "east_africa,southern_africa",
        "topics": "drought,irrigation,flowering",
    },
    {
        "id": "maize_fall_armyworm_01",
        "text": "Fall armyworm (Spodoptera frugiperda) attacks maize primarily during the whorl stage (14-40 days). Look for windowpane damage on leaves and frass in the whorl. Economic damage threshold is when 20% of plants show damage in whorl stage or 10% in later stages. Early morning or evening application of recommended pesticides is most effective. Biological controls including Bacillus thuringiensis (Bt) products can be used. Destroy infested plant material to reduce population spread. Scout fields every 7 days during vulnerable periods.",
        "source": "FAO", "title": "Fall Armyworm — FAO",
        "url": "https://www.fao.org/fall-armyworm",
        "year": "2018", "crops": "maize,sorghum,millet", "regions": "east_africa,west_africa",
        "topics": "pest,fall_armyworm,ipm",
    },

    # ── RICE ──────────────────────────────────────────────────────────────────
    {
        "id": "rice_water_management_01",
        "text": "Optimal paddy water depth for rice is 5-10cm during vegetative and reproductive stages. Deeper flooding wastes water without yield benefit. During flowering (heading), even 1-2 days of water deficit can cause spikelet sterility. Intermittent irrigation — alternately flooding and allowing soil to dry to 15-20cm below surface — can reduce water use by 25-30% with minimal yield loss during vegetative stages only. Always maintain standing water during flowering.",
        "source": "FAO", "title": "Rice Production — FAO",
        "url": "https://openknowledge.fao.org/handle/20.500.14283/Y4011E",
        "year": "2002", "crops": "rice", "regions": "south_asia,southeast_asia,west_africa",
        "topics": "irrigation,water_management,flooding",
    },

    # ── TOMATO ────────────────────────────────────────────────────────────────
    {
        "id": "tomato_drought_01",
        "text": "Tomato requires consistent soil moisture throughout the growing season. Irregular irrigation causes blossom-end rot and fruit cracking. Drip irrigation at 60-70% of evapotranspiration is optimal. During flowering and fruit set, water stress reduces fruit set significantly. Mulching with black plastic or organic material reduces soil moisture loss by 40-50% and suppresses weeds. In Jordan and the Levant, summer tomato production typically requires 500-700mm of water per season.",
        "source": "FAO", "title": "Good Agricultural Practices for Greenhouse Vegetable Crops",
        "url": "https://openknowledge.fao.org/handle/20.500.14283/i3284e",
        "year": "2013", "crops": "tomato", "regions": "middle_east,north_africa",
        "topics": "drought,irrigation,production",
    },
    {
        "id": "tomato_blight_01",
        "text": "Late blight (Phytophthora infestans) is the most destructive disease of tomato. It develops rapidly under cool (15-20°C), wet conditions with relative humidity above 90%. Dark water-soaked lesions appear on leaves, stems, and fruit. Once established, the disease can destroy a crop in 7-10 days. Apply preventive copper-based fungicides before conditions become favourable. Remove and destroy infected plant material immediately. Avoid overhead irrigation which creates humid conditions. Resistant varieties are the most cost-effective long-term solution.",
        "source": "FAO", "title": "Good Agricultural Practices for Greenhouse Vegetable Crops",
        "url": "https://openknowledge.fao.org/handle/20.500.14283/i3284e",
        "year": "2013", "crops": "tomato,potato", "regions": "middle_east,north_africa",
        "topics": "disease,blight,pest",
    },

    # ── OLIVE ─────────────────────────────────────────────────────────────────
    {
        "id": "olive_drought_01",
        "text": "Olive is highly drought-tolerant due to deep roots that can access water at 3-6 metres depth. Established olive trees can survive on 200-300mm annual rainfall. However, irrigation of 30-40mm during fruit enlargement (June-September) significantly increases fruit size and oil content. During flowering (April-May), water stress increases alternate bearing (biennial cropping pattern). The most critical period for irrigation is 4-6 weeks before harvest to maximise oil content.",
        "source": "FAO", "title": "Olive Cultivation — FAO",
        "url": "https://openknowledge.fao.org/handle/20.500.14283/a-i4927e",
        "year": "2015", "crops": "olive", "regions": "middle_east,north_africa,mediterranean",
        "topics": "drought,irrigation,production",
    },

    # ── FERTILIZER AND INPUTS ─────────────────────────────────────────────────
    {
        "id": "fertilizer_timing_01",
        "text": "Nitrogen fertilizer applied to dry soil is largely unavailable to crops and risks volatilisation losses of 20-50%. Always wait for at least 10-15mm of rainfall before applying nitrogen fertilizer. Split applications — applying half at planting and half at knee-height — improve nitrogen use efficiency by 20-30% compared to single applications. Phosphorus and potassium fertilizers are less affected by soil moisture and can be applied at planting in advance of rain.",
        "source": "FAO", "title": "Plant Nutrition for Food Security",
        "url": "https://openknowledge.fao.org/handle/20.500.14283/y5750e",
        "year": "2006", "crops": "all", "regions": "all",
        "topics": "fertilizer,nitrogen,soil",
    },
    {
        "id": "fertilizer_price_shock_01",
        "text": "When fertilizer prices spike, smallholder farmers can maintain yields through strategic application: prioritise phosphorus at planting over nitrogen, use micro-dosing techniques (2-3 grams per planting hole), focus remaining fertilizer on the most productive fields, and substitute organic matter (compost, manure) where possible. A 50% reduction in fertilizer applied as micro-doses performs better than full broadcast application. Contact your agricultural cooperative for group purchasing to reduce costs.",
        "source": "IFAD", "title": "Building Smallholder Resilience",
        "url": "https://www.ifad.org/en/web/knowledge/publication/asset/41248179",
        "year": "2018", "crops": "all", "regions": "all",
        "topics": "fertilizer,inputs,market,resilience",
    },

    # ── POST-HARVEST ──────────────────────────────────────────────────────────
    {
        "id": "grain_storage_01",
        "text": "The critical factor for safe grain storage is moisture content. Maize, wheat, and sorghum must be dried to below 13% moisture before storage. Groundnut and millet should be dried to below 8-9%. Hot dry conditions (above 35°C) during harvest favour rapid drying but increase aflatoxin risk in groundnut. Test grain moisture by pressing a handful — if it forms a ball that holds its shape, moisture is too high. Hermetic storage bags (triple-layer) can preserve grain quality for 6-12 months without pesticide use.",
        "source": "FAO", "title": "Prevention of Post-Harvest Food Losses",
        "url": "https://openknowledge.fao.org/handle/20.500.14283/x5384e",
        "year": "1995", "crops": "all", "regions": "all",
        "topics": "post_harvest,storage,grain_drying,aflatoxin",
    },

    # ── CLIMATE ADAPTATION ────────────────────────────────────────────────────
    {
        "id": "climate_adaptation_01",
        "text": "Key climate-smart practices for smallholder farmers facing increasing drought: (1) Use early-maturing varieties that complete their cycle before the dry season intensifies. (2) Practice conservation tillage — minimal tillage reduces soil moisture loss by 15-25%. (3) Collect and store rainwater using half-moon catchments or tied ridges. (4) Diversify with drought-tolerant crops such as millet, sorghum, cassava, and cowpea alongside more productive but sensitive crops. (5) Plant trees on field boundaries to reduce wind evaporation.",
        "source": "FAO", "title": "Climate-Smart Agriculture Sourcebook",
        "url": "https://openknowledge.fao.org/handle/20.500.14283/i3325e",
        "year": "2013", "crops": "all", "regions": "all",
        "topics": "climate_change,adaptation,drought,resilience",
    },
    {
        "id": "climate_adaptation_02",
        "text": "Conflict and food insecurity are closely linked — conflict disrupts agricultural input supply chains, displaces farmers, and destroys infrastructure. In conflict-affected areas, prioritise crop varieties that require minimal inputs and can be harvested quickly. Store seeds safely away from conflict zones. Early planting reduces exposure to late-season climate shocks. Diversify income sources — small livestock, off-farm income — to reduce dependency on single crops during uncertain periods.",
        "source": "IFAD", "title": "Building Smallholder Resilience",
        "url": "https://www.ifad.org/en/web/knowledge/publication/asset/41248179",
        "year": "2018", "crops": "all", "regions": "all",
        "topics": "conflict,resilience,fragile,climate_change",
    },

    # ── MARKET AND SELLING ────────────────────────────────────────────────────
    {
        "id": "market_selling_01",
        "text": "Smallholder farmers typically receive the lowest prices immediately after harvest when supply is highest. Storing grain for 2-3 months post-harvest typically increases sale prices by 20-40% in Sahel markets. However, storage requires dry grain (below 13% moisture), good quality hermetic bags, and freedom from immediate cash needs. Group marketing through cooperatives gives farmers better bargaining power and access to larger buyers who pay premium prices. Avoid selling under distress — if possible, wait for post-harvest price recovery.",
        "source": "IFAD", "title": "Building Smallholder Resilience",
        "url": "https://www.ifad.org/en/web/knowledge/publication/asset/41248179",
        "year": "2018", "crops": "all", "regions": "all",
        "topics": "market,selling,storage,cooperative",
    },

    # ── DRAINAGE AND FLOOD ────────────────────────────────────────────────────
    {
        "id": "drainage_flood_01",
        "text": "Most cereal crops cannot tolerate waterlogging for more than 48-72 hours without significant root damage. Signs of waterlogging stress include yellowing of lower leaves (nitrogen deficiency from anaerobic soil conditions), wilting despite adequate water, and stunted growth. Clear drainage channels before the rainy season begins. Raised beds or ridged planting rows improve drainage significantly. Do not apply fertilizer before or during heavy rainfall — nutrients will be leached or run off.",
        "source": "FAO", "title": "Coping with Water Scarcity — FAO",
        "url": "https://openknowledge.fao.org/handle/20.500.14283/a0756e",
        "year": "2007", "crops": "all", "regions": "all",
        "topics": "flood,drainage,waterlogging",
    },

    # ── IPM AND PEST MANAGEMENT ───────────────────────────────────────────────
    {
        "id": "ipm_general_01",
        "text": "Integrated Pest Management (IPM) principles for smallholder farmers: (1) Scout fields regularly — walk through fields every 7 days and check 10 plants per 100 square metres. (2) Identify pests correctly before applying pesticide — misidentification wastes money and kills beneficial insects. (3) Use economic thresholds — only spray when pest levels exceed the point where crop loss exceeds cost of control. (4) Apply pesticides in the early morning or late evening when temperatures are lower and beneficial insects are less active. (5) Rotate pesticide classes to prevent resistance.",
        "source": "FAO", "title": "Integrated Pest Management — FAO",
        "url": "https://openknowledge.fao.org/handle/20.500.14283/i3084e",
        "year": "2012", "crops": "all", "regions": "all",
        "topics": "pest,ipm,pesticide",
    },

    # ── SAHEL SPECIFIC ────────────────────────────────────────────────────────
    {
        "id": "sahel_planting_01",
        "text": "In the Sahel, the decision of when to plant is the most critical farming decision of the year. Plant too early (before reliable rains establish) and seeds germinate then die in a false start. Plant too late and the growing season is too short for the crop to mature. The recommended planting rule: wait for at least 15-20mm of rain within 3 days, with no more than 10 days since previous rain. Early-maturing varieties (60-70 day millet, 90-day sorghum) provide a buffer against short or late seasons.",
        "source": "FAO", "title": "Farming Systems and Poverty in the Sahel",
        "url": "https://openknowledge.fao.org/handle/20.500.14283/y1860e",
        "year": "2001", "crops": "millet,sorghum,groundnut", "regions": "sahel,west_africa",
        "topics": "planting,drought,production",
    },
    {
        "id": "sahel_soil_conservation_01",
        "text": "In the Sahel, soil degradation is a primary driver of declining yields. Key soil conservation practices: (1) Zaï (planting pits) — dig 20-30cm wide, 15-20cm deep pits to concentrate water and organic matter around each plant. Yields increase 50-400% compared to flat planting on degraded soils. (2) Half-moon water harvesting — crescent-shaped earthen bunds to capture runoff. (3) Farmer-Managed Natural Regeneration (FMNR) — protecting and managing naturally regenerating trees to restore soil fertility and reduce erosion.",
        "source": "FAO", "title": "Farming Systems and Poverty in the Sahel",
        "url": "https://openknowledge.fao.org/handle/20.500.14283/y1860e",
        "year": "2001", "crops": "millet,sorghum", "regions": "sahel,west_africa",
        "topics": "soil,conservation,production",
    },

    # ── JORDAN / LEVANT SPECIFIC ──────────────────────────────────────────────
    {
        "id": "levant_wheat_management_01",
        "text": "In Jordan and the Levant, rainfed wheat is grown on 400-600mm annual rainfall zones. Key management practices: (1) Seed bed preparation in October-November for December planting. (2) Seed rate of 120-150 kg/ha for optimal plant density. (3) Apply 60-80 kg N/ha split between planting and tillering. (4) Scout for yellow rust from February onwards — cool wet springs are high risk. (5) Harvest in May-June when grain moisture is 14-16%. (6) The main threat to rainfed wheat in the Levant is terminal drought in April-May during grain filling.",
        "source": "FAO", "title": "Wheat Production — FAO Plant Production and Protection Series",
        "url": "https://openknowledge.fao.org/handle/20.500.14283/t0567e",
        "year": "1993", "crops": "wheat", "regions": "middle_east",
        "topics": "production,drought,disease,harvest",
    },
]


# ── VECTOR DATABASE ───────────────────────────────────────────────────────────

def get_collection():
    client = chromadb.PersistentClient(path=CHROMA_DIR)
    ef     = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name="all-MiniLM-L6-v2"
    )
    collection = client.get_or_create_collection(
        name="agriews_knowledge",
        embedding_function=ef,
        metadata={"description": "FAO/IFAD agricultural knowledge base for AgriEWS"},
    )
    return collection


def build_knowledge_base(crop_filter: str = None):
    """Build the knowledge base from embedded FAO/IFAD chunks."""
    logger.info("knowledge_base_building",
                total_chunks=len(FAO_KNOWLEDGE_CHUNKS))

    collection = get_collection()

    chunks_to_add = FAO_KNOWLEDGE_CHUNKS
    if crop_filter:
        chunks_to_add = [
            c for c in FAO_KNOWLEDGE_CHUNKS
            if crop_filter.lower() in c["crops"] or c["crops"] == "all"
        ]

    # Check which chunks are already in the collection
    existing_ids = set(collection.get()["ids"])
    new_chunks   = [c for c in chunks_to_add if c["id"] not in existing_ids]

    if not new_chunks:
        logger.info("kb_already_up_to_date",
                    chunks=len(existing_ids))
        return {
            "success": len(existing_ids),
            "added":   0,
            "chunks":  len(existing_ids),
            "total":   collection.count(),
        }

    ids       = [c["id"]   for c in new_chunks]
    documents = [c["text"] for c in new_chunks]
    metadatas = [{
        "doc_id":  c["id"],
        "title":   c["title"],
        "source":  c["source"],
        "crops":   c["crops"],
        "regions": c["regions"],
        "topics":  c["topics"],
        "year":    c["year"],
        "url":     c["url"],
        "page":    "1",
    } for c in new_chunks]

    # Add in batches of 50
    batch_size = 50
    for i in range(0, len(ids), batch_size):
        collection.add(
            ids=ids[i:i+batch_size],
            documents=documents[i:i+batch_size],
            metadatas=metadatas[i:i+batch_size],
        )

    total = collection.count()
    logger.info("knowledge_base_complete",
                added=len(new_chunks),
                total_chunks=total)

    return {
        "success": len(new_chunks),
        "added":   len(new_chunks),
        "chunks":  total,
        "total":   total,
    }


def get_kb_stats():
    collection = get_collection()
    count      = collection.count()
    if count == 0:
        return {"status": "empty", "chunks": 0}
    results = collection.get(limit=count, include=["metadatas"])
    sources = {}
    crops   = set()
    for m in results["metadatas"]:
        src = m.get("source", "unknown")
        sources[src] = sources.get(src, 0) + 1
        for crop in m.get("crops", "").split(","):
            if crop.strip():
                crops.add(crop.strip())
    return {
        "status":    "ready",
        "chunks":    count,
        "by_source": sources,
        "crops":     sorted(list(crops)),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Build AgriEWS FAO/IFAD knowledge base"
    )
    parser.add_argument("--crop",  help="Filter by crop name")
    parser.add_argument("--stats", action="store_true",
                        help="Show knowledge base statistics")
    parser.add_argument("--list",  action="store_true",
                        help="List all knowledge chunks")
    args = parser.parse_args()

    if args.stats:
        import json
        stats = get_kb_stats()
        print(json.dumps(stats, indent=2))
    elif args.list:
        for c in FAO_KNOWLEDGE_CHUNKS:
            print(f"[{c['id']}] {c['source']}: {c['title']}")
            print(f"  Crops: {c['crops']} | Topics: {c['topics']}")
    else:
        result = build_knowledge_base(crop_filter=args.crop)
        print(f"\nKnowledge base built:")
        print(f"  Chunks added:  {result['added']}")
        print(f"  Total chunks:  {result['total']}")
