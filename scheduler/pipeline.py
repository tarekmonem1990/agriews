"""
AgriEWS — self-contained pipeline
All configuration and logic in one file to avoid import issues.
"""
import asyncio
import os
import json
import httpx
import structlog
from datetime import datetime, date
from enum import Enum
from typing import Optional
from dotenv import load_dotenv

load_dotenv("config/.env")
logger = structlog.get_logger()

# ── SETTINGS ──────────────────────────────────────────────────────────────────

ANTHROPIC_API_KEY        = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL          = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
ANTHROPIC_MAX_TOKENS     = int(os.getenv("ANTHROPIC_MAX_TOKENS", "400"))
WFP_VAM_BASE_URL         = os.getenv("WFP_VAM_BASE_URL", "https://api.vam.wfp.org/")
AT_API_KEY               = os.getenv("AT_API_KEY", "")
AT_USERNAME              = os.getenv("AT_USERNAME", "sandbox")
AT_SENDER_ID             = os.getenv("AT_SENDER_ID", "AgriEWS")
WHATSAPP_API_TOKEN       = os.getenv("WHATSAPP_API_TOKEN", "")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")


# ── ENUMS ─────────────────────────────────────────────────────────────────────

class HazardLevel(str, Enum):
    NONE    = "none"
    LOW     = "low"
    MEDIUM  = "medium"
    HIGH    = "high"
    EXTREME = "extreme"

class Channel(str, Enum):
    SMS      = "sms"
    WHATSAPP = "whatsapp"

class TrendDirection(str, Enum):
    STABLE  = "stable"
    RISING  = "rising"
    FALLING = "falling"
    SPIKE   = "spike"
    CRASH   = "crash"


# ── DISTRICT REGISTRY ─────────────────────────────────────────────────────────
# Edit this section to add your districts.
# lat/lon = coordinates of the district centre.

DISTRICTS = [
    {
        "id":          "sn_kaffrine_nord",
        "country_iso": "SN",
        "name":        "Kaffrine Nord",
        "lat":         14.105,
        "lon":         -15.551,
        "crops":       ["groundnut", "millet", "sorghum"],
        "languages":   ["french"],
        "channels":    [Channel.WHATSAPP],
        "timezone":    "Africa/Dakar",
    },
]


# ── FARMER REGISTRY ───────────────────────────────────────────────────────────
# Edit this section to add test farmers.
# Replace the phone number with your own to receive the first test advisory.

FARMERS = [
    {
        "id":                 "test_001",
        "district_id":        "sn_kaffrine_nord",
        "phone":              "+221700000000",
        "preferred_channel":  Channel.WHATSAPP,
        "preferred_language": "french",
        "crops":              ["groundnut", "millet"],
    },
]


# ── STEP 1: FETCH WEATHER ─────────────────────────────────────────────────────

async def fetch_weather(district_id, lat, lon):
    params = {
        "latitude":     lat,
        "longitude":    lon,
        "daily":        "precipitation_sum,temperature_2m_max,temperature_2m_min",
        "forecast_days": 7,
        "timezone":     "auto",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(
            "https://api.open-meteo.com/v1/forecast",
            params=params
        )
        r.raise_for_status()
        data = r.json()

    daily    = data.get("daily", {})
    precip   = daily.get("precipitation_sum", [0] * 7)
    tmax     = daily.get("temperature_2m_max", [0] * 7)
    tmin     = daily.get("temperature_2m_min", [0] * 7)
    rain_7d  = sum(p for p in precip if p is not None)
    rain_24h = precip[0] if precip else 0.0

    logger.info("weather_fetched",
                district=district_id,
                rain_7d=round(rain_7d, 1))

    return {
        "district_id":    district_id,
        "rain_7d_mm":     rain_7d,
        "rain_24h_mm":    rain_24h,
        "temp_max_c":     tmax[0] or 0.0,
        "temp_min_c":     tmin[0] or 0.0,
        "flood_risk":     min(100.0, rain_24h * 2.5) if rain_24h > 30 else 0.0,
        "source":         "open-meteo",
    }


# ── STEP 2: FETCH MARKET PRICES ───────────────────────────────────────────────

async def fetch_market_prices(district_id, country_iso, crops):
    url    = f"{WFP_VAM_BASE_URL}MarketPrices/PriceMonthly"
    params = {"CountryCode": country_iso, "format": "json"}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(url, params=params)
            r.raise_for_status()
            records = r.json()
    except Exception as e:
        logger.warning("market_fetch_failed", error=str(e))
        return []

    prices = []
    for record in records:
        commodity = record.get("CommodityName", "").lower()
        if not any(crop.lower() in commodity for crop in crops):
            continue
        price = record.get("Price")
        if price is None:
            continue
        prev  = record.get("PreviousPrice")
        pct   = ((float(price) - float(prev)) / float(prev) * 100
                 if prev and float(prev) > 0 else 0.0)
        trend = (TrendDirection.SPIKE   if pct > 15  else
                 TrendDirection.RISING  if pct > 3   else
                 TrendDirection.CRASH   if pct < -15 else
                 TrendDirection.FALLING if pct < -3  else
                 TrendDirection.STABLE)
        prices.append({
            "crop":         commodity,
            "price_local":  float(price),
            "currency":     record.get("CurrencyName", "USD"),
            "unit":         record.get("UnitName", "kg"),
            "market_name":  record.get("MarketName", "unknown"),
            "trend":        trend,
            "trend_pct":    round(pct, 1),
        })

    logger.info("prices_fetched",
                district=district_id, count=len(prices))
    return prices


# ── STEP 3: FETCH INPUT PRICE SHOCKS ─────────────────────────────────────────

async def fetch_shocks(district_id):
    WB_URL = (
        "https://thedocs.worldbank.org/en/doc/"
        "40ebbf38f5a6b68bfc11e5273e1405d4-0090012022"
        "/related/Food-Security-Dashboard.json"
    )
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(WB_URL)
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        logger.warning("shock_fetch_failed", error=str(e))
        return []

    shocks = []
    fert   = data.get("fertilizer_index")
    if fert:
        current  = fert.get("current")
        previous = fert.get("previous")
        if current and previous and float(previous) > 0:
            pct      = (float(current) - float(previous)) / float(previous) * 100
            is_shock = abs(pct) > 10
            if is_shock:
                shocks.append({
                    "input_type":   "fertilizer (global index)",
                    "trend_pct":    round(pct, 1),
                    "shock_reason": (
                        f"World Bank fertilizer index moved {pct:+.1f}% "
                        f"vs last month"
                    ),
                })
    logger.info("shocks_fetched",
                district=district_id, count=len(shocks))
    return shocks


# ── STEP 4: SCORE HAZARDS ─────────────────────────────────────────────────────

def score_hazards(weather):
    rain  = weather["rain_7d_mm"]
    r24   = weather["rain_24h_mm"]
    tmax  = weather["temp_max_c"]

    drought = (85.0 if rain < 5  else 60.0 if rain < 15 else
               35.0 if rain < 30 else 15.0 if rain < 50 else 5.0)
    flood   = (95.0 if r24 > 80 else 75.0 if r24 > 50 else
               50.0 if r24 > 30 else 25.0 if r24 > 15 else 0.0)
    pest    = (70.0 if tmax > 30 else 45.0 if tmax > 28 else
               25.0 if tmax > 25 else 10.0)

    def level(s):
        return (HazardLevel.EXTREME if s >= 80 else
                HazardLevel.HIGH    if s >= 60 else
                HazardLevel.MEDIUM  if s >= 35 else
                HazardLevel.LOW     if s >= 15 else
                HazardLevel.NONE)

    rank = {"none":0,"low":1,"medium":2,"high":3,"extreme":4}
    dl, fl, pl = level(drought), level(flood), level(pest)
    composite  = max([dl, fl, pl], key=lambda x: rank[x.value])

    return {
        "drought_level": dl,
        "flood_level":   fl,
        "pest_level":    pl,
        "composite":     composite,
    }


# ── STEP 5: GET AGRONOMIC ACTION ──────────────────────────────────────────────

def get_action(crop, scores, weather):
    c = crop.lower()
    if scores["drought_level"] in (HazardLevel.HIGH, HazardLevel.EXTREME):
        return {
            "groundnut": "irrigate immediately; apply mulch to retain soil moisture",
            "maize":     "irrigate at least 25mm; delay fertilizer until rain returns",
            "millet":    "millet is drought-tolerant — monitor for 5 more days",
            "sorghum":   "drought-tolerant — consider emergency irrigation if dry 14+ days",
            "rice":      "maintain paddy water; emergency irrigation required",
        }.get(c, "conserve moisture — mulch, avoid tillage, delay fertilizer")

    if scores["flood_level"] in (HazardLevel.HIGH, HazardLevel.EXTREME):
        return {
            "groundnut": "clear drainage now; no fertilizer before heavy rain",
            "rice":      "monitor paddy level — excess water causes root rot",
        }.get(c, "clear drainage; no fertilizer or pesticide before rain")

    if scores["pest_level"] in (HazardLevel.HIGH, HazardLevel.EXTREME):
        return f"inspect {crop} for pest damage — warm humid conditions favour outbreaks"

    return f"conditions favourable for {crop} — continue normal management"


# ── STEP 6: GENERATE ADVISORY VIA AI ─────────────────────────────────────────

async def generate_advisory(district, weather, scores, crop_prices, shocks, language, crop):
    if not ANTHROPIC_API_KEY:
        logger.warning("no_anthropic_key_using_template")
        return _template_advisory(district, weather, scores, crop_prices, shocks, crop)

    action = get_action(crop, scores, weather)

    weather_facts = f"""WEATHER for {district['name']} — next 7 days:
- Total rain: {weather['rain_7d_mm']:.0f}mm | Next 24h: {weather['rain_24h_mm']:.0f}mm
- Temperature: {weather['temp_min_c']:.0f}C to {weather['temp_max_c']:.0f}C
- Drought: {scores['drought_level'].value} | Flood: {scores['flood_level'].value} | Pest: {scores['pest_level'].value}
- Action for {crop}: {action}"""

    market_facts = "MARKET PRICES:\n" + (
        "\n".join(f"- {p['crop'].title()}: {p['price_local']:.0f} {p['currency']}/{p['unit']} "
                  f"at {p['market_name']} — {p['trend'].value} ({p['trend_pct']:+.0f}%)"
                  for p in crop_prices[:3])
        or "- No market data available today."
    )

    shock_facts = "INPUT PRICES:\n" + (
        "\n".join(f"- {s['input_type']}: {s['trend_pct']:+.0f}%. {s['shock_reason']}"
                  for s in shocks)
        or "- No input price shocks detected."
    )

    prompt = (
        f"{weather_facts}\n\n{market_facts}\n\n{shock_facts}\n\n"
        f"Write a farmer advisory in {language} as JSON: "
        f"{{\"weather_section\":\"...\",\"market_section\":\"...\",\"shock_section\":\"...\"}}"
    )

    async with httpx.AsyncClient(timeout=30.0) as client:
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
                "system":     (
                    "You are AgriEWS, an agricultural early warning assistant. "
                    "Convert structured data into clear farmer advisories. "
                    "Simple language, no jargon, 2-3 sentences per section. "
                    "Respond ONLY as JSON with keys: weather_section, market_section, shock_section."
                ),
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        r.raise_for_status()
        data = r.json()

    raw = data["content"][0]["text"].strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())


def _template_advisory(district, weather, scores, crop_prices, shocks, crop):
    """Fallback template when no Anthropic key is configured."""
    action = get_action(crop, scores, weather)
    market = (f"{crop_prices[0]['crop'].title()} at {crop_prices[0]['price_local']:.0f} "
              f"{crop_prices[0]['currency']}/{crop_prices[0]['unit']} — "
              f"{crop_prices[0]['trend'].value}."
              if crop_prices else "No market data available today.")
    shock  = (f"ALERT: {shocks[0]['input_type']} {shocks[0]['trend_pct']:+.0f}%. "
              f"{shocks[0]['shock_reason']}"
              if shocks else "No input price alerts today.")
    return {
        "weather_section": (
            f"Rainfall forecast: {weather['rain_7d_mm']:.0f}mm over 7 days. "
            f"Hazard level: {scores['composite'].value}. "
            f"Recommended action: {action}."
        ),
        "market_section": market,
        "shock_section":  shock,
    }


# ── STEP 7: DELIVER VIA WHATSAPP ──────────────────────────────────────────────

async def deliver_whatsapp(farmer, advisory, crop, hazard_level):
    LABELS = {
        HazardLevel.NONE:    "All clear",
        HazardLevel.LOW:     "Low risk",
        HazardLevel.MEDIUM:  "Watch",
        HazardLevel.HIGH:    "Alert",
        HazardLevel.EXTREME: "Danger",
    }
    message = (
        f"*AgriEWS Advisory* | {date.today().strftime('%d %b %Y')} | {crop.title()}\n"
        f"Status: *{LABELS[hazard_level]}*\n\n"
        f"*Weather & Action*\n{advisory['weather_section']}\n\n"
        f"*Market*\n{advisory['market_section']}\n\n"
        f"*Input Prices*\n{advisory['shock_section']}\n\n"
        f"_AgriEWS is free | Reply STOP to unsubscribe_"
    )
    url     = f"https://graph.facebook.com/v19.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_API_TOKEN}",
        "Content-Type":  "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to":   farmer["phone"],
        "type": "text",
        "text": {"body": message, "preview_url": False},
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(url, json=payload, headers=headers)
            r.raise_for_status()
        logger.info("whatsapp_sent", farmer=farmer["id"], crop=crop)
        return "sent"
    except Exception as e:
        logger.error("whatsapp_failed", farmer=farmer["id"], error=str(e))
        return "failed"


# ── MAIN PIPELINE ─────────────────────────────────────────────────────────────

async def run_pipeline():
    logger.info("pipeline_starting", districts=len(DISTRICTS))

    for district in DISTRICTS:
        logger.info("district_starting", district=district["id"])
        try:
            weather      = await fetch_weather(district["id"], district["lat"], district["lon"])
            crop_prices  = await fetch_market_prices(district["id"], district["country_iso"], district["crops"])
            shocks       = await fetch_shocks(district["id"])
            scores       = score_hazards(weather)

            logger.info("data_ready",
                        district=district["id"],
                        rain_7d=round(weather["rain_7d_mm"], 1),
                        prices=len(crop_prices),
                        shocks=len(shocks),
                        hazard=scores["composite"].value)

            farmers = [f for f in FARMERS if f["district_id"] == district["id"]]

            for farmer in farmers:
                for crop in farmer["crops"]:
                    advisory = await generate_advisory(
                        district=district,
                        weather=weather,
                        scores=scores,
                        crop_prices=crop_prices,
                        shocks=shocks,
                        language=farmer["preferred_language"],
                        crop=crop,
                    )
                    if farmer["preferred_channel"] == Channel.WHATSAPP:
                        status = await deliver_whatsapp(
                            farmer, advisory, crop, scores["composite"]
                        )
                    logger.info("advisory_delivered",
                                farmer=farmer["id"],
                                crop=crop,
                                status=status)

        except Exception as e:
            logger.error("district_failed",
                         district=district["id"], error=str(e))
            continue

    logger.info("pipeline_complete")


if __name__ == "__main__":
    asyncio.run(run_pipeline())
