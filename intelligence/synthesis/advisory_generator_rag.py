"""
intelligence/synthesis/advisory_generator.py  (RAG version)

Replaces the hardcoded rule-based advisory generator with a
RAG-powered system grounded exclusively in FAO/IFAD knowledge.

Flow:
  1. Retrieve relevant FAO/IFAD passages from ChromaDB
  2. Pass passages + situation data to Claude
  3. Claude generates advisory citing only FAO/IFAD sources
  4. Falls back to template if KB not available or API key missing
"""

import json
import os
import httpx
import structlog
from datetime import date, datetime

logger = structlog.get_logger()

ANTHROPIC_API_KEY    = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL      = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
ANTHROPIC_MAX_TOKENS = int(os.getenv("ANTHROPIC_MAX_TOKENS", "600"))

# ── SYSTEM PROMPT ─────────────────────────────────────────────────────────────

RAG_SYSTEM_PROMPT = """You are AgriEWS, an agricultural early warning assistant
for smallholder farmers in developing countries.

Your role is to generate practical farming advisories based EXCLUSIVELY on the
FAO and IFAD knowledge base passages provided to you. You must not use general
knowledge or make up information not present in the provided passages.

Rules you must always follow:
1. Base every recommendation on the provided FAO/IFAD passages
2. Cite the passage number [1], [2] etc. when making a specific recommendation
3. Write in simple, clear language a farmer with no technical background can understand
4. Do not use technical jargon — translate any technical terms into plain language
5. Maximum 3 sentences per section
6. If the knowledge base does not cover a specific situation, say "consult your local extension officer"
7. Adapt the language and cultural context to the region specified
8. Never invent statistics or percentages not found in the passages

Your response must be JSON with exactly these keys:
{
  "weather_section": "...",
  "market_section": "...",
  "shock_section": "...",
  "sources_used": ["FAO document title 1", "FAO document title 2"]
}"""


async def generate_advisory_rag(
    district: dict,
    weather: dict,
    scores: dict,
    crop_prices: list,
    shocks: list,
    pest_alerts: list,
    language: str,
    crop: str,
) -> dict:
    """
    Generate a RAG-powered advisory grounded in FAO/IFAD knowledge.
    Falls back to template if KB not ready or API key missing.
    """

    # Try RAG first
    if ANTHROPIC_API_KEY:
        try:
            return await _generate_rag(
                district, weather, scores, crop_prices,
                shocks, pest_alerts, language, crop
            )
        except Exception as e:
            logger.error("rag_generation_failed", error=str(e))

    # Fallback to template
    logger.warning("rag_fallback_to_template")
    return _template_fallback(
        district, weather, scores, crop_prices, shocks, pest_alerts, crop
    )


async def _generate_rag(
    district, weather, scores, crop_prices,
    shocks, pest_alerts, language, crop
) -> dict:
    """Core RAG generation — retrieves FAO/IFAD context then calls Claude."""

    from knowledge.retriever import retrieve_knowledge, format_context_for_llm, is_kb_ready

    # Determine topics based on current hazards
    topics = []
    if scores["drought_level"] in ("high", "extreme"):
        topics.extend(["drought", "irrigation", "water_management", "soil_moisture"])
    if scores["flood_level"] in ("high", "extreme"):
        topics.extend(["flood", "drainage", "waterlogging"])
    if scores["pest_level"] in ("high", "extreme"):
        topics.extend(["pest", "disease", "ipm"])
    if scores["growth_stage"].value in ("harvest", "post_harvest"):
        topics.extend(["post_harvest", "storage", "aflatoxin", "grain_drying"])
    if any(s.get("shock_detected") or s.get("type") == "price_shock" for s in shocks):
        topics.extend(["fertilizer", "inputs", "market"])
    if not topics:
        topics = ["production", "management"]

    # Retrieve relevant FAO/IFAD passages
    if is_kb_ready():
        passages = retrieve_knowledge(
            crop=crop,
            region=district.get("region", "all"),
            hazard_level=scores["composite"].value,
            growth_stage=scores["growth_stage"].value,
            topics=topics,
            n_results=5,
        )
    else:
        logger.warning("kb_not_ready_using_empty_context")
        passages = []

    kb_context = format_context_for_llm(passages)

    # Build the situation summary
    stage = scores["growth_stage"].value
    situation = (
        f"CURRENT FARMING SITUATION:\n"
        f"- District: {district['name']} ({district.get('country_iso', '')})\n"
        f"- Region: {district.get('region', 'unknown')}\n"
        f"- Crop: {crop} at {stage} stage\n"
        f"- Date: {date.today().strftime('%d %B %Y')}\n"
        f"- Rainfall (7 days): {weather['rain_7d_mm']:.0f}mm\n"
        f"- Temperature: {weather['temp_min_c']:.0f}–{weather['temp_max_c']:.0f}°C\n"
        f"- Drought index (SPI): {weather['spi']:+.1f} "
        f"({'below' if weather['spi'] < 0 else 'above'} seasonal normal)\n"
        f"- Drought hazard: {scores['drought_level'].value}\n"
        f"- Flood hazard: {scores['flood_level'].value}\n"
        f"- Pest pressure: {scores['pest_level'].value}\n"
        f"- Overall risk: {scores['composite'].value}"
    )

    if scores.get("cascade"):
        situation += "\n- WARNING: Multiple hazards occurring simultaneously"

    if weather.get("data_stale"):
        situation += "\n- NOTE: Weather data may be up to 72 hours old"

    # Market situation
    market_situation = "\nMARKET SITUATION:\n"
    if crop_prices:
        for p in crop_prices[:2]:
            trend = p["trend"].value if hasattr(p["trend"], "value") else str(p["trend"])
            market_situation += (
                f"- {p['crop'].title()}: {p['price_local']:.0f} "
                f"{p['currency']}/{p['unit']} at {p['market_name']} "
                f"({trend}, {p['trend_pct']:+.0f}%)\n"
            )
    else:
        market_situation += "- No local market price data available today\n"

    # Input/shock situation
    shock_situation = "\nINPUT PRICES AND RISKS:\n"
    active_shocks = [s for s in shocks if s.get("shock_detected") or
                     s.get("type") in ("price_shock", "conflict_signal")]
    if active_shocks:
        for s in active_shocks:
            shock_situation += f"- {s.get('shock_reason', str(s))}\n"
    else:
        shock_situation += "- No significant input price shocks detected\n"

    if pest_alerts:
        shock_situation += f"- PEST ALERT: {pest_alerts[0]['message']}\n"

    # Build the full prompt
    prompt = (
        f"{kb_context}\n\n"
        f"{'='*60}\n\n"
        f"{situation}\n"
        f"{market_situation}"
        f"{shock_situation}\n"
        f"{'='*60}\n\n"
        f"Generate a practical advisory for this farmer in {language}.\n"
        f"Crop: {crop} | Stage: {stage} | Risk: {scores['composite'].value}\n\n"
        f"Remember:\n"
        f"- Use ONLY information from the FAO/IFAD passages above\n"
        f"- Write in {language} — simple, clear, actionable\n"
        f"- Cite passage numbers [1], [2] etc. for specific recommendations\n"
        f"- 2-3 sentences maximum per section\n\n"
        f"Respond as JSON: "
        f"{{\"weather_section\":\"...\","
        f"\"market_section\":\"...\","
        f"\"shock_section\":\"...\","
        f"\"sources_used\":[...]}}"
    )

    async with httpx.AsyncClient(timeout=45.0) as client:
        r = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key":         ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type":      "application/json",
            },
            json={
                "model":      ANTHROPIC_MODEL,
                "max_tokens": ANTHROPIC_MAX_TOKENS,
                "system":     RAG_SYSTEM_PROMPT,
                "messages":   [{"role": "user", "content": prompt}],
            },
        )
        r.raise_for_status()
        data = r.json()

    raw = data["content"][0]["text"].strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    result = json.loads(raw.strip())

    # Log which sources were used
    sources = result.get("sources_used", [])
    logger.info("rag_advisory_generated",
                crop=crop, stage=stage,
                passages_retrieved=len(passages),
                sources_used=len(sources),
                kb_grounded=len(passages) > 0)

    return result


def _template_fallback(
    district, weather, scores, crop_prices, shocks, pest_alerts, crop
) -> dict:
    """
    Simple template fallback when RAG is unavailable.
    Used during initial setup before KB is built or API key added.
    """
    language = district.get("languages", ["english"])
    if isinstance(language, list):
        language = language[0] if language else "english"

    stage   = scores["growth_stage"].value
    hazard  = scores["composite"].value
    rain    = weather["rain_7d_mm"]
    spi     = weather["spi"]

    weather_section = (
        f"[{stage}] Rainfall: {rain:.0f}mm/7d, SPI: {spi:+.1f}. "
        f"Risk level: {hazard}. "
        f"Knowledge base not yet built — add Anthropic API key for FAO-grounded advice."
    )

    market_section = (
        f"{crop_prices[0]['crop'].title()} at {crop_prices[0]['price_local']:.0f} "
        f"{crop_prices[0]['currency']}/{crop_prices[0]['unit']} "
        f"— {crop_prices[0]['trend'].value if hasattr(crop_prices[0]['trend'], 'value') else crop_prices[0]['trend']}."
        if crop_prices else "No market data available."
    )

    shock_section = (
        " ".join(s.get("shock_reason", "") for s in shocks[:2])
        or "No input price alerts today."
    )

    return {
        "weather_section": weather_section,
        "market_section":  market_section,
        "shock_section":   shock_section,
        "sources_used":    [],
    }
