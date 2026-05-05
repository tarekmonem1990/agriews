# AgriEWS — Agricultural Early Warning System

Free, open-source early warning platform for smallholder farmers.
Delivers weather forecasts + agronomic advice, crop market prices,
and agricultural input price shock alerts — via WhatsApp and SMS.

**Free to farmers. Always.**

## What it does

Every morning, for every registered district, AgriEWS:
1. Pulls weather forecasts from Open-Meteo (free)
2. Pulls crop prices from WFP VAM (free)
3. Monitors fertilizer/input price shocks from World Bank RTP (free)
4. Generates a plain-language advisory per crop per language via AI
5. Delivers it to farmers via WhatsApp or SMS

## Three-pillar advisory

Every farmer receives:
- WEATHER + ACTION: forecast and what to do on the farm today
- MARKET: crop price signal and whether to sell or hold
- INPUTS: fertilizer/pesticide price alert and whether to buy or wait

## Setup

See docs/SETUP.md for full deployment instructions.
API keys needed: Anthropic, WhatsApp Business, Africa's Talking (SMS).

## Principles
- Free data only — Open-Meteo, WFP VAM, World Bank RTP, Copernicus
- Geography-agnostic — adding a country = updating config, not code
- SMS works with zero internet on farmer side
- LLM generates language only — agronomic advice comes from validated rules
- No farmer data monetisation, ever

## Licence
MIT — free to use, fork, and deploy.
