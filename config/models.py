"""
config/models.py
Shared data models used across all layers.
Think of these as the standard "envelopes" that data
travels in between every part of the system.
"""
from __future__ import annotations
from datetime import datetime, date
from enum import Enum
from typing import Optional
from pydantic import BaseModel

class HazardLevel(str, Enum):
    NONE    = "none"
    LOW     = "low"
    MEDIUM  = "medium"
    HIGH    = "high"
    EXTREME = "extreme"

class Channel(str, Enum):
    SMS       = "sms"
    WHATSAPP  = "whatsapp"
    APP       = "app"
    EXTENSION = "extension"

class TrendDirection(str, Enum):
    STABLE  = "stable"
    RISING  = "rising"
    FALLING = "falling"
    SPIKE   = "spike"
    CRASH   = "crash"

class District(BaseModel):
    id: str
    country_iso: str
    name: str
    lat: float
    lon: float
    crops: list[str]
    languages: list[str]
    channels: list[Channel]
    timezone: str = "UTC"

class Farmer(BaseModel):
    id: str
    district_id: str
    phone: str
    preferred_channel: Channel
    preferred_language: str
    crops: list[str]
    registered_at: datetime

class WeatherForecast(BaseModel):
    district_id: str
    fetched_at: datetime
    forecast_date: date
    rain_7d_mm: float
    rain_24h_mm: float
    temp_max_c: float
    temp_min_c: float
    humidity_pct: float
    drought_spi: Optional[float] = None
    flood_risk_score: float = 0.0
    source: str = "open-meteo"

class CropPrice(BaseModel):
    district_id: str
    fetched_at: datetime
    crop: str
    price_local: float
    currency: str
    unit: str
    market_name: str
    trend: TrendDirection
    trend_pct: float
    source: str = "wfp-vam"

class InputPrice(BaseModel):
    district_id: str
    fetched_at: datetime
    input_type: str
    price_local: float
    currency: str
    unit: str
    trend: TrendDirection
    trend_pct: float
    shock_detected: bool = False
    shock_reason: Optional[str] = None
    source: str

class HazardScores(BaseModel):
    district_id: str
    scored_at: datetime
    drought_score: float
    flood_score: float
    pest_score: float
    drought_level: HazardLevel
    flood_level: HazardLevel
    pest_level: HazardLevel
    composite_level: HazardLevel

class Advisory(BaseModel):
    district_id: str
    generated_at: datetime
    valid_for_date: date
    language: str
    crop: Optional[str] = None
    weather_section: str
    market_section: str
    shock_section: str
    hazard_level: HazardLevel
    has_market_alert: bool = False
    has_shock_alert: bool = False
    weather_source: str
    market_source: str
    shock_source: str

class DeliveryReceipt(BaseModel):
    advisory_id: str
    farmer_id: str
    channel: Channel
    sent_at: datetime
    status: str
    gateway_message_id: Optional[str] = None
    error: Optional[str] = None
