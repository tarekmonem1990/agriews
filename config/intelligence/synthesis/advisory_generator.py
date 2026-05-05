"""
intelligence/synthesis/advisory_generator.py
The AI core of AgriEWS.

Takes structured data from weather, market, and shock modules
and generates plain-language farmer advisories via Anthropic API.

The AI does ONLY language generation.
All agronomic reasoning comes from the validated rule tables below.
Cost: roughly $0.001 per advisory at claude-haiku-4-5-20251001 pricing.
"""
import json
import anthropic
from datetime import datetime, date
from config.models import (
    Advisory, WeatherForecast, HazardScores, HazardLevel,
    CropPrice, InputPrice, TrendDirection, District
)
from config.settings import get_settings
import structlog

logger = structlog.get_logger()
settings = get_settings()
client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

SYSTEM = """You are AgriEWS, an agricultural early warning assistant
for smallholder farmers in developing countries.

Your job is to convert structured data into clear, actionable advisories.

Rules you must always follow:
- Write in simple language a farmer with no technical background can understand
- Never invent any information not present in the data you receive
- Always recommend one specific action, not just describe the situation
- Maximum 2-3 sentences per section
- No technical jargon (no SPI, NDVI, index values, etc.)
- Write in natural sentences, never bullet points
- If no alert exists for a section, say so briefly and reassuringly
- Adapt tone to the language and culture requested

Respond ONLY as JSON with exactly these keys:
{"weather_section":"...","market_section":"...","shock_section":"..."}
No other text outside the JSON."""


async def generate_advisory(
    district: District,
    forecast: WeatherForecast,
    scores: HazardScores,
    crop_prices: list[CropPrice],
    input_prices: list[InputPrice],
    language: str = "english",
    crop: str | None = None,
) -> Advisory:
    """
    Generate a full three-pillar advisory for one district,
    one crop, and one language.
    """
    # Get the recommended agronomic action from validated rules
    action = _get_action(crop, scores, forecast) if crop else ""

    # Build the structured context for the AI
    weather_facts = f"""WEATHER DATA for {district.name} — next 7 days:
- Total rainfall forecast: {forecast.rain_7d_mm:.0f}mm
- Next 24 hours rainfall: {forecast.rain_24h_mm:.0f}mm
- Temperature: {forecast.temp_min_c:.0f}C to {forecast.temp_max_c:.0f}C
- Drought risk: {scores.drought_level.value}
- Flood risk: {scores.flood_level.value}
- Pest pressure: {scores.pest_level.value}
- Overall hazard: {scores.composite_level.value}
{"- Recommended action for " + crop + ": " + action if action else ""}"""

    market_facts = "CROP MARKET PRICES:\n" + (
        "\n".join(
            f"- {p.crop.title()}: {p.price_local:.0f} {p.currency}/{p.unit} "
            f"at {p.market_name} — {p.trend.value} ({p.trend_pct:+.0f}%)"
            for p in crop_prices[:3]
        ) or "- No market price data available for this district today."
    )

    active_shocks = [ip for ip in input_prices if ip.shock_detected]
    shock_facts = "AGRICULTURAL INPUT PRICES:\n" + (
        "\n".join(
            f"- {s.input_type}: {s.trend.value} ({s.trend_pct:+.0f}%). "
            f"Reason: {s.shock_reason or 'supply disruption detected'}"
            for s in active_shocks
        ) or "- No significant input price shocks detected today."
    )

    prompt = (
        f"{weather_facts}\n\n"
        f"{market_facts}\n\n"
        f"{shock_facts}\n\n"
        f"Write the farmer advisory in {language}."
    )

    logger.info("advisory_generating",
                district=district.id, language=language, crop=crop)

    response = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=settings.anthropic_max_tokens,
        system=SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    sections = json.loads(raw)

    advisory = Advisory(
        district_id=district.id,
        generated_at=datetime.utcnow(),
        valid_for_date=date.today(),
        language=language,
        crop=crop,
        weather_section=sections["weather_section"],
        market_section=sections["market_section"],
        shock_section=sections["shock_section"],
        hazard_level=scores.composite_level,
        has_market_alert=any(
            p.trend in (TrendDirection.SPIKE, TrendDirection.CRASH)
            for p in crop_prices
        ),
        has_shock_alert=bool(active_shocks),
        weather_source=forecast.source,
        market_source=crop_prices[0].source if crop_prices else "none",
        shock_source=input_prices[0].source if input_prices else "none",
    )

    logger.info("advisory_generated",
                district=district.id,
                hazard=scores.composite_level,
                has_market_alert=advisory.has_market_alert,
                has_shock_alert=advisory.has_shock_alert)

    return advisory


def _get_action(
    crop: str,
    scores: HazardScores,
    forecast: WeatherForecast
) -> str:
    """
    Validated agronomic action lookup table.
    Returns the correct recommended action based on
    crop + hazard level combination.

    This is NEVER generated by the AI — it comes from
    a validated agronomic decision table so advice is
    always accurate and traceable.
    """
    c = crop.lower()

    if scores.drought_level in (HazardLevel.HIGH, HazardLevel.EXTREME):
        return {
            "groundnut": "irrigate immediately if possible; apply mulch to retain soil moisture",
            "maize":     "irrigate at least 25mm; delay fertilizer application until rain returns",
            "millet":    "millet is drought-tolerant — no irrigation needed yet, monitor for 5 more days",
            "sorghum":   "drought-tolerant crop — monitor closely, consider emergency irrigation if dry for 14+ days",
            "rice":      "maintain paddy water level; emergency irrigation required immediately",
            "wheat":     "irrigate immediately; drought at this stage causes permanent yield loss",
            "cassava":   "cassava tolerates drought — no action needed unless dry for 3+ weeks",
            "default":   "conserve soil moisture — apply mulch, avoid tillage, delay fertilizer",
        }.get(c, "conserve soil moisture — apply mulch, avoid tillage, delay fertilizer")

    if scores.flood_level in (HazardLevel.HIGH, HazardLevel.EXTREME):
        return {
            "groundnut": "clear drainage channels immediately; do not apply fertilizer before heavy rain",
            "maize":     "check field drainage; delay pesticide application until after rain passes",
            "rice":      "monitor paddy water level carefully — excess water causes root rot",
            "wheat":     "ensure drainage is clear — waterlogging for 24h causes serious damage",
            "default":   "clear drainage channels now; do not apply fertilizer or pesticide before heavy rain",
        }.get(c, "clear drainage channels now; do not apply fertilizer or pesticide before heavy rain")

    if scores.pest_level in (HazardLevel.HIGH, HazardLevel.EXTREME):
        return (
            f"inspect {crop} fields closely for pest damage — "
            f"warm humid conditions strongly favour pest outbreaks; "
            f"contact your extension officer if you find damage"
        )

    return f"conditions are favourable for {crop} — continue your normal farm management"
