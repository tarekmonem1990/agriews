"""
scheduler/pipeline.py
Main pipeline orchestrator.

This is the file that runs every morning and:
1. Fetches weather, market prices, and shock signals
2. Scores hazards for each district
3. Generates advisories via AI
4. Delivers them to farmers via WhatsApp or SMS

To run manually:
  python scheduler/pipeline.py
"""
import asyncio
from datetime import datetime
from config.models import District, Farmer, Channel, HazardLevel
from config.settings import get_settings
from ingestion.pipeline import fetch_weather, fetch_market_prices, fetch_input_shocks
from intelligence.hazard.scorer import score_hazards
from intelligence.synthesis.advisory_generator import generate_advisory
import structlog

logger = structlog.get_logger()
settings = get_settings()


# ── DISTRICT REGISTRY ─────────────────────────────────────────────────────────
# Add your districts here.
# Each district needs: id, country ISO code, name,
# coordinates (lat/lon), crops grown, languages, and channels.
#
# To add a new country: copy one district block and update the values.
# Nothing else in the code needs to change.

DISTRICTS = [
    District(
        id="sn_kaffrine_nord",
        country_iso="SN",
        name="Kaffrine Nord",
        lat=14.105,
        lon=-15.551,
        crops=["groundnut", "millet", "sorghum"],
        languages=["wolof", "french"],
        channels=[Channel.WHATSAPP, Channel.SMS],
        timezone="Africa/Dakar",
    ),
    # Add more districts here, for example:
    # District(
    #     id="et_tigray_central",
    #     country_iso="ET",
    #     name="Tigray Central",
    #     lat=14.032,
    #     lon=38.476,
    #     crops=["teff", "sorghum", "maize"],
    #     languages=["tigrinya", "amharic"],
    #     channels=[Channel.SMS],
    #     timezone="Africa/Addis_Ababa",
    # ),
]


# ── FARMER REGISTRY ───────────────────────────────────────────────────────────
# In production this comes from the database.
# For now, add test farmers here to verify delivery.

TEST_FARMERS = [
    Farmer(
        id="test_001",
        district_id="sn_kaffrine_nord",
        phone="+221700000000",      # replace with a real number for testing
        preferred_channel=Channel.WHATSAPP,
        preferred_language="french",
        crops=["groundnut", "millet"],
        registered_at=datetime.utcnow(),
    ),
]


# ── HAZARD SCORING ────────────────────────────────────────────────────────────

def score_district_hazards(forecast):
    """
    Score drought, flood, and pest pressure for a district.
    Returns HazardScores with levels from none to extreme.
    """
    from config.models import HazardScores

    drought = _score_drought(forecast)
    flood   = _score_flood(forecast)
    pest    = _score_pest(forecast)

    dl = _to_level(drought)
    fl = _to_level(flood)
    pl = _to_level(pest)
    composite = max([dl, fl, pl], key=_rank)

    return HazardScores(
        district_id=forecast.district_id,
        scored_at=datetime.utcnow(),
        drought_score=drought,
        flood_score=flood,
        pest_score=pest,
        drought_level=dl,
        flood_level=fl,
        pest_level=pl,
        composite_level=composite,
    )


def _score_drought(f) -> float:
    if f.drought_spi is not None:
        spi = f.drought_spi
        if spi <= -2.0: return 90.0
        if spi <= -1.5: return 70.0
        if spi <= -1.0: return 50.0
        if spi <= -0.5: return 30.0
        return 10.0
    rain = f.rain_7d_mm
    if rain < 5:  return 85.0
    if rain < 15: return 60.0
    if rain < 30: return 35.0
    if rain < 50: return 15.0
    return 5.0

def _score_flood(f) -> float:
    r = f.rain_24h_mm
    if r > 80: return 95.0
    if r > 50: return 75.0
    if r > 30: return 50.0
    if r > 15: return 25.0
    return f.flood_risk_score

def _score_pest(f) -> float:
    if f.temp_max_c > 30 and f.humidity_pct > 70: return 70.0
    if f.temp_max_c > 28 and f.humidity_pct > 60: return 45.0
    if f.temp_max_c > 25: return 25.0
    return 10.0

def _to_level(score: float) -> HazardLevel:
    if score >= 80: return HazardLevel.EXTREME
    if score >= 60: return HazardLevel.HIGH
    if score >= 35: return HazardLevel.MEDIUM
    if score >= 15: return HazardLevel.LOW
    return HazardLevel.NONE

def _rank(level: HazardLevel) -> int:
    return {"none":0,"low":1,"medium":2,"high":3,"extreme":4}[level.value]


# ── DELIVERY ──────────────────────────────────────────────────────────────────

async def deliver_whatsapp(advisory, farmer):
    """Send advisory via WhatsApp."""
    import httpx
    from config.models import DeliveryReceipt

    LABELS = {
        HazardLevel.NONE:    "All clear",
        HazardLevel.LOW:     "Low risk",
        HazardLevel.MEDIUM:  "Watch",
        HazardLevel.HIGH:    "Alert",
        HazardLevel.EXTREME: "Danger",
    }

    label    = LABELS[advisory.hazard_level]
    date_str = advisory.valid_for_date.strftime("%d %b %Y")
    crop_str = f" — {advisory.crop.title()}" if advisory.crop else ""
    alerts   = ("*INPUT ALERT* | " if advisory.has_shock_alert else "") + \
               ("*MARKET ALERT* | " if advisory.has_market_alert else "")

    message = (
        f"*AgriEWS Advisory* | {date_str}{crop_str}\n"
        f"Status: *{label}*\n"
        f"{alerts}\n"
        f"---\n"
        f"*Weather & Action*\n{advisory.weather_section}\n\n"
        f"*Market*\n{advisory.market_section}\n\n"
        f"*Input Prices*\n{advisory.shock_section}\n"
        f"---\n"
        f"_AgriEWS is free | Reply STOP to unsubscribe_"
    )

    url = (
        f"https://graph.facebook.com/v19.0/"
        f"{settings.whatsapp_phone_number_id}/messages"
    )
    payload = {
        "messaging_product": "whatsapp",
        "to": farmer.phone,
        "type": "text",
        "text": {"body": message, "preview_url": False},
    }
    headers = {
        "Authorization": f"Bearer {settings.whatsapp_api_token}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(url, json=payload, headers=headers)
            r.raise_for_status()
            msg_id = r.json().get("messages", [{}])[0].get("id")
        logger.info("whatsapp_sent",
                    farmer=farmer.id, msg_id=msg_id)
        return DeliveryReceipt(
            advisory_id=f"{advisory.district_id}_{advisory.valid_for_date}",
            farmer_id=farmer.id,
            channel=Channel.WHATSAPP,
            sent_at=datetime.utcnow(),
            status="sent",
            gateway_message_id=msg_id,
        )
    except Exception as e:
        logger.error("whatsapp_failed", farmer=farmer.id, error=str(e))
        return DeliveryReceipt(
            advisory_id=f"{advisory.district_id}_{advisory.valid_for_date}",
            farmer_id=farmer.id,
            channel=Channel.WHATSAPP,
            sent_at=datetime.utcnow(),
            status="failed",
            error=str(e),
        )


async def deliver_sms(advisory, farmer):
    """Send advisory via Africa's Talking SMS."""
    import africastalking
    from config.models import DeliveryReceipt

    africastalking.initialize(
        username=settings.at_username,
        api_key=settings.at_api_key,
    )
    sms = africastalking.SMS

    TAGS = {
        HazardLevel.NONE:    "OK",
        HazardLevel.LOW:     "LOW",
        HazardLevel.MEDIUM:  "WATCH",
        HazardLevel.HIGH:    "ALERT",
        HazardLevel.EXTREME: "DANGER",
    }

    def trunc(text, n):
        return text if len(text) <= n else text[:n].rsplit(" ", 1)[0]

    district_short = advisory.district_id.split("_")[-1].upper()[:6]
    date_str       = advisory.valid_for_date.strftime("%d/%m")
    tag            = TAGS[advisory.hazard_level]
    weather        = trunc(advisory.weather_section, 55)
    market         = trunc(advisory.market_section, 40)
    shock          = trunc(advisory.shock_section, 35) if advisory.has_shock_alert else "Inputs OK"

    message = (
        f"AGRI {district_short} {date_str} [{tag}]\n"
        f"{weather}\n{market}\n{shock}\nReply 1=more"
    )[:160]

    try:
        resp   = sms.send(
            message=message,
            recipients=[farmer.phone],
            sender_id=settings.at_sender_id,
        )
        result = resp.get("SMSMessageData", {}).get("Recipients", [{}])[0]
        status = result.get("status", "unknown")
        return DeliveryReceipt(
            advisory_id=f"{advisory.district_id}_{advisory.valid_for_date}",
            farmer_id=farmer.id,
            channel=Channel.SMS,
            sent_at=datetime.utcnow(),
            status="sent" if status == "Success" else "failed",
            gateway_message_id=result.get("messageId"),
            error=None if status == "Success" else status,
        )
    except Exception as e:
        logger.error("sms_failed", farmer=farmer.id, error=str(e))
        return DeliveryReceipt(
            advisory_id=f"{advisory.district_id}_{advisory.valid_for_date}",
            farmer_id=farmer.id,
            channel=Channel.SMS,
            sent_at=datetime.utcnow(),
            status="failed",
            error=str(e),
        )


# ── MAIN PIPELINE ─────────────────────────────────────────────────────────────

async def run_pipeline(dry_run: bool = False):
    """
    Run the full pipeline for all registered districts.
    dry_run=True skips AI generation and delivery — useful for testing data feeds.
    """
    logger.info("pipeline_starting",
                districts=len(DISTRICTS),
                dry_run=dry_run)

    for district in DISTRICTS:
        log = logger.bind(district=district.id)
        log.info("district_starting")

        try:
            # Step 1 — fetch all data
            forecast     = await fetch_weather(district.id, district.lat, district.lon)
            crop_prices  = await fetch_market_prices(district.id, district.country_iso, district.crops)
            input_prices = await fetch_input_shocks(district.id, district.country_iso)

            log.info("data_fetched",
                     rain_7d=round(forecast.rain_7d_mm, 1),
                     prices=len(crop_prices),
                     shocks=len(input_prices))

            if dry_run:
                log.info("dry_run_stopping_before_advisory")
                continue

            # Step 2 — score hazards
            scores = score_district_hazards(forecast)
            log.info("hazards_scored",
                     drought=scores.drought_level,
                     flood=scores.flood_level,
                     pest=scores.pest_level,
                     composite=scores.composite_level)

            # Step 3 — generate advisories and deliver
            farmers = [f for f in TEST_FARMERS if f.district_id == district.id]

            for farmer in farmers:
                for crop in farmer.crops:
                    advisory = await generate_advisory(
                        district=district,
                        forecast=forecast,
                        scores=scores,
                        crop_prices=crop_prices,
                        input_prices=input_prices,
                        language=farmer.preferred_language,
                        crop=crop,
                    )

                    # Step 4 — deliver
                    if farmer.preferred_channel == Channel.WHATSAPP:
                        receipt = await deliver_whatsapp(advisory, farmer)
                    else:
                        receipt = await deliver_sms(advisory, farmer)

                    log.info("advisory_delivered",
                             farmer=farmer.id,
                             crop=crop,
                             channel=farmer.preferred_channel,
                             status=receipt.status)

        except Exception as e:
            log.error("district_failed", error=str(e))
            continue

    logger.info("pipeline_complete")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Fetch data only, skip AI and delivery")
    args = parser.parse_args()
    asyncio.run(run_pipeline(dry_run=args.dry_run))
