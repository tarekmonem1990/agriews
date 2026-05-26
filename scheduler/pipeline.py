"""
AgriEWS — Complete Pipeline v2.2
Changes from v2.1:
- Replaced WFP DataBridges (requires token) with FAO GIEWS (free, open)
- All functions verified and in correct order
"""
import asyncio
import os
import json
import tempfile
import hashlib
import httpx
import structlog
from datetime import datetime, date, timedelta
from enum import Enum
from typing import Optional
from dotenv import load_dotenv
from gtts import gTTS

# RAG advisory generator — grounded in FAO/IFAD knowledge
try:
    from intelligence.synthesis.advisory_generator_rag import generate_advisory_rag
    RAG_AVAILABLE = True
except ImportError:
    RAG_AVAILABLE = False

load_dotenv("config/.env")
logger = structlog.get_logger()

# ── SETTINGS ──────────────────────────────────────────────────────────────────

ANTHROPIC_API_KEY        = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL          = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
ANTHROPIC_MAX_TOKENS     = int(os.getenv("ANTHROPIC_MAX_TOKENS", "500"))
ACLED_API_KEY            = os.getenv("ACLED_API_KEY", "")
ACLED_EMAIL              = os.getenv("ACLED_EMAIL", "")
WHATSAPP_API_TOKEN       = os.getenv("WHATSAPP_API_TOKEN", "")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
AT_API_KEY               = os.getenv("AT_API_KEY", "")
AT_USERNAME              = os.getenv("AT_USERNAME", "sandbox")
AT_SENDER_ID             = os.getenv("AT_SENDER_ID", "AgriEWS")
TELEGRAM_BOT_TOKEN       = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID         = os.getenv("TELEGRAM_CHAT_ID", "")

CACHE_DIR = "/tmp/agriews_cache"
os.makedirs(CACHE_DIR, exist_ok=True)

# ── LOCALE MAP ────────────────────────────────────────────────────────────────

LANGUAGE_TO_GTTS = {
    "french": "fr", "wolof": "fr", "bambara": "fr",
    "hausa": "ha", "yoruba": "yo", "igbo": "ig",
    "amharic": "am", "swahili": "sw", "somali": "so",
    "tigrinya": "ti", "oromo": "om",
    "arabic": "ar", "darija": "ar",
    "hindi": "hi", "marathi": "mr", "punjabi": "pa",
    "bengali": "bn", "telugu": "te", "tamil": "ta",
    "kannada": "kn", "gujarati": "gu", "urdu": "ur",
    "nepali": "ne", "sinhala": "si",
    "khmer": "km", "burmese": "my", "thai": "th",
    "vietnamese": "vi", "indonesian": "id", "tagalog": "tl",
    "mandarin": "zh-CN", "cantonese": "zh-TW",
    "uzbek": "uz", "kazakh": "kk",
    "spanish": "es", "portuguese": "pt",
    "english": "en",
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
    TELEGRAM = "telegram"

class TrendDirection(str, Enum):
    STABLE  = "stable"
    RISING  = "rising"
    FALLING = "falling"
    SPIKE   = "spike"
    CRASH   = "crash"

class GrowthStage(str, Enum):
    PRE_SEASON   = "pre_season"
    PLANTING     = "planting"
    VEGETATIVE   = "vegetative"
    FLOWERING    = "flowering"
    GRAIN_FILL   = "grain_fill"
    HARVEST      = "harvest"
    POST_HARVEST = "post_harvest"

# ── CROP CALENDARS ────────────────────────────────────────────────────────────

CROP_CALENDARS = {
    "groundnut_west_africa": {
        GrowthStage.PLANTING:    (6, 6),
        GrowthStage.VEGETATIVE:  (7, 7),
        GrowthStage.FLOWERING:   (8, 8),
        GrowthStage.GRAIN_FILL:  (9, 9),
        GrowthStage.HARVEST:     (10, 11),
        GrowthStage.POST_HARVEST:(12, 5),
    },
    "millet_west_africa": {
        GrowthStage.PLANTING:    (6, 7),
        GrowthStage.VEGETATIVE:  (7, 8),
        GrowthStage.FLOWERING:   (8, 9),
        GrowthStage.GRAIN_FILL:  (9, 10),
        GrowthStage.HARVEST:     (10, 11),
        GrowthStage.POST_HARVEST:(12, 5),
    },
    "sorghum_west_africa": {
        GrowthStage.PLANTING:    (6, 7),
        GrowthStage.VEGETATIVE:  (7, 8),
        GrowthStage.FLOWERING:   (8, 9),
        GrowthStage.GRAIN_FILL:  (9, 10),
        GrowthStage.HARVEST:     (11, 12),
        GrowthStage.POST_HARVEST:(1, 5),
    },
    "maize_east_africa": {
        GrowthStage.PLANTING:    (3, 4),
        GrowthStage.VEGETATIVE:  (4, 5),
        GrowthStage.FLOWERING:   (5, 6),
        GrowthStage.GRAIN_FILL:  (6, 7),
        GrowthStage.HARVEST:     (7, 8),
        GrowthStage.POST_HARVEST:(8, 2),
    },
    "teff_east_africa": {
        GrowthStage.PLANTING:    (6, 7),
        GrowthStage.VEGETATIVE:  (7, 8),
        GrowthStage.FLOWERING:   (8, 9),
        GrowthStage.GRAIN_FILL:  (9, 10),
        GrowthStage.HARVEST:     (10, 11),
        GrowthStage.POST_HARVEST:(11, 5),
    },
    "rice_south_asia": {
        GrowthStage.PLANTING:    (6, 7),
        GrowthStage.VEGETATIVE:  (7, 8),
        GrowthStage.FLOWERING:   (8, 9),
        GrowthStage.GRAIN_FILL:  (9, 10),
        GrowthStage.HARVEST:     (10, 11),
        GrowthStage.POST_HARVEST:(11, 5),
    },
    "default": {
        GrowthStage.PLANTING:    (4, 5),
        GrowthStage.VEGETATIVE:  (5, 6),
        GrowthStage.FLOWERING:   (6, 7),
        GrowthStage.GRAIN_FILL:  (7, 8),
        GrowthStage.HARVEST:     (8, 10),
        GrowthStage.POST_HARVEST:(10, 3),
    },
}

CROP_CALENDAR_LOOKUP = {
    ("groundnut", "SN"): "groundnut_west_africa",
    ("groundnut", "GM"): "groundnut_west_africa",
    ("groundnut", "GN"): "groundnut_west_africa",
    ("millet",    "SN"): "millet_west_africa",
    ("millet",    "ML"): "millet_west_africa",
    ("millet",    "NE"): "millet_west_africa",
    ("sorghum",   "SN"): "sorghum_west_africa",
    ("sorghum",   "BF"): "sorghum_west_africa",
    ("maize",     "ET"): "maize_east_africa",
    ("maize",     "KE"): "maize_east_africa",
    ("teff",      "ET"): "teff_east_africa",
    ("rice",      "IN"): "rice_south_asia",
    ("rice",      "BD"): "rice_south_asia",
}

def get_growth_stage(crop: str, country_iso: str) -> GrowthStage:
    calendar_key  = CROP_CALENDAR_LOOKUP.get(
        (crop.lower(), country_iso.upper()), "default"
    )
    calendar      = CROP_CALENDARS[calendar_key]
    current_month = date.today().month
    for stage, (start, end) in calendar.items():
        if start <= end:
            if start <= current_month <= end:
                return stage
        else:
            if current_month >= start or current_month <= end:
                return stage
    return GrowthStage.POST_HARVEST

# ── CACHE ─────────────────────────────────────────────────────────────────────

def cache_set(key: str, data, ttl_hours: int = 6):
    cache_file = os.path.join(
        CACHE_DIR, hashlib.md5(key.encode()).hexdigest() + ".json"
    )
    payload = {
        "data":    data,
        "expires": (datetime.utcnow() + timedelta(hours=ttl_hours)).isoformat(),
    }
    with open(cache_file, "w") as f:
        json.dump(payload, f, default=str)

def cache_get(key: str):
    cache_file = os.path.join(
        CACHE_DIR, hashlib.md5(key.encode()).hexdigest() + ".json"
    )
    if not os.path.exists(cache_file):
        return None
    with open(cache_file) as f:
        payload = json.load(f)
    if datetime.utcnow() > datetime.fromisoformat(payload["expires"]):
        return None
    logger.info("cache_hit", key=key)
    return payload["data"]

# ── DISTRICT & FARMER REGISTRY ────────────────────────────────────────────────
# To add a new district: copy one block and update the values.
# The language field automatically determines the voice note language.

DISTRICTS = [
    {
        "id":          "sn_kaffrine_nord",
        "country_iso": "SN",
        "name":        "Kaffrine Nord",
        "region":      "west_africa",
        "lat":         14.105,
        "lon":         -15.551,
        "crops":       ["groundnut", "millet", "sorghum"],
        "languages":   ["french"],
        "channels":    [Channel.WHATSAPP],
        "timezone":    "Africa/Dakar",
        "fragile":     False,
    },
    # Irbid, Jordan
    {
        "id":          "jo_irbid",
        "country_iso": "JO",
        "name":        "Irbid",
        "region":      "middle_east",
        "lat":         32.55,
        "lon":         35.85,
        "crops":       ["wheat", "tomato", "olive"],
        "languages":   ["arabic"],
        "channels":    [Channel.TELEGRAM],
        "timezone":    "Asia/Amman",
        "fragile":     False,
    },
    # Uncomment to add more districts:
    # {
    #     "id":          "et_tigray_central",
    #     "country_iso": "ET",
    #     "name":        "Tigray Central",
    #     "region":      "east_africa",
    #     "lat":         14.032,
    #     "lon":         38.476,
    #     "crops":       ["teff", "sorghum", "maize"],
    #     "languages":   ["tigrinya"],
    #     "channels":    [Channel.SMS],
    #     "timezone":    "Africa/Addis_Ababa",
    #     "fragile":     True,
    # },
]

# Replace phone number with your own to receive test advisories
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
    # You — Kaffrine Nord (French)
    {
        "id":                 "test_telegram_001",
        "district_id":        "sn_kaffrine_nord",  # must match DISTRICTS id exactly
        "phone":              "telegram",
        "preferred_channel":  Channel.TELEGRAM,
        "preferred_language": "french",
        "crops":              ["groundnut", "millet"],
        "voice_notes":        True,
        "telegram_chat_id":   "8535333554",
    },
    # You — Irbid (Arabic)
    {
        "id":                 "test_telegram_irbid",
        "district_id":        "jo_irbid",
        "phone":              "telegram",
        "preferred_channel":  Channel.TELEGRAM,
        "preferred_language": "arabic",
        "crops":              ["wheat", "tomato", "olive"],
        "voice_notes":        True,
        "telegram_chat_id":   "8535333554",
    },
]

# ── HELPERS ───────────────────────────────────────────────────────────────────

def _trend(pct: float) -> TrendDirection:
    if pct > 15:    return TrendDirection.SPIKE
    elif pct > 3:   return TrendDirection.RISING
    elif pct < -15: return TrendDirection.CRASH
    elif pct < -3:  return TrendDirection.FALLING
    else:           return TrendDirection.STABLE

def _iso2_to_iso3(iso2: str) -> str:
    mapping = {
        "SN":"SEN","ML":"MLI","NE":"NER","BF":"BFA","GM":"GMB","GN":"GIN",
        "ET":"ETH","KE":"KEN","TZ":"TZA","UG":"UGA","SS":"SSD","SD":"SDN",
        "SO":"SOM","TD":"TCD","CF":"CAF","CD":"COD","NG":"NGA","GH":"GHA",
        "CM":"CMR","MZ":"MOZ","ZW":"ZWE","ZM":"ZMB","MW":"MWI","MG":"MDG",
        "IN":"IND","BD":"BGD","NP":"NPL","PK":"PAK","AF":"AFG","MM":"MMR",
        "KH":"KHM","LA":"LAO","HT":"HTI","NI":"NIC","GT":"GTM","HN":"HND",
        "YE":"YEM","SY":"SYR","IQ":"IRQ","LB":"LBN",
    }
    return mapping.get(iso2.upper(), iso2)

def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    import math
    R    = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a    = (math.sin(dlat/2)**2 +
            math.cos(math.radians(lat1)) *
            math.cos(math.radians(lat2)) *
            math.sin(dlon/2)**2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

# ── STEP 1: WEATHER ───────────────────────────────────────────────────────────

async def fetch_weather(district_id, lat, lon):
    cache_key = f"weather_{district_id}"
    cached    = cache_get(cache_key)
    if cached:
        return cached

    params = {
        "latitude":      lat,
        "longitude":     lon,
        "daily":         "precipitation_sum,temperature_2m_max,temperature_2m_min",
        "hourly":        "relativehumidity_2m",
        "forecast_days": 7,
        "timezone":      "auto",
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(
                "https://api.open-meteo.com/v1/forecast", params=params
            )
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        logger.error("weather_fetch_failed", error=str(e))
        stale = cache_get(f"{cache_key}_stale")
        if stale:
            stale["data_stale"] = True
            return stale
        raise

    daily        = data.get("daily", {})
    hourly       = data.get("hourly", {})
    precip       = daily.get("precipitation_sum", [0] * 7)
    tmax         = daily.get("temperature_2m_max", [0] * 7)
    tmin         = daily.get("temperature_2m_min", [0] * 7)
    humidity     = hourly.get("relativehumidity_2m", [0] * 168)
    rain_7d      = sum(p for p in precip if p is not None)
    rain_24h     = precip[0] if precip else 0.0
    avg_humidity = (sum(h for h in humidity[:24] if h) / 24) if humidity else 0.0
    spi          = _compute_spi_proxy(rain_7d, lat, date.today().month)

    result = {
        "district_id":  district_id,
        "rain_7d_mm":   rain_7d,
        "rain_24h_mm":  rain_24h,
        "temp_max_c":   tmax[0] or 0.0,
        "temp_min_c":   tmin[0] or 0.0,
        "humidity_pct": avg_humidity,
        "flood_risk":   min(100.0, rain_24h * 2.5) if rain_24h > 30 else 0.0,
        "spi":          spi,
        "source":       "open-meteo",
        "data_stale":   False,
    }
    cache_set(cache_key, result, ttl_hours=3)
    cache_set(f"{cache_key}_stale", result, ttl_hours=72)
    logger.info("weather_fetched", district=district_id,
                rain_7d=round(rain_7d, 1), spi=round(spi, 2))
    return result

def _compute_spi_proxy(rain_7d_mm, lat, month):
    abs_lat = abs(lat)
    if abs_lat < 15:
        norm = 35.0 if month in [6,7,8,9,10] else 5.0
    elif abs_lat < 25:
        norm = 20.0 if month in [7,8,9] else 2.0
    else:
        norm = 15.0
    if norm == 0:
        return 0.0
    return round(max(-3.0, min(3.0, ((rain_7d_mm - norm) / norm) * 2.0)), 2)

# ── STEP 2: MARKET PRICES — FAO GIEWS + FEWS NET ─────────────────────────────

async def fetch_market_prices(district_id, country_iso, crops):
    cache_key = f"market_{district_id}"
    cached    = cache_get(cache_key)
    if cached:
        return cached

    prices = []

    # Source 1: FAO GIEWS — free, no token needed
    try:
        giews = await _fetch_fao_giews(district_id, country_iso, crops)
        prices.extend(giews)
        logger.info("fao_giews_fetched", district=district_id, count=len(giews))
    except Exception as e:
        logger.warning("fao_giews_failed", error=str(e))

    # Source 2: FEWS NET — free, no token needed
    try:
        fews = await _fetch_fews_net(district_id, country_iso, crops)
        existing = {p["crop"] for p in prices}
        new_fews = [p for p in fews if p["crop"] not in existing]
        prices.extend(new_fews)
        logger.info("fews_net_fetched", district=district_id, count=len(fews))
    except Exception as e:
        logger.warning("fews_net_failed", error=str(e))

    if prices:
        cache_set(cache_key, prices, ttl_hours=12)
    return prices

async def _fetch_fao_giews(district_id, country_iso, crops):
    """
    FAO GIEWS Food Price Monitoring and Analysis Tool.
    Free, open, no registration needed.
    https://fpma.fao.org/giews/fpmat4/
    """
    iso3   = _iso2_to_iso3(country_iso)
    url    = "https://fpma.fao.org/giews/fpmat4/global/"
    params = {"iso3": iso3, "format": "json", "limit": 100}

    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(url, params=params, follow_redirects=True)
        r.raise_for_status()
        data = r.json()

    records = data.get("data", data) if isinstance(data, dict) else data
    prices  = []
    for record in (records or []):
        commodity = str(record.get("commodity", "")).lower()
        if not any(crop.lower() in commodity for crop in crops):
            continue
        price = record.get("price") or record.get("value")
        if price is None:
            continue
        prev = record.get("prev_price") or record.get("previous_value")
        pct  = ((float(price) - float(prev)) / float(prev) * 100
                if prev and float(prev) > 0 else 0.0)
        prices.append({
            "crop":        commodity,
            "price_local": float(price),
            "currency":    record.get("currency", "USD"),
            "unit":        record.get("unit", "kg"),
            "market_name": record.get("market", record.get("market_name", "unknown")),
            "trend":       _trend(pct),
            "trend_pct":   round(pct, 1),
            "source":      "fao-giews",
        })
    return prices

async def _fetch_fews_net(district_id, country_iso, crops):
    """
    FEWS NET market prices — free, no token needed.
    Covers 30+ food-insecure countries.
    https://fdw.fews.net/api/
    """
    url    = "https://fdw.fews.net/api/marketprice/"
    params = {"country_code": country_iso, "format": "json", "page_size": 100}

    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
        data = r.json()

    prices = []
    for record in data.get("results", []):
        commodity = record.get("commodity", "").lower()
        if not any(crop.lower() in commodity for crop in crops):
            continue
        price = record.get("price")
        if price is None:
            continue
        prices.append({
            "crop":        commodity,
            "price_local": float(price),
            "currency":    record.get("currency_name", "USD"),
            "unit":        record.get("unit_name", "kg"),
            "market_name": record.get("market_name", "unknown"),
            "trend":       TrendDirection.STABLE,
            "trend_pct":   0.0,
            "source":      "fews-net",
        })
    return prices

# ── STEP 3: SHOCK SIGNALS — WORLD BANK + ACLED ───────────────────────────────

async def fetch_shocks(district_id, country_iso, lat, lon):
    cache_key = f"shocks_{district_id}"
    cached    = cache_get(cache_key)
    if cached:
        return cached

    shocks = []

    try:
        wb = await _fetch_wb_rtp(district_id)
        shocks.extend(wb)
    except Exception as e:
        logger.warning("wb_rtp_failed", error=str(e))

    if ACLED_API_KEY and ACLED_EMAIL:
        try:
            conflict = await _fetch_acled_events(
                district_id, country_iso, lat, lon
            )
            shocks.extend(conflict)
        except Exception as e:
            logger.warning("acled_failed", error=str(e))
    else:
        logger.info("acled_skipped", note="Register free at acleddata.com")

    if shocks:
        cache_set(cache_key, shocks, ttl_hours=6)
    return shocks

async def _fetch_wb_rtp(district_id):
    """
    World Bank commodity price API — free, no token.
    Fetches fertilizer price index (AG.PRD.FERT.ZS).
    """
    WB_URL = (
        "https://api.worldbank.org/v2/en/indicator/AG.PRD.FERT.ZS"
        "?format=json&mrv=2&per_page=2"
    )
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.get(WB_URL)
        r.raise_for_status()
        data = r.json()

    shocks  = []
    records = data[1] if isinstance(data, list) and len(data) > 1 else []
    values  = [
        float(rec["value"])
        for rec in records
        if rec.get("value") is not None
    ]

    if len(values) >= 2:
        current     = values[0]
        previous    = values[1]
        pct         = (current - previous) / previous * 100
        is_shock    = abs(pct) > 10
        level_alert = current > 150

        if is_shock or level_alert:
            reasons = []
            if is_shock:
                reasons.append(
                    f"Global fertilizer index moved {pct:+.1f}% vs last period"
                )
            if level_alert:
                reasons.append(
                    f"Fertilizer index at {current:.0f} — historically elevated"
                )
            shocks.append({
                "type":         "price_shock",
                "input_type":   "fertilizer",
                "trend_pct":    round(pct, 1),
                "shock_reason": ". ".join(reasons),
                "severity":     "high" if abs(pct) > 20 else "medium",
                "source":       "world-bank-api",
            })
    return shocks

async def _fetch_acled_events(district_id, country_iso, lat, lon):
    """
    ACLED conflict events — free API (register at acleddata.com).
    Fetches events within 200km of district in last 30 days.
    """
    url    = "https://api.acleddata.com/acled/read"
    params = {
        "key":              ACLED_API_KEY,
        "email":            ACLED_EMAIL,
        "country":          country_iso,
        "event_date":       (date.today() - timedelta(days=30)).strftime("%Y-%m-%d"),
        "event_date_where": ">=",
        "limit":            50,
        "fields":           "event_date|event_type|fatalities|location|latitude|longitude",
    }
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
        data = r.json()

    events = data.get("data", [])
    nearby = []
    for event in events:
        try:
            if _haversine_km(
                lat, lon,
                float(event.get("latitude", 0)),
                float(event.get("longitude", 0))
            ) <= 200:
                nearby.append(event)
        except Exception:
            continue

    violent = [
        e for e in nearby
        if e.get("event_type") in (
            "Battles",
            "Violence against civilians",
            "Explosions/Remote violence",
        )
    ]

    if not violent:
        return []

    return [{
        "type":         "conflict_signal",
        "input_type":   "supply routes",
        "trend_pct":    0.0,
        "shock_reason": (
            f"{len(violent)} conflict event(s) within 200km in last 30 days. "
            f"Input supply routes may be disrupted. "
            f"Check local availability before purchasing."
        ),
        "severity":     "high" if len(violent) > 3 else "medium",
        "source":       "acled",
    }]

# ── STEP 4: PEST MONITORING ───────────────────────────────────────────────────

async def fetch_pest_alerts(district_id, country_iso, crops, weather):
    cache_key = f"pests_{district_id}"
    cached    = cache_get(cache_key)
    if cached:
        return cached

    alerts = []

    # FAO FAMEWS fall armyworm alerts
    if any(c in ["maize", "sorghum", "millet"] for c in crops):
        try:
            faw = await _fetch_famews(country_iso)
            alerts.extend(faw)
        except Exception as e:
            logger.warning("famews_failed", error=str(e))

    # Weather-driven disease risk
    alerts.extend(_compute_disease_risk(crops, weather))

    if alerts:
        cache_set(cache_key, alerts, ttl_hours=12)

    logger.info("pest_alerts_fetched", district=district_id, count=len(alerts))
    return alerts

async def _fetch_famews(country_iso):
    """FAO FAMEWS fall armyworm monitoring — free."""
    url = "https://www.fao.org/famews/data/alerts"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(
                url,
                params={"country": country_iso, "format": "json"},
                follow_redirects=True,
            )
            if r.status_code != 200:
                return []
            data = r.json()
    except Exception:
        return []

    return [{
        "pest":     "fall armyworm",
        "severity": a.get("severity", "medium"),
        "message":  (
            f"FAO FAMEWS: fall armyworm activity in "
            f"{a.get('location', 'your region')}. "
            f"Inspect maize and sorghum leaves for egg masses and damage."
        ),
        "source":   "fao-famews",
    } for a in data.get("alerts", [])]

def _compute_disease_risk(crops, weather):
    """Weather-driven crop disease risk model."""
    alerts   = []
    tmax     = weather["temp_max_c"]
    humidity = weather["humidity_pct"]
    rain_7d  = weather["rain_7d_mm"]

    if any(c in crops for c in ["wheat", "sorghum"]):
        if 15 <= tmax <= 25 and humidity > 70:
            alerts.append({
                "pest":     "rust disease",
                "severity": "medium",
                "message":  (
                    "Cool humid conditions favour rust in wheat and sorghum. "
                    "Inspect leaves for orange-brown pustules."
                ),
                "source":   "weather-model",
            })

    if any(c in crops for c in ["potato", "tomato"]):
        if tmax < 22 and rain_7d > 20:
            alerts.append({
                "pest":     "late blight",
                "severity": "high",
                "message":  (
                    "Conditions highly favourable for late blight. "
                    "Check for dark water-soaked lesions. "
                    "Apply copper-based fungicide as prevention."
                ),
                "source":   "weather-model",
            })

    if any(c in crops for c in ["groundnut", "maize"]):
        if tmax > 32 and rain_7d < 10:
            alerts.append({
                "pest":     "aflatoxin risk",
                "severity": "high",
                "message":  (
                    "Hot dry conditions increase aflatoxin risk in groundnut "
                    "and maize. Harvest promptly and dry grain below 13% moisture "
                    "before storage."
                ),
                "source":   "weather-model",
            })

    return alerts

# ── STEP 5: SCORE HAZARDS ─────────────────────────────────────────────────────

def score_hazards(weather, pest_alerts, shocks, growth_stage):
    """
    Multi-hazard scoring with cascade detection and growth stage awareness.
    Two or more HIGH hazards simultaneously triggers EXTREME composite.
    """
    spi  = weather.get("spi", 0.0)
    rain = weather["rain_7d_mm"]
    r24  = weather["rain_24h_mm"]
    tmax = weather["temp_max_c"]

    # SPI-based drought scoring
    if   spi <= -2.0: drought = 90.0
    elif spi <= -1.5: drought = 70.0
    elif spi <= -1.0: drought = 50.0
    elif spi <= -0.5: drought = 30.0
    elif spi >   0.5: drought = 5.0
    else:
        drought = (
            85.0 if rain < 5  else
            60.0 if rain < 15 else
            35.0 if rain < 30 else
            15.0 if rain < 50 else 5.0
        )

    flood = (
        95.0 if r24 > 80 else
        75.0 if r24 > 50 else
        50.0 if r24 > 30 else
        25.0 if r24 > 15 else 0.0
    )

    high_pests = [a for a in pest_alerts if a.get("severity") == "high"]
    med_pests  = [a for a in pest_alerts if a.get("severity") == "medium"]
    pest = (
        80.0 if high_pests else
        45.0 if med_pests  else
        25.0 if tmax > 30  else 10.0
    )

    # Growth stage multipliers — drought at flowering is catastrophic
    multipliers = {
        GrowthStage.FLOWERING:   1.5,
        GrowthStage.GRAIN_FILL:  1.3,
        GrowthStage.VEGETATIVE:  1.1,
        GrowthStage.PLANTING:    1.0,
        GrowthStage.HARVEST:     0.8,
        GrowthStage.POST_HARVEST:0.3,
        GrowthStage.PRE_SEASON:  0.3,
    }
    drought = min(100.0, drought * multipliers.get(growth_stage, 1.0))

    # Conflict amplification
    if any(s.get("type") == "conflict_signal" for s in shocks):
        drought = min(100.0, drought * 1.2)
        pest    = min(100.0, pest    * 1.1)

    def level(s):
        return (
            HazardLevel.EXTREME if s >= 80 else
            HazardLevel.HIGH    if s >= 60 else
            HazardLevel.MEDIUM  if s >= 35 else
            HazardLevel.LOW     if s >= 15 else
            HazardLevel.NONE
        )

    rank       = {"none":0,"low":1,"medium":2,"high":3,"extreme":4}
    dl, fl, pl = level(drought), level(flood), level(pest)
    high_count = sum(1 for lv in [dl, fl, pl] if rank[lv.value] >= rank["high"])
    cascade    = high_count >= 2
    composite  = (
        HazardLevel.EXTREME if cascade
        else max([dl, fl, pl], key=lambda x: rank[x.value])
    )

    return {
        "drought_level": dl,
        "flood_level":   fl,
        "pest_level":    pl,
        "composite":     composite,
        "drought_score": round(drought, 1),
        "flood_score":   round(flood, 1),
        "pest_score":    round(pest, 1),
        "cascade":       cascade,
        "growth_stage":  growth_stage,
        "spi":           spi,
    }

# ── STEP 6: AGRONOMIC ACTIONS ─────────────────────────────────────────────────


# ── AGRONOMIC ACTION TABLES (MULTILINGUAL) ────────────────────────────────────

ACTIONS = {
    "english": {
        "drought_flowering": {
            "groundnut":"CRITICAL: drought at flowering reduces yield 50-70%. Irrigate immediately.",
            "maize":    "CRITICAL: drought at silking causes permanent loss. Irrigate 25-50mm now.",
            "wheat":    "CRITICAL: irrigate immediately — drought at flowering causes permanent yield loss.",
            "tomato":   "CRITICAL: drought causes flower drop. Irrigate 20-30mm immediately.",
            "default":  "CRITICAL: flowering is the most drought-sensitive stage. Irrigate immediately.",
        },
        "drought_grain_fill": {
            "groundnut":"Irrigate to support pod filling. Plan early harvest if drought continues 10+ days.",
            "wheat":    "Irrigate to support grain fill. Consider early harvest if no water available.",
            "tomato":   "Maintain even soil moisture to prevent fruit cracking.",
            "default":  "Irrigate to support grain fill. Plan early harvest if drought continues.",
        },
        "drought_vegetative": {
            "groundnut":"Apply mulch to conserve moisture. Delay fertilizer until rain returns.",
            "millet":   "Millet is drought-tolerant at this stage. Monitor for 7 more days.",
            "sorghum":  "Sorghum tolerates drought here. Monitor for one more week.",
            "olive":    "Olive is drought-tolerant. No action needed unless dry for 3+ weeks.",
            "default":  "Apply mulch and delay fertilizer until rain returns.",
        },
        "drought_planting":   "Delay planting — wait for 20mm of rainfall before sowing. Seeds won't germinate in dry soil.",
        "drought_harvest":    "Dry conditions favour harvest. Proceed if crop is mature. Dry grain below 13% moisture before storage.",
        "drought_default":    "Conserve soil moisture — apply mulch, avoid tillage, delay fertilizer.",
        "flood": {
            "groundnut":"Clear drainage immediately. No fertilizer before heavy rain.",
            "rice":     "Monitor paddy level — excess water beyond 15cm damages plants.",
            "maize":    "Clear drainage — maize cannot tolerate waterlogging beyond 48 hours.",
            "tomato":   "Ensure drainage — tomatoes are highly sensitive to waterlogging.",
            "default":  "Clear drainage channels. No fertilizer or pesticide before heavy rain.",
        },
        "pest":         "Inspect {crop} fields today — conditions favour pest outbreaks. Check leaf undersides. Contact extension officer if 10%+ plants damaged.",
        "stage_advice": {
            "planting":    "Good planting conditions. Ensure seeds are treated before sowing.",
            "vegetative":  "Favourable conditions. Good time for top-dressing if rain is forecast.",
            "flowering":   "Critical stage — monitor closely and ensure adequate moisture.",
            "grain_fill":  "Avoid crop stress. Continue normal management.",
            "harvest":     "Monitor maturity. Prepare clean dry storage before harvesting.",
            "post_harvest":"Good time to prepare land, source inputs, and plan next season.",
            "default":     "Conditions are favourable — continue normal management.",
        },
    },
    "french": {
        "drought_flowering": {
            "groundnut":"CRITIQUE: la sécheresse à la floraison réduit le rendement de 50-70%. Irriguer immédiatement.",
            "maize":    "CRITIQUE: la sécheresse à la fécondation cause des pertes permanentes. Irriguer 25-50mm maintenant.",
            "millet":   "CRITIQUE: irriguer immédiatement si possible. La floraison est le stade le plus sensible.",
            "default":  "CRITIQUE: la floraison est le stade le plus sensible à la sécheresse. Irriguer immédiatement.",
        },
        "drought_grain_fill": {
            "groundnut":"Irriguer pour le remplissage des gousses. Envisager une récolte précoce si la sécheresse dure 10+ jours.",
            "millet":   "Irriguer si possible pour soutenir le remplissage des grains.",
            "default":  "Irriguer pour soutenir le remplissage. Envisager une récolte précoce si nécessaire.",
        },
        "drought_vegetative": {
            "groundnut":"Appliquer un paillis pour conserver l'humidité. Retarder les engrais jusqu'au retour de la pluie.",
            "millet":   "Le mil est tolérant à la sécheresse à ce stade. Surveiller 7 jours supplémentaires.",
            "sorghum":  "Le sorgho tolère la sécheresse ici. Surveiller une semaine de plus.",
            "default":  "Appliquer un paillis et retarder les engrais jusqu'au retour de la pluie.",
        },
        "drought_planting":   "Retarder la plantation — attendre 20mm de pluie avant de semer. Les graines ne germent pas dans un sol sec.",
        "drought_harvest":    "Les conditions sèches favorisent la récolte. Procéder si la culture est mature. Sécher les grains à moins de 13% d'humidité.",
        "drought_default":    "Conserver l'humidité du sol — paillis, éviter le labour, retarder les engrais.",
        "flood": {
            "groundnut":"Dégager les canaux de drainage immédiatement. Ne pas appliquer d'engrais avant les fortes pluies.",
            "rice":     "Surveiller le niveau d'eau — une eau excessive au-delà de 15cm endommage les plants.",
            "maize":    "S'assurer du drainage — le maïs ne tolère pas l'engorgement plus de 48 heures.",
            "default":  "Dégager les canaux de drainage. Pas d'engrais ou pesticides avant les fortes pluies.",
        },
        "pest":         "Inspecter les champs de {crop} aujourd'hui — conditions favorables aux infestations. Vérifier le dessous des feuilles. Contacter l'agent d'encadrement si 10%+ des plants sont touchés.",
        "stage_advice": {
            "planting":    "Bonnes conditions pour la plantation. S'assurer que les semences sont traitées.",
            "vegetative":  "Conditions favorables. Bon moment pour l'engrais de couverture si pluie prévue.",
            "flowering":   "Stade critique — surveiller de près et assurer une humidité adéquate.",
            "grain_fill":  "Éviter tout stress à ce stade. Continuer la gestion normale.",
            "harvest":     "Surveiller la maturité. Préparer un stockage propre et sec.",
            "post_harvest":"Bon moment pour préparer les terres et planifier la prochaine saison.",
            "default":     "Conditions favorables — continuer la gestion normale.",
        },
    },
    "arabic": {
        "drought_flowering": {
            "wheat":    "تحذير حرج: الجفاف خلال الإزهار يقلل المحصول 50-70٪. الري الفوري ضروري.",
            "tomato":   "تحذير حرج: الجفاف يسبب تساقط الأزهار. الري بـ 20-30 مم فوراً.",
            "olive":    "تحذير: الزيتون حساس للجفاف في الإزهار. الري إذا توفرت مياه.",
            "groundnut":"تحذير حرج: الجفاف خلال الإزهار يقلل المحصول بشدة. الري الفوري.",
            "default":  "تحذير حرج: الإزهار هو أكثر المراحل حساسية للجفاف. الري الفوري ضروري.",
        },
        "drought_grain_fill": {
            "wheat":  "الري لدعم امتلاء الحبوب. التخطيط للحصاد المبكر إذا استمر الجفاف 10+ أيام.",
            "tomato": "الحفاظ على رطوبة منتظمة في التربة لمنع تشقق الثمار.",
            "default":"الري لدعم امتلاء الحبوب. التخطيط لحصاد مبكر إذا استمر الجفاف.",
        },
        "drought_vegetative": {
            "wheat":  "تطبيق التغطية العضوية للحفاظ على الرطوبة. تأجيل التسميد حتى عودة الأمطار.",
            "tomato": "الري بانتظام مع تغطية التربة. تأجيل التسميد حتى تحسن الرطوبة.",
            "olive":  "الزيتون متحمل للجفاف في هذه المرحلة. المراقبة أسبوعاً إضافياً.",
            "default":"تطبيق التغطية العضوية وتأجيل التسميد حتى عودة الأمطار.",
        },
        "drought_planting":   "تأجيل الزراعة — انتظر هطول 20 مم على الأقل. البذور لن تنبت في تربة جافة.",
        "drought_harvest":    "الظروف الجافة مناسبة للحصاد وتجفيف الحبوب. المضي في الحصاد إذا اكتملت النضج. تجفيف الحبوب إلى أقل من 13٪ رطوبة.",
        "drought_default":    "الحفاظ على رطوبة التربة — تغطية عضوية، تجنب الحرث، تأجيل التسميد.",
        "flood": {
            "wheat":   "تنظيف قنوات الصرف فوراً. عدم إضافة أسمدة قبل الأمطار الغزيرة.",
            "tomato":  "التحقق من الصرف — الطماطم حساسة جداً للتشبع بالماء.",
            "olive":   "تنظيف قنوات الصرف — الزيتون لا يتحمل التشبع بالماء.",
            "default": "تنظيف قنوات الصرف. عدم إضافة أسمدة أو مبيدات قبل الأمطار.",
        },
        "pest":         "فحص حقول {crop} اليوم — الظروف مواتية لتفشي الآفات. فحص الجهة السفلية من الأوراق. التواصل مع المرشد الزراعي إذا أُصيب أكثر من 10٪ من النباتات.",
        "stage_advice": {
            "planting":    "ظروف جيدة للزراعة. التأكد من معالجة البذور قبل الزراعة.",
            "vegetative":  "ظروف مواتية. وقت مناسب لإضافة السماد التكميلي إذا كانت الأمطار متوقعة.",
            "flowering":   "مرحلة حرجة — المراقبة الدقيقة وضمان الرطوبة الكافية.",
            "grain_fill":  "تجنب أي إجهاد للمحصول. الاستمرار في الإدارة الطبيعية.",
            "harvest":     "مراقبة النضج. تجهيز مخازن نظيفة وجافة قبل الحصاد.",
            "post_harvest":"وقت مناسب لتجهيز الأرض وتوفير المستلزمات والتخطيط للموسم القادم.",
            "default":     "الظروف مواتية — الاستمرار في الإدارة الطبيعية.",
        },
    },
}


def get_action(crop, scores, district):
    """
    Growth-stage-aware multilingual agronomic action lookup.
    Language determined by district setting.
    Never AI-generated — validated agronomic rules only.
    """
    language = district.get("languages", ["english"])
    if isinstance(language, list):
        language = language[0] if language else "english"
    language = language.lower()

    lang_actions = ACTIONS.get(language, ACTIONS["english"])
    c     = crop.lower()
    stage = scores["growth_stage"]
    dl    = scores["drought_level"]
    fl    = scores["flood_level"]
    pl    = scores["pest_level"]

    if dl in (HazardLevel.HIGH, HazardLevel.EXTREME):
        if stage == GrowthStage.FLOWERING:
            t = lang_actions["drought_flowering"]
            return t.get(c, t["default"])
        elif stage == GrowthStage.GRAIN_FILL:
            t = lang_actions["drought_grain_fill"]
            return t.get(c, t["default"])
        elif stage == GrowthStage.VEGETATIVE:
            t = lang_actions["drought_vegetative"]
            return t.get(c, t["default"])
        elif stage == GrowthStage.PLANTING:
            return lang_actions["drought_planting"]
        else:
            return lang_actions["drought_harvest"]

    if fl in (HazardLevel.HIGH, HazardLevel.EXTREME):
        t = lang_actions["flood"]
        return t.get(c, t["default"])

    if pl in (HazardLevel.HIGH, HazardLevel.EXTREME):
        return lang_actions["pest"].replace("{crop}", crop)

    adv = lang_actions["stage_advice"]
    return adv.get(stage.value, adv["default"])


# ── STEP 7: GENERATE ADVISORY ─────────────────────────────────────────────────

async def generate_advisory(
    district, weather, scores, crop_prices,
    shocks, pest_alerts, language, crop
):
    if not ANTHROPIC_API_KEY:
        logger.warning("no_anthropic_key_using_template")
        return _template_advisory(
            district, weather, scores, crop_prices, shocks, pest_alerts, crop
        )

    action       = get_action(crop, scores, district)
    stage        = scores["growth_stage"]
    cascade_note = (
        " WARNING: multiple hazards occurring simultaneously — elevated risk."
        if scores["cascade"] else ""
    )
    stale_note = (
        " Note: weather data may be up to 72 hours old."
        if weather.get("data_stale") else ""
    )
    pest_note = (
        " ".join(a["message"] for a in pest_alerts[:1])
        if pest_alerts else ""
    )

    weather_facts = (
        f"WEATHER for {district['name']} — next 7 days:\n"
        f"- Rain: {weather['rain_7d_mm']:.0f}mm total | "
        f"Next 24h: {weather['rain_24h_mm']:.0f}mm\n"
        f"- Temperature: {weather['temp_min_c']:.0f}C to {weather['temp_max_c']:.0f}C\n"
        f"- Drought index (SPI): {weather['spi']:+.1f} "
        f"({'below' if weather['spi'] < 0 else 'above'} seasonal normal)\n"
        f"- Drought: {scores['drought_level'].value} | "
        f"Flood: {scores['flood_level'].value} | "
        f"Pest: {scores['pest_level'].value}\n"
        f"- Crop growth stage: {stage.value}\n"
        f"- Recommended action for {crop}: {action}"
        f"{cascade_note}{stale_note}"
    )

    market_facts = "CROP MARKET PRICES:\n" + (
        "\n".join(
            f"- {p['crop'].title()}: {p['price_local']:.0f} {p['currency']}/{p['unit']} "
            f"at {p['market_name']} — {p['trend'].value} ({p['trend_pct']:+.0f}%) "
            f"[{p['source']}]"
            for p in crop_prices[:3]
        ) or "- No market price data available today."
    )

    shock_list  = shocks or []
    shock_facts = "AGRICULTURAL INPUTS AND RISKS:\n" + (
        "\n".join(
            f"- {s.get('input_type', 'inputs').title()}: {s['shock_reason']}"
            for s in shock_list
        ) or "- No significant input price shocks or conflict signals detected."
    )
    if pest_note:
        shock_facts += f"\n- PEST ALERT: {pest_note}"

    prompt = (
        f"{weather_facts}\n\n"
        f"{market_facts}\n\n"
        f"{shock_facts}\n\n"
        f"Write a farmer advisory in {language} for the {stage.value} "
        f"stage of {crop}. Keep it practical and clear.\n"
        f"Respond ONLY as JSON:\n"
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
                    "You are AgriEWS, an agricultural early warning assistant "
                    "for smallholder farmers in developing countries. "
                    "Convert structured data into clear, actionable advisories. "
                    "Use simple language with no technical jargon. "
                    "2-3 sentences per section. "
                    "If cascade or conflict signals are present, emphasise urgency. "
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


def _translate_action(action_en: str, language: str) -> str:
    """
    Translate English agronomic action to target language.
    Uses keyword replacement for common agronomic terms.
    Full translation improves significantly with Anthropic API key.
    """
    if language == "english":
        return action_en

    if language == "french":
        replacements = [
            ("irrigate immediately","irriguer immédiatement"),
            ("Irrigate immediately","Irriguer immédiatement"),
            ("CRITICAL:","CRITIQUE :"),
            ("irrigate","irriguer"),
            ("Irrigate","Irriguer"),
            ("drought","sécheresse"),
            ("flooding","inondation"),
            ("waterlogging","engorgement"),
            ("drainage channels","canaux de drainage"),
            ("Clear drainage","Dégager les canaux"),
            ("fertilizer","engrais"),
            ("Fertilizer","Engrais"),
            ("pesticide","pesticide"),
            ("mulch","paillis"),
            ("harvest","récolte"),
            ("Harvest","Récolter"),
            ("yield loss","perte de rendement"),
            ("planting","semis"),
            ("Planting","Semis"),
            ("sowing","semis"),
            ("germinate","germer"),
            ("soil moisture","humidité du sol"),
            ("top-dressing","fumure de couverture"),
            ("storage","stockage"),
            ("drying","séchage"),
            ("aflatoxin","aflatoxine"),
            ("pest","ravageur"),
            ("Pest","Ravageur"),
            ("disease","maladie"),
            ("extension officer","agent agricole"),
            ("inspect","inspecter"),
            ("Inspect","Inspecter"),
            ("monitor","surveiller"),
            ("Monitor","Surveiller"),
            ("conditions favourable","conditions favorables"),
            ("Conditions favourable","Conditions favorables"),
            ("continue normal management","continuer la gestion normale"),
            ("Good planting conditions","Bonnes conditions de semis"),
            ("Good time to apply","Bon moment pour appliquer"),
            ("rain is forecast","pluie prévue"),
            ("Critical growth stage","Stade critique de croissance"),
            ("Avoid any stress","Éviter tout stress"),
            ("Monitor crop maturity","Surveiller la maturité"),
            ("prepare clean, dry storage","préparer un stockage propre et sec"),
            ("prepare land","préparer le sol"),
            ("plan next season","planifier la prochaine saison"),
            ("no action needed","aucune action nécessaire"),
            ("at least","au moins"),
            ("if possible","si possible"),
            ("if available","si disponible"),
            ("immediately","immédiatement"),
            ("days","jours"),
            ("weeks","semaines"),
            ("below 13% moisture","à moins de 13% d'humidité"),
        ]
        result = action_en
        for en, fr in replacements:
            result = result.replace(en, fr)
        return result

    if language == "arabic":
        replacements = [
            ("CRITICAL:","تحذير:"),
            ("irrigate immediately","ري فوري"),
            ("Irrigate immediately","الري فوراً"),
            ("irrigate","الري"),
            ("Irrigate","الري"),
            ("drought","الجفاف"),
            ("flooding","الفيضان"),
            ("waterlogging","تشبع التربة بالماء"),
            ("drainage channels","قنوات الصرف"),
            ("Clear drainage","تنظيف قنوات الصرف"),
            ("fertilizer","الأسمدة"),
            ("Fertilizer","الأسمدة"),
            ("pesticide","المبيدات"),
            ("mulch","التغطية العضوية"),
            ("harvest","الحصاد"),
            ("Harvest","الحصاد"),
            ("yield loss","خسارة المحصول"),
            ("planting","الزراعة"),
            ("soil moisture","رطوبة التربة"),
            ("storage","التخزين"),
            ("drying","التجفيف"),
            ("aflatoxin","الأفلاتوكسين"),
            ("pest","الآفات"),
            ("Pest","الآفات"),
            ("disease","الأمراض"),
            ("extension officer","المرشد الزراعي"),
            ("inspect","فحص"),
            ("Inspect","فحص"),
            ("monitor","مراقبة"),
            ("Monitor","مراقبة"),
            ("conditions favourable","الظروف مناسبة"),
            ("continue normal management","استمر في الإدارة الطبيعية"),
            ("immediately","فوراً"),
            ("days","أيام"),
            ("weeks","أسابيع"),
            ("below 13% moisture","أقل من 13% رطوبة"),
            ("if possible","إن أمكن"),
            ("if available","إن توفر"),
            ("at least","على الأقل"),
        ]
        result = action_en
        for en, ar in replacements:
            result = result.replace(en, ar)
        return result

    return action_en

# ── MULTILINGUAL TEMPLATES ────────────────────────────────────────────────────

TRANSLATIONS = {
    "french": {
        "hazard_labels": {
            "none":"Aucun risque","low":"Risque faible",
            "medium":"Surveillance","high":"Alerte","extreme":"Danger extrême",
        },
        "stage_labels": {
            "pre_season":"Pré-saison","planting":"Semis","vegetative":"Végétatif",
            "flowering":"Floraison","grain_fill":"Remplissage",
            "harvest":"Récolte","post_harvest":"Post-récolte",
        },
        "weather_intro":   "Prévisions météo sur 7 jours",
        "rain_label":      "Pluie",
        "spi_label":       "Indice de sécheresse (SPI)",
        "below_normal":    "en dessous de la normale saisonnière",
        "above_normal":    "au-dessus de la normale saisonnière",
        "action_label":    "Action recommandée",
        "cascade_warning": "ATTENTION : plusieurs risques simultanés.",
        "stale_warning":   "Note : données météo pouvant avoir jusqu'à 72h.",
        "market_no_data":  "Aucune donnée de prix disponible aujourd'hui.",
        "shock_none":      "Aucune alerte sur les intrants aujourd'hui.",
        "trend_labels": {
            "stable":"stable","rising":"en hausse","falling":"en baisse",
            "spike":"forte hausse","crash":"forte baisse",
        },
        "at":    "à",
        "in":    "à",
        "risk":  "Risque",
        "level": "Niveau",
    },
    "arabic": {
        "hazard_labels": {
            "none":"لا توجد مخاطر","low":"خطر منخفض",
            "medium":"مراقبة","high":"تحذير","extreme":"خطر شديد",
        },
        "stage_labels": {
            "pre_season":"ما قبل الموسم","planting":"الزراعة",
            "vegetative":"النمو الخضري","flowering":"الإزهار",
            "grain_fill":"امتلاء الحبوب","harvest":"الحصاد",
            "post_harvest":"ما بعد الحصاد",
        },
        "weather_intro":   "توقعات الطقس لـ 7 أيام",
        "rain_label":      "هطول الأمطار",
        "spi_label":       "مؤشر الجفاف",
        "below_normal":    "أقل من المعدل الموسمي",
        "above_normal":    "أعلى من المعدل الموسمي",
        "action_label":    "الإجراء الموصى به",
        "cascade_warning": "تحذير: مخاطر متعددة متزامنة — خطر مرتفع.",
        "stale_warning":   "ملاحظة: بيانات الطقس قد تكون قديمة حتى 72 ساعة.",
        "market_no_data":  "لا تتوفر بيانات أسعار اليوم.",
        "shock_none":      "لا تحذيرات على مستلزمات الإنتاج اليوم.",
        "trend_labels": {
            "stable":"مستقر","rising":"ارتفاع","falling":"انخفاض",
            "spike":"ارتفاع حاد","crash":"انخفاض حاد",
        },
        "at":    "في",
        "in":    "في",
        "risk":  "المستوى",
        "level": "المستوى",
    },
    "english": {
        "hazard_labels": {
            "none":"All clear","low":"Low risk",
            "medium":"Watch","high":"Alert","extreme":"Danger",
        },
        "stage_labels": {
            "pre_season":"Pre-season","planting":"Planting",
            "vegetative":"Vegetative","flowering":"Flowering",
            "grain_fill":"Grain fill","harvest":"Harvest",
            "post_harvest":"Post-harvest",
        },
        "weather_intro":   "7-day weather forecast",
        "rain_label":      "Rainfall",
        "spi_label":       "Drought index (SPI)",
        "below_normal":    "below seasonal normal",
        "above_normal":    "above seasonal normal",
        "action_label":    "Recommended action",
        "cascade_warning": "WARNING: multiple hazards simultaneously.",
        "stale_warning":   "Note: weather data may be up to 72h old.",
        "market_no_data":  "No market price data available today.",
        "shock_none":      "No input price alerts today.",
        "trend_labels": {
            "stable":"stable","rising":"rising","falling":"falling",
            "spike":"spike","crash":"crash",
        },
        "at":    "at",
        "in":    "at",
        "risk":  "Hazard",
        "level": "Level",
    },
}

def _get_t(language: str) -> dict:
    return TRANSLATIONS.get(language.lower(), TRANSLATIONS["english"])


def _template_advisory(district, weather, scores, crop_prices, shocks, pest_alerts, crop):
    """
    Multilingual template advisory — no Anthropic key needed.
    Generates proper French, Arabic, or English based on farmer language.
    """
    language = district.get("languages", ["english"])
    if isinstance(language, list):
        language = language[0] if language else "english"
    language = language.lower()

    t            = _get_t(language)
    action_en    = get_action(crop, scores, district)
    action       = _translate_action(action_en, language)
    stage        = scores["growth_stage"]
    stage_label  = t["stage_labels"].get(stage.value, stage.value)
    hazard_label = t["hazard_labels"].get(scores["composite"].value, scores["composite"].value)
    spi_dir      = t["below_normal"] if weather["spi"] < 0 else t["above_normal"]
    cascade      = f" {t['cascade_warning']}" if scores["cascade"] else ""
    stale        = f" {t['stale_warning']}" if weather.get("data_stale") else ""

    weather_section = (
        f"[{stage_label}] {t['weather_intro']}: "
        f"{t['rain_label']} {weather['rain_7d_mm']:.0f}mm / 7 jours. "
        f"{t['spi_label']}: {weather['spi']:+.1f} ({spi_dir}). "
        f"{t['risk']}: {hazard_label}.{cascade}{stale} "
        f"{t['action_label']}: {action}"
    ) if language == "french" else (
        f"[{stage_label}] {t['weather_intro']}: "
        f"{t['rain_label']} {weather['rain_7d_mm']:.0f} ملم / 7 أيام. "
        f"{t['spi_label']}: {weather['spi']:+.1f} ({spi_dir}). "
        f"{t['level']}: {hazard_label}.{cascade}{stale} "
        f"{t['action_label']}: {action}"
    ) if language == "arabic" else (
        f"[{stage_label}] {t['weather_intro']}: "
        f"{t['rain_label']} {weather['rain_7d_mm']:.0f}mm / 7 days. "
        f"{t['spi_label']}: {weather['spi']:+.1f} ({spi_dir}). "
        f"{t['risk']}: {hazard_label}.{cascade}{stale} "
        f"{t['action_label']}: {action}"
    )

    if crop_prices:
        p     = crop_prices[0]
        trend = t["trend_labels"].get(
            p["trend"].value if hasattr(p["trend"], "value") else p["trend"],
            str(p["trend"])
        )
        market_section = (
            f"{p['crop'].title()} {t['at']} {p['price_local']:.0f} "
            f"{p['currency']}/{p['unit']} {t['in']} {p['market_name']} "
            f"— {trend} ({p['trend_pct']:+.0f}%)."
        )
    else:
        market_section = t["market_no_data"]

    all_alerts = (
        [s["shock_reason"] for s in shocks] +
        [a["message"] for a in pest_alerts[:1]]
    )
    shock_section = " ".join(all_alerts) if all_alerts else t["shock_none"]

    return {
        "weather_section": weather_section,
        "market_section":  market_section,
        "shock_section":   shock_section,
        "lang":            language,
    }



# ── STEP 8: VOICE NOTE ────────────────────────────────────────────────────────

def generate_voice_note(advisory, language, district_name, crop, stage):
    """
    Convert advisory to voice note using gTTS.
    Free — no API key. Falls back to English if language TTS fails.
    """
    gtts_lang = LANGUAGE_TO_GTTS.get(language.lower(), "en")

    def clean(text):
        return (str(text).replace("*","").replace("_","")
                         .replace("#","").replace("[","").replace("]",""))

    intros = {
        "french":  f"Bonjour, voici votre bulletin AgriEWS pour {district_name}.",
        "arabic":  f"مرحباً، هذه نشرتكم الزراعية من AgriEWS لمنطقة {district_name}.",
        "english": f"Hello, this is your AgriEWS advisory for {district_name}.",
    }
    outros = {
        "french":  "Cette alerte est gratuite. Bonne journee.",
        "arabic":  "هذه النشرة مجانية. يوم سعيد.",
        "english": "This advisory is free. Have a good day.",
    }

    intro  = intros.get(language.lower(), intros["english"])
    outro  = outros.get(language.lower(), outros["english"])
    spoken = (
        f"{intro} "
        f"{clean(advisory['weather_section'])}. "
        f"{clean(advisory['market_section'])}. "
        f"{clean(advisory['shock_section'])}. "
        f"{outro}"
    )

    tmp_file = tempfile.NamedTemporaryFile(
        suffix=".mp3", delete=False, prefix="agriews_"
    )

    try:
        tts = gTTS(text=spoken, lang=gtts_lang, slow=False)
        tts.save(tmp_file.name)
        logger.info("voice_note_generated",
                    language=language, gtts_lang=gtts_lang)
        return tmp_file.name
    except Exception as e:
        logger.warning("gtts_lang_failed", lang=gtts_lang, error=str(e))
        try:
            fallback = (
                f"Hello, AgriEWS advisory for {district_name}. "
                f"{clean(advisory['weather_section'])}. "
                f"{clean(advisory['market_section'])}. "
                f"{clean(advisory['shock_section'])}. Free advisory."
            )
            tts = gTTS(text=fallback, lang="en", slow=False)
            tts.save(tmp_file.name)
            logger.info("voice_note_fallback_english_ok")
            return tmp_file.name
        except Exception as e2:
            logger.error("voice_note_failed_completely", error=str(e2))
            return None


# ── MESSAGE SANITISATION ──────────────────────────────────────────────────────

def _clean_advisory_text(text: str) -> str:
    """
    Clean advisory text for safe Telegram HTML delivery.
    Fixes all language issues: French, Arabic, English.
    - FAO citations [1],[2] → (1),(2) — brackets confuse Telegram Markdown
    - Stray HTML chars → escaped
    - Unmatched underscores → removed
    """
    import re
    if not text:
        return text
    # Convert FAO citation brackets [1] → (1)
    text = re.sub(r'\[(\d+)\]', r'(\1)', text)
    # Remove remaining unmatched brackets (keep content)
    text = re.sub(r'\[([^\]]*)\](?!\()', r'\1', text)
    # Escape HTML special chars
    text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    return text

# ── TELEGRAM DELIVERY ─────────────────────────────────────────────────────────

async def deliver_telegram(farmer, advisory, crop, scores, district):
    """
    Send advisory via Telegram Bot API.
    Completely free, no limits, no approval needed.
    Sends text advisory + voice note in farmer language.
    """
    if not TELEGRAM_BOT_TOKEN:
        logger.warning("telegram_no_token")
        return "failed"

    chat_id  = farmer.get("telegram_chat_id") or TELEGRAM_CHAT_ID
    if not chat_id:
        logger.warning("telegram_no_chat_id", farmer=farmer["id"])
        return "failed"

    LABELS = {
        HazardLevel.NONE:    "كل شيء على ما يرام" if advisory.get("lang") == "arabic" else "All clear",
        HazardLevel.LOW:     "خطر منخفض" if advisory.get("lang") == "arabic" else "Low risk",
        HazardLevel.MEDIUM:  "مراقبة" if advisory.get("lang") == "arabic" else "Watch",
        HazardLevel.HIGH:    "تحذير" if advisory.get("lang") == "arabic" else "Alert",
        HazardLevel.EXTREME: "خطر شديد" if advisory.get("lang") == "arabic" else "Danger",
    }

    hazard_level = scores["composite"]
    stage        = scores["growth_stage"]
    cascade_line = (
        "\n⚠️ <b>MULTIPLE HAZARDS — elevated risk</b>" if scores["cascade"] else ""
    )


    # Clean advisory sections for safe HTML delivery (all languages)
    weather_clean = _clean_advisory_text(advisory['weather_section'])
    market_clean  = _clean_advisory_text(advisory['market_section'])
    shock_clean   = _clean_advisory_text(advisory['shock_section'])

    message = (
        f"🌾 <b>AgriEWS Advisory</b> | {date.today().strftime('%d %b %Y')}\n"
        f"📍 <b>{district['name']}</b> | {crop.title()} | {stage.value}\n"
        f"🚨 Status: <b>{LABELS[hazard_level]}</b>"
        f"{cascade_line}\n\n"
        f"🌦 <b>Weather &amp; Action</b>\n{weather_clean}\n\n"
        f"📈 <b>Market</b>\n{market_clean}\n\n"
        f"⚡ <b>Inputs &amp; Alerts</b>\n{shock_clean}\n\n"
        f"<i>Reply /report to send a field observation</i>\n"
        f"<i>AgriEWS is free</i>"
        f"<i>AgriEWS is free</i>"
    )

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # Send text message
            r = await client.post(url, json={
                "chat_id":    chat_id,
                "text":       message,
                "parse_mode": "HTML",
            })
            r.raise_for_status()
            logger.info("telegram_text_sent", farmer=farmer["id"], chat_id=chat_id)

            # Send voice note if enabled
            if farmer.get("voice_notes") and TELEGRAM_BOT_TOKEN:
                audio_path = None
                try:
                    audio_path = generate_voice_note(
                        advisory,
                        farmer["preferred_language"],
                        district["name"],
                        crop,
                        stage,
                    )
                    voice_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendAudio"
                    with open(audio_path, "rb") as af:
                        vr = await client.post(
                            voice_url,
                            data={"chat_id": chat_id},
                            files={"audio": ("advisory.mp3", af, "audio/mpeg")},
                        )
                        vr.raise_for_status()
                    logger.info("telegram_voice_sent", farmer=farmer["id"])
                except Exception as e:
                    logger.error("telegram_voice_failed",
                                 farmer=farmer["id"], error=str(e))
                finally:
                    if audio_path and os.path.exists(audio_path):
                        os.remove(audio_path)

        return "sent"

    except Exception as e:
        logger.error("telegram_failed", farmer=farmer["id"], error=str(e))
        return "failed"

# ── MAIN PIPELINE ─────────────────────────────────────────────────────────────

# ── WHATSAPP DELIVERY ─────────────────────────────────────────────────────────

async def deliver_whatsapp(farmer, advisory, crop, scores, district):
    """Send advisory via WhatsApp Business API."""
    if not WHATSAPP_API_TOKEN or not WHATSAPP_PHONE_NUMBER_ID:
        logger.warning("whatsapp_no_token")
        return "failed"

    LABELS = {
        HazardLevel.NONE:    "All clear",
        HazardLevel.LOW:     "Low risk",
        HazardLevel.MEDIUM:  "Watch",
        HazardLevel.HIGH:    "Alert",
        HazardLevel.EXTREME: "Danger",
    }
    hazard_level = scores["composite"]
    stage        = scores["growth_stage"]
    cascade_line = (
        " | MULTIPLE HAZARDS"
        if scores["cascade"] else ""
    )

    lines = [
        f"*AgriEWS Advisory* | {date.today().strftime('%d %b %Y')}",
        f"*{district['name']}* | {crop.title()} | Stage: {stage.value}",
        f"Status: *{LABELS[hazard_level]}*{cascade_line}",
        "",
        "*Weather & Action*",
        advisory['weather_section'],
        "",
        "*Market*",
        advisory['market_section'],
        "",
        "*Inputs & Alerts*",
        advisory['shock_section'],
        "",
        "_Reply REPORT to send a field observation_",
        "_AgriEWS is free | Reply STOP to unsubscribe_",
    ]
    message = "\n".join(lines)

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

            if farmer.get("voice_notes") and WHATSAPP_PHONE_NUMBER_ID:
                audio_path = None
                try:
                    audio_path = generate_voice_note(
                        advisory, farmer["preferred_language"],
                        district["name"], crop, stage,
                    )
                    if audio_path:
                        with open(audio_path, "rb") as af:
                            up = await client.post(
                                f"https://graph.facebook.com/v19.0/{WHATSAPP_PHONE_NUMBER_ID}/media",
                                headers={"Authorization": f"Bearer {WHATSAPP_API_TOKEN}"},
                                files={"file": ("advisory.mp3", af, "audio/mpeg")},
                                data={"messaging_product": "whatsapp"},
                            )
                            up.raise_for_status()
                            media_id = up.json().get("id")
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
                        logger.info("whatsapp_voice_sent", farmer=farmer["id"])
                except Exception as e:
                    logger.error("whatsapp_voice_failed",
                                 farmer=farmer["id"], error=str(e))
                finally:
                    if audio_path and os.path.exists(audio_path):
                        try: os.remove(audio_path)
                        except: pass
        return "sent"
    except Exception as e:
        logger.error("whatsapp_failed", farmer=farmer["id"], error=str(e))
        return "failed"


async def run_pipeline():
    logger.info("agriews_v2_starting", districts=len(DISTRICTS))

    for district in DISTRICTS:
        log = logger.bind(district=district["id"])
        log.info("district_starting")

        try:
            weather     = await fetch_weather(
                district["id"], district["lat"], district["lon"]
            )
            crop_prices = await fetch_market_prices(
                district["id"], district["country_iso"], district["crops"]
            )
            shocks      = await fetch_shocks(
                district["id"], district["country_iso"],
                district["lat"], district["lon"]
            )
            pest_alerts = await fetch_pest_alerts(
                district["id"], district["country_iso"],
                district["crops"], weather
            )

            log.info("all_data_fetched",
                     district=district["id"],
                     rain_7d=round(weather["rain_7d_mm"], 1),
                     spi=weather["spi"],
                     prices=len(crop_prices),
                     shocks=len(shocks),
                     pests=len(pest_alerts),
                     data_stale=weather.get("data_stale", False))

            farmers = [
                f for f in FARMERS
                if f["district_id"] == district["id"]
            ]

            for farmer in farmers:
                # One combined advisory per farmer covering all their crops
                # Use the highest-risk crop as the primary crop for scoring
                primary_crop = farmer["crops"][0] if farmer["crops"] else "default"
                stage  = get_growth_stage(primary_crop, district["country_iso"])
                scores = score_hazards(weather, pest_alerts, shocks, stage)

                # Elevate scores for any additional crops
                for extra_crop in farmer["crops"][1:]:
                    extra_stage  = get_growth_stage(extra_crop, district["country_iso"])
                    extra_scores = score_hazards(weather, pest_alerts, shocks, extra_stage)
                    rank = {"none":0,"low":1,"medium":2,"high":3,"extreme":4}
                    if rank[extra_scores["composite"].value] > rank[scores["composite"].value]:
                        scores = extra_scores
                        primary_crop = extra_crop

                log.info("hazards_scored",
                         farmer=farmer["id"],
                         primary_crop=primary_crop,
                         stage=stage.value,
                         drought=scores["drought_level"].value,
                         flood=scores["flood_level"].value,
                         pest=scores["pest_level"].value,
                         composite=scores["composite"].value,
                         cascade=scores["cascade"])

                # Pass farmer language to district for template
                district_with_lang = {
                    **district,
                    "languages": [farmer["preferred_language"]],
                }

                # Use RAG (FAO/IFAD grounded) if available, else template
                if RAG_AVAILABLE:
                    advisory = await generate_advisory_rag(
                        district=district_with_lang,
                        weather=weather,
                        scores=scores,
                        crop_prices=crop_prices,
                        shocks=shocks,
                        pest_alerts=pest_alerts,
                        language=farmer["preferred_language"],
                        crop=primary_crop,
                    )
                else:
                    advisory = await generate_advisory(
                        district=district_with_lang,
                        weather=weather,
                        scores=scores,
                        crop_prices=crop_prices,
                        shocks=shocks,
                        pest_alerts=pest_alerts,
                        language=farmer["preferred_language"],
                        crop=primary_crop,
                    )

                if farmer["preferred_channel"] == Channel.WHATSAPP:
                    status = await deliver_whatsapp(
                        farmer=farmer,
                        advisory=advisory,
                        crop=primary_crop,
                        scores=scores,
                        district=district,
                    )
                elif farmer["preferred_channel"] == Channel.TELEGRAM:
                    status = await deliver_telegram(
                        farmer=farmer,
                        advisory=advisory,
                        crop=primary_crop,
                        scores=scores,
                        district=district,
                    )
                else:
                    status = "no_channel"

                log.info("advisory_delivered",
                         farmer=farmer["id"],
                         crop=primary_crop,
                         stage=stage.value,
                         language=farmer["preferred_language"],
                         composite=scores["composite"].value,
                         cascade=scores["cascade"],
                         voice_note=farmer.get("voice_notes", False),
                         status=status)

        except Exception as e:
            log.error("district_failed",
                      district=district["id"], error=str(e))
            continue

    # Build knowledge base on first run if not ready
    try:
        from knowledge.retriever import is_kb_ready, get_kb_size
        from knowledge.ingest import build_knowledge_base
        if not is_kb_ready():
            logger.info("kb_building_first_time")
            result = build_knowledge_base()
            logger.info("kb_built",
                        docs_success=result.get("success", 0),
                        chunks=result.get("chunks", 0))
        else:
            logger.info("kb_ready", chunks=get_kb_size())
    except Exception as e:
        logger.warning("kb_build_failed", error=str(e))

    logger.info("agriews_v2_complete")


if __name__ == "__main__":
    asyncio.run(run_pipeline())
