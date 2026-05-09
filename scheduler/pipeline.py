"""
AgriEWS — self-contained pipeline with locale-aware voice notes
Free voice notes via gTTS (Google Translate TTS — no API key needed)
"""
import asyncio
import os
import json
import tempfile
import httpx
import structlog
from datetime import datetime, date
from enum import Enum
from typing import Optional
from dotenv import load_dotenv
from gtts import gTTS

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


# ── LOCALE MAP ────────────────────────────────────────────────────────────────
# Maps district language names to gTTS language codes.
# gTTS uses Google Translate under the hood — free, no key needed.
# Add new languages here as you onboard new countries.
# Full list: https://gtts.readthedocs.io/en/latest/module.html#languages

LANGUAGE_TO_GTTS = {
    # West Africa
    "french":     "fr",
    "wolof":      "fr",   # fallback to French until Wolof TTS matures
    "bambara":    "fr",   # fallback
    "hausa":      "ha",
    "yoruba":     "yo",
    "igbo":       "ig",

    # East Africa
    "amharic":    "am",
    "swahili":    "sw",
    "tigrinya":   "ti",
    "somali":     "so",
    "oromo":      "om",

    # North Africa / Middle East
    "arabic":     "ar",
    "darija":     "ar",   # Moroccan Arabic fallback

    # South / Southeast Asia
    "hindi":      "hi",
    "marathi":    "mr",
    "punjabi":    "pa",
    "bengali":    "bn",
    "telugu":     "te",
    "tamil":      "ta",
    "kannada":    "kn",
    "gujarati":   "gu",
    "urdu":       "ur",
    "nepali":     "ne",
    "sinhala":    "si",
    "khmer":      "km",
    "burmese":    "my",
    "thai":       "th",
    "vietnamese": "vi",
    "indonesian": "id",
    "tagalog":    "tl",

    # East Asia
    "mandarin":   "zh-CN",
    "cantonese":  "zh-TW",

    # Central Asia
    "uzbek":      "uz",
    "kazakh":     "kk",

    # Latin America
    "spanish":    "es",
    "portuguese": "pt",
    "quechua":    "qu",

    # Default fallback
    "english":    "en",
}


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
# Add your districts here.
# To add a new country: copy one block and update the values.
# The language field automatically determines the voice note language.

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
    # Example — uncomment to add India Maharashtra district:
    # {
    #     "id":          "in_pune_rural",
    #     "country_iso": "IN",
    #     "name":        "Pune Rural",
    #     "lat":         18.520,
    #     "lon":         73.856,
    #     "crops":       ["sorghum", "sugarcane", "onion"],
    #     "languages":   ["marathi"],
    #     "channels":    [Channel.WHATSAPP],
    #     "timezone":    "Asia/Kolkata",
    # },
]


# ── FARMER REGISTRY ───────────────────────────────────────────────────────────
# Replace the phone number with your own to receive the first test advisory.

FARMERS = [
    {
        "id":                 "test_001",
        "district_id":        "sn_kaffrine_nord",
        "phone":              "+221700000000",
        "preferred_channel":  Channel.WHATSAPP,
        "preferred_language": "french",
        "crops":              ["groundnut", "millet"],
        "voice_notes":        True,
    },
]


# ── STEP 1: FETCH WEATHER ─────────────────────────────────────────────────────

async def fetch_weather(district_id, lat, lon):
    params = {
        "latitude":      lat,
        "longitude":     lon,
        "daily":         "precipitation_sum,temperature_2m_max,temperature_2m_min",
        "forecast_days": 7,
        "timezone":      "auto",
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
        "district_id": district_id,
        "rain_7d_mm":  rain_7d,
        "rain_24h_mm": rain_24h,
        "temp_max_c":  tmax[0] or 0.0,
        "temp_min_c":  tmin[0] or 0.0,
        "flood_risk":  min(100.0, rain_24h * 2.5) if rain_24h > 30 else 0.0,
        "source":      "open-meteo",
    }


# ── STEP 2: FETCH MARKET PRICES ───────────────────────────────────────────────

async def fetch_market_prices(district_id, country_iso, crops):
    """
    Fetch crop prices from WFP DataBridges (primary) and FEWS NET (secondary).
    Both free, no API key needed. Results merged and deduplicated.
    """
    cache_key = f"market_{district_id}"
    cached = cache_get(cache_key)
    if cached:
        return cached

    prices = []

    # Source 1: WFP DataBridges
    try:
        vam_prices = await _fetch_wfp_vam(district_id, country_iso, crops)
        prices.extend(vam_prices)
        logger.info("wfp_vam_fetched",
                    district=district_id, count=len(vam_prices))
    except Exception as e:
        logger.warning("wfp_vam_failed", error=str(e))

    # Source 2: FEWS NET
    try:
        fews_prices = await _fetch_fews_net(district_id, country_iso, crops)
        existing_crops = {p["crop"] for p in prices}
        new_fews = [p for p in fews_prices
                    if p["crop"] not in existing_crops]
        prices.extend(new_fews)
        logger.info("fews_net_fetched",
                    district=district_id, count=len(fews_prices))
    except Exception as e:
        logger.warning("fews_net_failed", error=str(e))

    if prices:
        cache_set(cache_key, prices, ttl_hours=12)

    return prices
async def _fetch_wfp_vam(district_id, country_iso, crops):
    # WFP DataBridges API v2 — replaced old VAM endpoint
    url    = "https://api.wfp.org/vam-data-bridges/7.0.0/MarketPrices/PriceMonthly"
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
            "crop":        commodity,
            "price_local": float(price),
            "currency":    record.get("CurrencyName", "USD"),
            "unit":        record.get("UnitName", "kg"),
            "market_name": record.get("MarketName", "unknown"),
            "trend":       trend,
            "trend_pct":   round(pct, 1),
        })

    logger.info("market_prices_fetched",
                district=district_id, count=len(prices))
    return prices


# ── STEP 3: FETCH INPUT PRICE SHOCKS ─────────────────────────────────────────

async def fetch_shocks(district_id):
    # World Bank Commodity Price Data API — free, no key needed
    # Fetches fertilizer price index directly
    WB_URL = (
        "https://api.worldbank.org/v2/en/indicator/AG.PRD.FERT.ZS"
        "?format=json&mrv=2&per_page=2"
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
    try:
        # World Bank API returns array: [metadata, [datapoints]]
        records = data[1] if isinstance(data, list) and len(data) > 1 else []
        values  = [
            float(r["value"])
            for r in records
            if r.get("value") is not None
        ]
        if len(values) >= 2:
            current  = values[0]
            previous = values[1]
            pct      = (current - previous) / previous * 100
            is_shock = abs(pct) > 10

            # Also check absolute level — above 150 index is historically high
            level_alert = current > 150

            if is_shock or level_alert:
                reason_parts = []
                if is_shock:
                    reason_parts.append(
                        f"Global fertilizer index moved {pct:+.1f}% "
                        f"vs last month"
                    )
                if level_alert:
                    reason_parts.append(
                        f"Fertilizer index at {current:.0f} — "
                        f"historically elevated level"
                    )
                shocks.append({
                    "type":         "price_shock",
                    "input_type":   "fertilizer",
                    "trend_pct":    round(pct, 1),
                    "shock_reason": ". ".join(reason_parts),
                    "severity":     "high" if abs(pct) > 20 else "medium",
                    "source":       "world-bank-api",
                })
    except Exception as e:
        logger.warning("wb_parse_failed", error=str(e))
    return shocks


# ── STEP 4: SCORE HAZARDS ─────────────────────────────────────────────────────

def score_hazards(weather):
    rain = weather["rain_7d_mm"]
    r24  = weather["rain_24h_mm"]
    tmax = weather["temp_max_c"]

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

def get_action(crop, scores):
    c = crop.lower()
    if scores["drought_level"] in (HazardLevel.HIGH, HazardLevel.EXTREME):
        return {
            "groundnut": "irrigate immediately; apply mulch to retain soil moisture",
            "maize":     "irrigate at least 25mm; delay fertilizer until rain returns",
            "millet":    "millet is drought-tolerant — monitor for 5 more days",
            "sorghum":   "drought-tolerant — consider emergency irrigation if dry 14+ days",
            "rice":      "maintain paddy water; emergency irrigation required",
            "wheat":     "irrigate immediately; drought at this stage causes yield loss",
        }.get(c, "conserve moisture — mulch, avoid tillage, delay fertilizer")

    if scores["flood_level"] in (HazardLevel.HIGH, HazardLevel.EXTREME):
        return {
            "groundnut": "clear drainage now; no fertilizer before heavy rain",
            "rice":      "monitor paddy level — excess water causes root rot",
        }.get(c, "clear drainage; no fertilizer or pesticide before rain")

    if scores["pest_level"] in (HazardLevel.HIGH, HazardLevel.EXTREME):
        return (f"inspect {crop} for pest damage — "
                f"warm humid conditions favour outbreaks")

    return f"conditions favourable for {crop} — continue normal management"


# ── STEP 6: GENERATE ADVISORY VIA AI ─────────────────────────────────────────

async def generate_advisory(
    district, weather, scores, crop_prices, shocks, language, crop
):
    if not ANTHROPIC_API_KEY:
        logger.warning("no_anthropic_key_using_template")
        return _template_advisory(
            district, weather, scores, crop_prices, shocks, crop
        )

    action = get_action(crop, scores)

    weather_facts = (
        f"WEATHER for {district['name']} — next 7 days:\n"
        f"- Total rain: {weather['rain_7d_mm']:.0f}mm | "
        f"Next 24h: {weather['rain_24h_mm']:.0f}mm\n"
        f"- Temperature: {weather['temp_min_c']:.0f}C "
        f"to {weather['temp_max_c']:.0f}C\n"
        f"- Drought: {scores['drought_level'].value} | "
        f"Flood: {scores['flood_level'].value} | "
        f"Pest: {scores['pest_level'].value}\n"
        f"- Action for {crop}: {action}"
    )

    market_facts = "CROP MARKET PRICES:\n" + (
        "\n".join(
            f"- {p['crop'].title()}: {p['price_local']:.0f} "
            f"{p['currency']}/{p['unit']} at {p['market_name']} "
            f"— {p['trend'].value} ({p['trend_pct']:+.0f}%)"
            for p in crop_prices[:3]
        ) or "- No market data available today."
    )

    shock_facts = "AGRICULTURAL INPUT PRICES:\n" + (
        "\n".join(
            f"- {s['input_type']}: {s['trend_pct']:+.0f}%. "
            f"{s['shock_reason']}"
            for s in shocks
        ) or "- No significant input price shocks detected today."
    )

    prompt = (
        f"{weather_facts}\n\n"
        f"{market_facts}\n\n"
        f"{shock_facts}\n\n"
        f"Write a farmer advisory in {language} as JSON:\n"
        f"{{\"weather_section\":\"...\","
        f"\"market_section\":\"...\","
        f"\"shock_section\":\"...\"}}"
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
                "system": (
                    "You are AgriEWS, an agricultural early warning assistant. "
                    "Convert structured data into clear farmer advisories. "
                    "Simple language, no jargon, 2-3 sentences per section. "
                    "Respond ONLY as JSON with keys: "
                    "weather_section, market_section, shock_section."
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


def _template_advisory(
    district, weather, scores, crop_prices, shocks, crop
):
    """Fallback when no Anthropic key is configured."""
    action = get_action(crop, scores)
    market = (
        f"{crop_prices[0]['crop'].title()} at "
        f"{crop_prices[0]['price_local']:.0f} "
        f"{crop_prices[0]['currency']}/{crop_prices[0]['unit']} "
        f"— {crop_prices[0]['trend'].value}."
        if crop_prices else "No market data available today."
    )
    shock = (
        f"Alert: {shocks[0]['input_type']} {shocks[0]['trend_pct']:+.0f}%. "
        f"{shocks[0]['shock_reason']}"
        if shocks else "No input price alerts today."
    )
    return {
        "weather_section": (
            f"Rainfall forecast: {weather['rain_7d_mm']:.0f}mm over 7 days. "
            f"Hazard level: {scores['composite'].value}. "
            f"Recommended action: {action}."
        ),
        "market_section": market,
        "shock_section":  shock,
    }


# ── STEP 7: GENERATE VOICE NOTE (FREE — gTTS) ─────────────────────────────────

def generate_voice_note(advisory, language, district_name):
    """
    Convert advisory text to a voice note using gTTS.
    Completely free — uses Google Translate TTS, no API key needed.
    Returns path to the temporary audio file.
    Language is determined automatically by the district language setting.
    """
    gtts_lang = LANGUAGE_TO_GTTS.get(language.lower(), "en")

    # Build a natural spoken version of the advisory
    spoken_text = (
        f"AgriEWS advisory for {district_name}. "
        f"{advisory['weather_section']} "
        f"{advisory['market_section']} "
        f"{advisory['shock_section']} "
        f"This message is free from AgriEWS."
    )

    # Generate audio to a temporary file
    tts       = gTTS(text=spoken_text, lang=gtts_lang, slow=False)
    tmp_file  = tempfile.NamedTemporaryFile(
        suffix=".mp3", delete=False, prefix="agriews_"
    )
    tts.save(tmp_file.name)

    logger.info("voice_note_generated",
                language=language,
                gtts_lang=gtts_lang,
                file=tmp_file.name)

    return tmp_file.name


# ── STEP 8: DELIVER VIA WHATSAPP ──────────────────────────────────────────────

async def deliver_whatsapp(farmer, advisory, crop, hazard_level, district):
    """
    Sends two WhatsApp messages to the farmer:
    1. The full text advisory
    2. A voice note in the farmer's language (if voice_notes=True)
    """
    LABELS = {
        HazardLevel.NONE:    "All clear",
        HazardLevel.LOW:     "Low risk",
        HazardLevel.MEDIUM:  "Watch",
        HazardLevel.HIGH:    "Alert",
        HazardLevel.EXTREME: "Danger",
    }

    # -- Message 1: text advisory --
    message = (
        f"*AgriEWS Advisory* | "
        f"{date.today().strftime('%d %b %Y')} | "
        f"{crop.title()}\n"
        f"Status: *{LABELS[hazard_level]}*\n\n"
        f"*Weather & Action*\n{advisory['weather_section']}\n\n"
        f"*Market*\n{advisory['market_section']}\n\n"
        f"*Input Prices*\n{advisory['shock_section']}\n\n"
        f"_AgriEWS is free | Reply STOP to unsubscribe_"
    )

    url = (
        f"https://graph.facebook.com/v19.0/"
        f"{WHATSAPP_PHONE_NUMBER_ID}/messages"
    )
    headers = {
        "Authorization": f"Bearer {WHATSAPP_API_TOKEN}",
        "Content-Type":  "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # Send text message
            r = await client.post(
                url,
                json={
                    "messaging_product": "whatsapp",
                    "to":   farmer["phone"],
                    "type": "text",
                    "text": {"body": message, "preview_url": False},
                },
                headers=headers,
            )
            r.raise_for_status()
            logger.info("whatsapp_text_sent", farmer=farmer["id"])

            # Send voice note if enabled for this farmer
            if farmer.get("voice_notes", False) and WHATSAPP_PHONE_NUMBER_ID:
                audio_path = None
                try:
                    # Generate voice note in farmer's language
                    audio_path = generate_voice_note(
                        advisory,
                        farmer["preferred_language"],
                        district["name"],
                    )

                    # Upload audio to WhatsApp media endpoint
                    with open(audio_path, "rb") as audio_file:
                        upload_r = await client.post(
                            f"https://graph.facebook.com/v19.0/"
                            f"{WHATSAPP_PHONE_NUMBER_ID}/media",
                            headers={
                                "Authorization": f"Bearer {WHATSAPP_API_TOKEN}"
                            },
                            files={
                                "file": (
                                    "advisory.mp3",
                                    audio_file,
                                    "audio/mpeg"
                                )
                            },
                            data={"messaging_product": "whatsapp"},
                        )
                        upload_r.raise_for_status()
                        media_id = upload_r.json().get("id")

                    # Send audio message
                    await client.post(
                        url,
                        json={
                            "messaging_product": "whatsapp",
                            "to":    farmer["phone"],
                            "type":  "audio",
                            "audio": {"id": media_id},
                        },
                        headers=headers,
                    )
                    logger.info("voice_note_sent",
                                farmer=farmer["id"],
                                language=farmer["preferred_language"])

                except Exception as e:
                    logger.error("voice_note_failed",
                                 farmer=farmer["id"], error=str(e))
                finally:
                    # Always delete the temp audio file to save disk space
                    if audio_path and os.path.exists(audio_path):
                        os.remove(audio_path)

        return "sent"

    except Exception as e:
        logger.error("whatsapp_failed",
                     farmer=farmer["id"], error=str(e))
        return "failed"


# ── MAIN PIPELINE ─────────────────────────────────────────────────────────────

async def run_pipeline():
    logger.info("pipeline_starting", districts=len(DISTRICTS))

    for district in DISTRICTS:
        logger.info("district_starting", district=district["id"])
        try:
            # Fetch all data
            weather     = await fetch_weather(
                district["id"], district["lat"], district["lon"]
            )
            crop_prices = await fetch_market_prices(
                district["id"], district["country_iso"], district["crops"]
            )
            shocks      = await fetch_shocks(district["id"])
            scores      = score_hazards(weather)

            logger.info("data_ready",
                        district=district["id"],
                        rain_7d=round(weather["rain_7d_mm"], 1),
                        prices=len(crop_prices),
                        shocks=len(shocks),
                        hazard=scores["composite"].value)

            # Generate and deliver per farmer
            farmers = [
                f for f in FARMERS
                if f["district_id"] == district["id"]
            ]

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
                            farmer=farmer,
                            advisory=advisory,
                            crop=crop,
                            hazard_level=scores["composite"],
                            district=district,
                        )

                    logger.info("advisory_delivered",
                                farmer=farmer["id"],
                                crop=crop,
                                language=farmer["preferred_language"],
                                voice_note=farmer.get("voice_notes", False),
                                status=status)

        except Exception as e:
            logger.error("district_failed",
                         district=district["id"], error=str(e))
            continue

    logger.info("pipeline_complete")


if __name__ == "__main__":
    asyncio.run(run_pipeline())
