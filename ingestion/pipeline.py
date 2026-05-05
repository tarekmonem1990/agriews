"""
ingestion/pipeline.py
Data ingestion pipeline — pulls all three data streams:
1. Weather forecasts from Open-Meteo (free, no key needed)
2. Crop market prices from WFP VAM (free, no key needed)
3. Input price shocks from World Bank RTP (free, no key needed)

All sources are open and free — no proprietary data.
"""
import httpx
from datetime import datetime, date
from config.models import (
    WeatherForecast, CropPrice, InputPrice,
    TrendDirection, District
)
import structlog

logger = structlog.get_logger()


# ── WEATHER ───────────────────────────────────────────────────────────────────

async def fetch_weather(
    district_id: str,
    lat: float,
    lon: float
) -> WeatherForecast:
    """
    Fetch 7-day weather forecast from Open-Meteo.
    Free, no API key required, global coverage.
    https://open-meteo.com
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "precipitation_sum,temperature_2m_max,temperature_2m_min",
        "forecast_days": 7,
        "timezone": "auto",
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

    # Simple flood risk heuristic
    # Replaced by ML model in intelligence layer for production
    flood_risk = min(100.0, rain_24h * 2.5) if rain_24h > 30 else 0.0

    logger.info("weather_fetched",
                district=district_id,
                rain_7d=round(rain_7d, 1),
                rain_24h=round(rain_24h, 1))

    return WeatherForecast(
        district_id=district_id,
        fetched_at=datetime.utcnow(),
        forecast_date=date.today(),
        rain_7d_mm=rain_7d,
        rain_24h_mm=rain_24h,
        temp_max_c=tmax[0] or 0.0,
        temp_min_c=tmin[0] or 0.0,
        humidity_pct=0.0,
        flood_risk_score=flood_risk,
        source="open-meteo",
    )


# ── MARKET PRICES ─────────────────────────────────────────────────────────────

async def fetch_market_prices(
    district_id: str,
    country_iso: str,
    crops: list[str]
) -> list[CropPrice]:
    """
    Fetch crop market prices from WFP VAM.
    Free, no API key required. Covers 90+ countries.
    https://dataviz.vam.wfp.org/api/
    """
    url = "https://api.vam.wfp.org/MarketPrices/PriceMonthly"
    params = {"CountryCode": country_iso, "format": "json"}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(url, params=params)
            r.raise_for_status()
            records = r.json()
    except Exception as e:
        logger.warning("market_fetch_failed",
                       district=district_id, error=str(e))
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
        trend, pct = _calc_trend(float(price), prev)

        prices.append(CropPrice(
            district_id=district_id,
            fetched_at=datetime.utcnow(),
            crop=commodity,
            price_local=float(price),
            currency=record.get("CurrencyName", "USD"),
            unit=record.get("UnitName", "kg"),
            market_name=record.get("MarketName", "unknown"),
            trend=trend,
            trend_pct=pct,
            source="wfp-vam",
        ))

    logger.info("market_prices_fetched",
                district=district_id, count=len(prices))
    return prices


# ── INPUT PRICE SHOCKS ────────────────────────────────────────────────────────

async def fetch_input_shocks(
    district_id: str,
    country_iso: str,
) -> list[InputPrice]:
    """
    Monitor agricultural input price shocks.
    Source: World Bank Real-Time Price feed (free, no key needed).
    Flags any fertilizer index move greater than 10% as a shock signal.
    """
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
        logger.warning("shock_fetch_failed",
                       district=district_id, error=str(e))
        return []

    results = []
    fert = data.get("fertilizer_index")

    if fert:
        current  = fert.get("current")
        previous = fert.get("previous")

        if current and previous and previous > 0:
            pct      = ((current - previous) / previous) * 100
            is_shock = abs(pct) > 10

            if pct > 10:
                trend = TrendDirection.SPIKE
            elif pct < -10:
                trend = TrendDirection.CRASH
            else:
                trend = TrendDirection.STABLE

            results.append(InputPrice(
                district_id=district_id,
                fetched_at=datetime.utcnow(),
                input_type="fertilizer (global index)",
                price_local=current,
                currency="USD",
                unit="index",
                trend=trend,
                trend_pct=round(pct, 1),
                shock_detected=is_shock,
                shock_reason=(
                    f"World Bank fertilizer index moved {pct:+.1f}% "
                    f"compared to last month"
                    if is_shock else None
                ),
                source="world-bank-rtp",
            ))

    logger.info("shocks_fetched",
                district=district_id, count=len(results))
    return results


# ── HELPERS ───────────────────────────────────────────────────────────────────

def _calc_trend(
    current: float,
    previous: float | None
) -> tuple[TrendDirection, float]:
    """Calculate price trend direction and percentage change."""
    if not previous or previous == 0:
        return TrendDirection.STABLE, 0.0

    pct = ((current - previous) / previous) * 100

    if pct > 15:    return TrendDirection.SPIKE,   round(pct, 1)
    elif pct > 3:   return TrendDirection.RISING,  round(pct, 1)
    elif pct < -15: return TrendDirection.CRASH,   round(pct, 1)
    elif pct < -3:  return TrendDirection.FALLING, round(pct, 1)
    else:           return TrendDirection.STABLE,  round(pct, 1)
