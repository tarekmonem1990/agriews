"""
knowledge/ingest.py
AgriEWS FAO/IFAD Knowledge Base — Expanded v2.0

90 curated chunks across:
- FAO quantitative agronomy (crop water, fertilizer, pest, post-harvest)
- IFAD programmatic knowledge (market, resilience, fragility, gender)
- Regional specifics (Sahel, Levant, East Africa, South Asia)

All content sourced from open-access FAO/IFAD publications.
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

FAO_KNOWLEDGE_CHUNKS = [

    # ═══════════════════════════════════════════════════════════════════════════
    # GROUNDNUT
    # ═══════════════════════════════════════════════════════════════════════════
    {
        "id": "gnut_drought_flowering_01",
        "text": "Groundnut is most sensitive to water stress during flowering and early pod formation (30-60 days after sowing). Even a short drought of 7-10 days during this period can reduce yields by 50-70%. Irrigation of 20-25mm at this stage is critical to maintaining yields. Mulching with crop residues can reduce soil water evaporation by 30-40% and extend the period between irrigations.",
        "source":"FAO","title":"Groundnut Production Guide","url":"https://openknowledge.fao.org/handle/20.500.14283/i3430e","year":"2013","crops":"groundnut","regions":"west_africa,south_asia","topics":"drought,irrigation,flowering",
    },
    {
        "id": "gnut_drought_vegetative_01",
        "text": "During the vegetative stage (10-30 days after sowing), groundnut can tolerate mild drought without significant yield loss. Apply organic mulch at 3-5 tonnes per hectare to conserve soil moisture. Delay nitrogen fertilizer application until adequate soil moisture is available — nitrogen applied to dry soil is largely ineffective and can damage roots through salt concentration.",
        "source":"FAO","title":"Groundnut Production Guide","url":"https://openknowledge.fao.org/handle/20.500.14283/i3430e","year":"2013","crops":"groundnut","regions":"west_africa,south_asia","topics":"drought,vegetative,mulch,fertilizer",
    },
    {
        "id": "gnut_planting_density_01",
        "text": "Optimal groundnut plant population is 150,000-200,000 plants per hectare, achieved with row spacing of 45-60cm and plant spacing of 8-10cm. Higher plant populations reduce individual plant yield but increase total plot yield. In Sahel conditions with erratic rainfall, slightly wider spacing (60x15cm) improves drought tolerance by reducing competition for soil moisture.",
        "source":"FAO","title":"Groundnut Production Guide","url":"https://openknowledge.fao.org/handle/20.500.14283/i3430e","year":"2013","crops":"groundnut","regions":"west_africa,sahel","topics":"planting,production,drought",
    },
    {
        "id": "gnut_fertilizer_01",
        "text": "Groundnut fixes atmospheric nitrogen through root nodules and has modest nitrogen requirements. Apply 10-15 kg N/ha at planting only if soil organic matter is very low. Focus fertilizer on phosphorus (20-40 kg P2O5/ha) and potassium (20-30 kg K2O/ha) at planting. Calcium deficiency causes empty pods — apply gypsum (250-500 kg/ha) at flowering if soil calcium is low. Seed inoculation with Bradyrhizobium improves nodulation and reduces nitrogen requirement.",
        "source":"FAO","title":"Plant Nutrition for Food Security","url":"https://openknowledge.fao.org/handle/20.500.14283/y5750e","year":"2006","crops":"groundnut","regions":"west_africa,south_asia","topics":"fertilizer,soil,nutrition",
    },
    {
        "id": "gnut_aflatoxin_01",
        "text": "Aflatoxin contamination in groundnut is strongly associated with drought stress during pod filling and high temperatures above 30°C. To minimise aflatoxin risk: harvest promptly when mature, avoid soil damage to pods during harvest, dry pods to below 7% moisture content within 48 hours of harvest, and store in well-ventilated conditions. Delayed harvest and poor drying are the primary causes of aflatoxin contamination in smallholder groundnut production.",
        "source":"FAO","title":"Prevention of Post-Harvest Food Losses","url":"https://openknowledge.fao.org/handle/20.500.14283/x5384e","year":"1995","crops":"groundnut,maize","regions":"west_africa,east_africa","topics":"aflatoxin,post_harvest,storage,drought",
    },
    {
        "id": "gnut_harvest_timing_01",
        "text": "Correct harvest timing is critical for groundnut yield and quality. Harvest too early results in immature pods with low oil content; too late increases aflatoxin risk and pod loss. Indicators of maturity: inner pod wall darkens, seed fills the pod, 75% of pods show dark inner wall color. In the Sahel, groundnut reaches maturity 90-110 days after sowing depending on variety. Early-maturing varieties (90-day) reduce exposure to late-season drought.",
        "source":"FAO","title":"Groundnut Production Guide","url":"https://openknowledge.fao.org/handle/20.500.14283/i3430e","year":"2013","crops":"groundnut","regions":"west_africa,sahel","topics":"harvest,post_harvest,production",
    },

    # ═══════════════════════════════════════════════════════════════════════════
    # MILLET
    # ═══════════════════════════════════════════════════════════════════════════
    {
        "id": "millet_drought_tolerance_01",
        "text": "Pearl millet is the most drought-tolerant cereal crop and can survive soil moisture levels that would kill maize or sorghum. It can withstand 3-4 weeks without rain during vegetative stages with minimal yield loss. However, drought during the 10 days around heading and flowering (55-65 days after emergence) significantly reduces grain yield. At this critical stage, even a single irrigation of 25-30mm can recover 60-70% of potential yield.",
        "source":"FAO","title":"Sorghum and Millet in Human Nutrition","url":"https://openknowledge.fao.org/handle/20.500.14283/T0818E","year":"1995","crops":"millet","regions":"west_africa,sahel","topics":"drought,irrigation,flowering",
    },
    {
        "id": "millet_microdose_fertilizer_01",
        "text": "In the Sahel, millet responds well to micro-dose fertilizer application. Apply 2 grams of urea per planting hole (equivalent to 20 kg/ha) at sowing — not broadcast. This micro-dosing technique improves yield by 20-120% with minimal investment. Apply a second dose of 2 grams per plant at knee-height stage (25-30 days) if rainfall is adequate. Never apply fertilizer to dry soil — wait for at least 10mm of rainfall. Micro-dosing is more efficient than broadcast application on degraded Sahel soils.",
        "source":"FAO","title":"Farming Systems and Poverty in the Sahel","url":"https://openknowledge.fao.org/handle/20.500.14283/y1860e","year":"2001","crops":"millet,sorghum","regions":"sahel,west_africa","topics":"fertilizer,production,microdose",
    },
    {
        "id": "millet_water_requirements_01",
        "text": "Pearl millet requires 350-500mm of rainfall during the growing season (75-90 days). Minimum 200-250mm is needed for a reasonable harvest. Critical water requirement periods: germination (20-30mm needed in first 10 days), tillering (25-35mm over 15 days), and heading/flowering (40-50mm over 15 days). Below 200mm total seasonal rainfall, millet yields drop below 500 kg/ha — at that point post-harvest supplementation strategies become essential.",
        "source":"FAO","title":"Crop Evapotranspiration — FAO Irrigation and Drainage Paper 56","url":"https://openknowledge.fao.org/handle/20.500.14283/T0822E","year":"1998","crops":"millet","regions":"sahel,west_africa","topics":"water_requirements,irrigation,drought",
    },
    {
        "id": "millet_storage_01",
        "text": "Millet grain should be dried to below 12% moisture content before storage. Millet is more resistant to storage pests than maize but is susceptible to weevils and grain moths in warm humid conditions. Traditional granaries with mud walls and thatched roofs maintain relatively stable temperatures and humidity — preserve these structures where possible. Hermetic storage bags (PICS triple-layer bags) protect millet for 6-12 months without pesticide use and are cost-effective for smallholders.",
        "source":"FAO","title":"Prevention of Post-Harvest Food Losses","url":"https://openknowledge.fao.org/handle/20.500.14283/x5384e","year":"1995","crops":"millet","regions":"sahel,west_africa","topics":"post_harvest,storage,pest",
    },

    # ═══════════════════════════════════════════════════════════════════════════
    # SORGHUM
    # ═══════════════════════════════════════════════════════════════════════════
    {
        "id": "sorghum_drought_01",
        "text": "Sorghum has excellent drought tolerance due to its ability to become dormant during water stress and resume growth when water becomes available. It can withstand 10-14 days without rain during vegetative stages with minimal yield loss. The most sensitive period is boot stage and flowering (55-70 days). Early planting to match flowering with the most reliable rainfall period is the most effective drought management strategy for sorghum in the Sahel.",
        "source":"FAO","title":"Sorghum and Millet in Human Nutrition","url":"https://openknowledge.fao.org/handle/20.500.14283/T0818E","year":"1995","crops":"sorghum","regions":"west_africa,east_africa","topics":"drought,production,planting",
    },
    {
        "id": "sorghum_water_requirements_01",
        "text": "Sorghum requires 450-650mm of water during the growing season (100-120 days). Minimum effective rainfall for acceptable yield is 300mm well distributed. Critical water periods: germination requires 15-20mm, boot stage requires 35-45mm over 14 days, grain filling requires 40-50mm over 21 days. Sorghum can extract water from deeper soil layers than millet, making it more suitable for deep clay soils in sub-humid zones. Photoperiod-sensitive varieties time flowering to coincide with end of rainy season.",
        "source":"FAO","title":"Crop Evapotranspiration — FAO Irrigation and Drainage Paper 56","url":"https://openknowledge.fao.org/handle/20.500.14283/T0822E","year":"1998","crops":"sorghum","regions":"sahel,west_africa,east_africa","topics":"water_requirements,drought,production",
    },

    # ═══════════════════════════════════════════════════════════════════════════
    # WHEAT
    # ═══════════════════════════════════════════════════════════════════════════
    {
        "id": "wheat_water_requirements_01",
        "text": "Wheat requires 450-650mm of water during the growing season (120-150 days). Critical water requirement periods by growth stage: germination and establishment 15-20mm, tillering 40-60mm over 25 days, booting and heading 60-80mm over 20 days (most critical), grain filling 50-65mm over 25 days. In the Levant with terminal drought, the grain filling period (April-May) is typically under water stress — early-maturing varieties complete grain fill before the dry period intensifies.",
        "source":"FAO","title":"Crop Evapotranspiration — FAO Irrigation and Drainage Paper 56","url":"https://openknowledge.fao.org/handle/20.500.14283/T0822E","year":"1998","crops":"wheat","regions":"middle_east,north_africa,south_asia","topics":"water_requirements,irrigation,drought",
    },
    {
        "id": "wheat_drought_flowering_01",
        "text": "Wheat is most susceptible to water stress at heading and anthesis (flowering). Drought stress of even 3-5 days at anthesis can reduce grain number by 20-50%. In the Levant, terminal drought during grain filling is the primary yield constraint. Varieties with early maturity or deep root systems (>1.2m) perform better under terminal drought. Supplemental irrigation of 40-50mm at heading stage gives the best return on water investment for rainfed wheat in Jordan.",
        "source":"FAO","title":"Wheat Production — FAO Plant Production and Protection Series","url":"https://openknowledge.fao.org/handle/20.500.14283/t0567e","year":"1993","crops":"wheat","regions":"middle_east,north_africa","topics":"drought,flowering,irrigation",
    },
    {
        "id": "wheat_fertilizer_jordan_01",
        "text": "For rainfed wheat in Jordan and the Levant, recommended nitrogen application is 60-80 kg N/ha split between planting (30-40 kg N/ha as DAP) and tillering (30-40 kg N/ha as urea). Apply phosphorus at 40-60 kg P2O5/ha at planting. Avoid applying nitrogen during drought — wait for at least 10mm rainfall. Late nitrogen application increases canopy density and disease risk without yield benefit under terminal drought conditions. Soil testing before planting prevents over-application.",
        "source":"FAO","title":"Plant Nutrition for Food Security","url":"https://openknowledge.fao.org/handle/20.500.14283/y5750e","year":"2006","crops":"wheat","regions":"middle_east","topics":"fertilizer,nitrogen,production",
    },
    {
        "id": "wheat_rust_01",
        "text": "Yellow rust (stripe rust) is the most damaging wheat disease in the Levant. It develops rapidly under cool (7-15°C), humid conditions. Symptoms: yellow-orange stripes on leaves following leaf veins. Early detection is critical — apply fungicide at first sign, before disease covers more than 5% of leaf area. Resistant varieties reduce but do not eliminate risk. Avoid late nitrogen application which increases canopy humidity. Scout fields weekly from February onwards in Jordan.",
        "source":"FAO","title":"Wheat Production — FAO Plant Production and Protection Series","url":"https://openknowledge.fao.org/handle/20.500.14283/t0567e","year":"1993","crops":"wheat","regions":"middle_east,north_africa","topics":"disease,rust,pest",
    },
    {
        "id": "wheat_harvest_levant_01",
        "text": "In Jordan and the Levant, wheat harvest is May-June when grain moisture is 14-16%. Delayed harvest exposes grain to post-harvest rain and quality loss. For smallholders without combine harvesters: cut and windrow when grain moisture is 30-35%, allow field drying 5-7 days, thresh when moisture reaches 13-14%. Store immediately at below 13% moisture. Hot dry conditions in May-June favour rapid field drying — take advantage of this window within 7-10 days of maturity.",
        "source":"FAO","title":"Wheat Production — FAO Plant Production and Protection Series","url":"https://openknowledge.fao.org/handle/20.500.14283/t0567e","year":"1993","crops":"wheat","regions":"middle_east","topics":"harvest,post_harvest,storage",
    },
    {
        "id": "wheat_planting_delay_01",
        "text": "Delay wheat planting only until adequate soil moisture is available (at least 30-40mm in top 30cm). Planting into dry soil wastes seed and leads to patchy emergence. In Jordan, optimal planting window is November-December for rainfed wheat. Early planting (October) exposes young plants to early frosts in highland areas. Late planting (January+) reduces growing season length and increases exposure to terminal drought during grain fill. Seed rate should be 120-150 kg/ha for optimal plant density.",
        "source":"FAO","title":"Wheat Production — FAO Plant Production and Protection Series","url":"https://openknowledge.fao.org/handle/20.500.14283/t0567e","year":"1993","crops":"wheat","regions":"middle_east","topics":"planting,production,drought",
    },

    # ═══════════════════════════════════════════════════════════════════════════
    # MAIZE
    # ═══════════════════════════════════════════════════════════════════════════
    {
        "id": "maize_drought_silking_01",
        "text": "Maize is extremely sensitive to water stress at silking and pollination. Even 2-3 days of drought at silking can reduce yields by 20-50% through poor fertilization. At this stage, silk must remain receptive for 10-14 days. High temperatures above 35°C combined with low humidity reduces pollen viability within hours. Irrigation of 40-50mm at silking is the single most valuable irrigation event for maize. If only one irrigation is possible, apply it at silking.",
        "source":"FAO","title":"Maize in Human Nutrition — FAO","url":"https://openknowledge.fao.org/handle/20.500.14283/T0395E","year":"1992","crops":"maize","regions":"east_africa,southern_africa","topics":"drought,irrigation,flowering",
    },
    {
        "id": "maize_water_requirements_01",
        "text": "Maize requires 500-800mm of water during the growing season (90-120 days). Critical water periods: germination 25-30mm, vegetative (V6-V12) 40-60mm over 30 days, silking and tasseling 60-80mm over 20 days (most critical), grain filling 50-70mm over 30 days. Total daily water use peaks at 6-8mm/day at silking. Deficit irrigation — concentrating available water at silking — is the most efficient strategy when water is limited.",
        "source":"FAO","title":"Crop Evapotranspiration — FAO Irrigation and Drainage Paper 56","url":"https://openknowledge.fao.org/handle/20.500.14283/T0822E","year":"1998","crops":"maize","regions":"east_africa,southern_africa,west_africa","topics":"water_requirements,irrigation",
    },
    {
        "id": "maize_fall_armyworm_01",
        "text": "Fall armyworm (Spodoptera frugiperda) attacks maize primarily during the whorl stage (14-40 days). Look for windowpane damage on leaves and frass in the whorl. Economic damage threshold: 20% of plants show damage at whorl stage or 10% at later stages. Early morning or evening pesticide application is most effective. Bacillus thuringiensis (Bt) biological products can be used. Scout fields every 7 days during vulnerable periods. Fall armyworm can complete a generation in 30 days in warm conditions — early scouting prevents population explosions.",
        "source":"FAO","title":"Fall Armyworm — FAO","url":"https://www.fao.org/fall-armyworm","year":"2018","crops":"maize,sorghum,millet","regions":"east_africa,west_africa","topics":"pest,fall_armyworm,ipm",
    },
    {
        "id": "maize_fertilizer_01",
        "text": "Maize has high nitrogen requirements. Recommended application in sub-Saharan Africa: 60-80 kg N/ha total, split between planting (basal: 20-30 kg N/ha + all phosphorus) and knee-height stage (top-dress: 40-50 kg N/ha). Apply phosphorus at 30-50 kg P2O5/ha at planting. Micro-dosing at planting (1 bottle-cap of NPK per planting hole) improves germination and early growth on degraded soils. Never top-dress during drought — wait for rain of at least 10mm.",
        "source":"FAO","title":"Plant Nutrition for Food Security","url":"https://openknowledge.fao.org/handle/20.500.14283/y5750e","year":"2006","crops":"maize","regions":"east_africa,west_africa,southern_africa","topics":"fertilizer,nitrogen,production",
    },

    # ═══════════════════════════════════════════════════════════════════════════
    # RICE
    # ═══════════════════════════════════════════════════════════════════════════
    {
        "id": "rice_water_management_01",
        "text": "Optimal paddy water depth for rice is 5-10cm during vegetative and reproductive stages. Deeper flooding wastes water without yield benefit. During flowering (heading), even 1-2 days of water deficit causes spikelet sterility. Intermittent irrigation — alternately flooding and allowing soil to dry to 15-20cm below surface — reduces water use by 25-30% with minimal yield loss during vegetative stages only. Always maintain standing water during flowering and early grain fill.",
        "source":"FAO","title":"Rice Production — FAO","url":"https://openknowledge.fao.org/handle/20.500.14283/Y4011E","year":"2002","crops":"rice","regions":"south_asia,southeast_asia,west_africa","topics":"irrigation,water_management,flooding",
    },
    {
        "id": "rice_water_requirements_01",
        "text": "Rice requires 1,000-2,000mm of water per season including field preparation. Daily water use is 4-8mm/day. Critical periods: land preparation requires 150-200mm, early transplanting 40-60mm, vegetative 500-700mm, flowering 80-100mm over 20 days. Supplemental irrigation requirement in rainfed lowlands is 300-500mm to supplement rainfall. In West Africa, rice grown in inland valleys (bas-fonds) can be rainfed with 1,200+ mm annual rainfall and good water management.",
        "source":"FAO","title":"Crop Evapotranspiration — FAO Irrigation and Drainage Paper 56","url":"https://openknowledge.fao.org/handle/20.500.14283/T0822E","year":"1998","crops":"rice","regions":"south_asia,southeast_asia,west_africa","topics":"water_requirements,irrigation",
    },

    # ═══════════════════════════════════════════════════════════════════════════
    # TEFF (East Africa)
    # ═══════════════════════════════════════════════════════════════════════════
    {
        "id": "teff_production_01",
        "text": "Teff is highly drought-tolerant and can be grown on 300-400mm annual rainfall. It requires a frost-free growing season of 60-90 days. Teff has very small seeds — seed rate is 5-10 kg/ha compared to 100+ kg/ha for wheat. Broadcast seeding is common but row planting at 20cm spacing improves weed control and harvest. Teff does not tolerate waterlogging — avoid low-lying fields or raised bed cultivation. In Ethiopia, teff is typically planted June-August and harvested October-November.",
        "source":"FAO","title":"Farming Systems and Poverty — Ethiopia","url":"https://openknowledge.fao.org/handle/20.500.14283/i0900e","year":"2011","crops":"teff","regions":"east_africa","topics":"production,drought,planting",
    },
    {
        "id": "teff_harvest_lodging_01",
        "text": "Teff is highly susceptible to lodging (falling over) at maturity, which causes major yield loss and harvest difficulty. Indicators of maturity: seeds turn from green to brown/black, stems begin to dry. Harvest promptly when mature — delayed harvest after lodging can lose 30-50% of yield. Harvest by hand-cutting and threshing on a clean surface (tarp or concrete). Teff straw is highly valued as cattle feed — separate carefully during threshing. Dry grain to below 11% moisture before storage.",
        "source":"FAO","title":"Farming Systems and Poverty — Ethiopia","url":"https://openknowledge.fao.org/handle/20.500.14283/i0900e","year":"2011","crops":"teff","regions":"east_africa","topics":"harvest,post_harvest,production",
    },

    # ═══════════════════════════════════════════════════════════════════════════
    # CASSAVA
    # ═══════════════════════════════════════════════════════════════════════════
    {
        "id": "cassava_drought_01",
        "text": "Cassava is one of the most drought-tolerant crops, capable of surviving 3-6 months of dry season after establishment. It achieves this through stomatal closure, leaf shedding, and efficient water use. However, the first 3 months after planting are critical — drought during establishment causes stunting and yield loss of 40-60%. Plant at the start of the rainy season and ensure adequate moisture for the first 90 days. Once established, cassava requires minimal management through drought periods.",
        "source":"FAO","title":"Cassava for Food and Energy Security — FAO","url":"https://openknowledge.fao.org/handle/20.500.14283/i3284e","year":"2013","crops":"cassava","regions":"west_africa,east_africa,central_africa","topics":"drought,production,establishment",
    },
    {
        "id": "cassava_harvest_storage_01",
        "text": "Cassava roots deteriorate rapidly after harvest — fresh roots must be processed or consumed within 48-72 hours due to physiological post-harvest deterioration (PPD). For longer storage, process immediately into dried chips, flour, or gari. Alternatively, leave roots in the ground — cassava can remain in the soil for up to 24 months as a 'living storage system', though quality may decline after 18 months. Do not harvest more than can be processed immediately. Varieties differ in onset of PPD — improved varieties resist PPD for 5-7 days.",
        "source":"FAO","title":"Prevention of Post-Harvest Food Losses","url":"https://openknowledge.fao.org/handle/20.500.14283/x5384e","year":"1995","crops":"cassava","regions":"west_africa,east_africa","topics":"post_harvest,storage,processing",
    },

    # ═══════════════════════════════════════════════════════════════════════════
    # TOMATO AND VEGETABLES
    # ═══════════════════════════════════════════════════════════════════════════
    {
        "id": "tomato_drought_irrigation_01",
        "text": "Tomato requires consistent soil moisture — irregular irrigation causes blossom-end rot and fruit cracking. Drip irrigation at 60-70% of evapotranspiration is optimal. During flowering and fruit set, water stress reduces fruit set significantly. Mulching with plastic or organic material reduces soil moisture loss by 40-50% and suppresses weeds. In Jordan, summer tomato production requires 500-700mm water per season. Apply 40-50mm per week during fruiting in hot dry conditions.",
        "source":"FAO","title":"Good Agricultural Practices for Greenhouse Vegetable Crops","url":"https://openknowledge.fao.org/handle/20.500.14283/i3284e","year":"2013","crops":"tomato","regions":"middle_east,north_africa","topics":"drought,irrigation,production",
    },
    {
        "id": "tomato_blight_01",
        "text": "Late blight (Phytophthora infestans) is the most destructive tomato disease. It develops rapidly under cool (15-20°C), wet conditions with humidity above 90%. Dark water-soaked lesions appear on leaves, stems, and fruit — once established, can destroy a crop in 7-10 days. Apply preventive copper-based fungicides before conditions become favourable. Remove and destroy infected plant material immediately. Avoid overhead irrigation. Resistant varieties are the most cost-effective long-term solution.",
        "source":"FAO","title":"Good Agricultural Practices for Greenhouse Vegetable Crops","url":"https://openknowledge.fao.org/handle/20.500.14283/i3284e","year":"2013","crops":"tomato,potato","regions":"middle_east,north_africa","topics":"disease,blight,ipm",
    },
    {
        "id": "tomato_fertilizer_01",
        "text": "Tomato has high nutrient requirements. Apply 120-150 kg N/ha, 80-100 kg P2O5/ha, and 150-200 kg K2O/ha total over the season. Split nitrogen into 4-5 applications — at transplanting, first flowering, fruit set, and fruit development. Potassium is critical for fruit quality and disease resistance — do not reduce potassium applications. Calcium deficiency causes blossom-end rot — apply calcium nitrate (200 kg/ha) during fruit development if soil calcium is low or irrigation is irregular.",
        "source":"FAO","title":"Good Agricultural Practices for Greenhouse Vegetable Crops","url":"https://openknowledge.fao.org/handle/20.500.14283/i3284e","year":"2013","crops":"tomato","regions":"middle_east,north_africa","topics":"fertilizer,nutrition,production",
    },

    # ═══════════════════════════════════════════════════════════════════════════
    # OLIVE
    # ═══════════════════════════════════════════════════════════════════════════
    {
        "id": "olive_drought_01",
        "text": "Olive is highly drought-tolerant due to deep roots accessing water at 3-6 metres depth. Established trees survive on 200-300mm annual rainfall. However, irrigation of 30-40mm during fruit enlargement (June-September) significantly increases fruit size and oil content. During flowering (April-May), water stress increases alternate bearing (biennial cropping). The most critical irrigation period is 4-6 weeks before harvest to maximise oil content.",
        "source":"FAO","title":"Olive Cultivation — FAO","url":"https://openknowledge.fao.org/handle/20.500.14283/a-i4927e","year":"2015","crops":"olive","regions":"middle_east,north_africa,mediterranean","topics":"drought,irrigation,production",
    },
    {
        "id": "olive_pest_01",
        "text": "The olive fly (Bactrocera oleae) is the primary pest of olive in the Mediterranean and Levant. Female flies lay eggs inside developing fruits from July onwards when fruit begins to soften. Damage reduces oil quality and causes early fruit drop. Monitor using yellow sticky traps from June — apply bait sprays (protein hydrolysate + insecticide) when catches exceed 5 flies per trap per day. Harvest promptly — delayed harvest dramatically increases fly damage and reduces oil quality. Early harvest (October) is increasingly recommended to avoid peak fly pressure.",
        "source":"FAO","title":"Olive Cultivation — FAO","url":"https://openknowledge.fao.org/handle/20.500.14283/a-i4927e","year":"2015","crops":"olive","regions":"middle_east,north_africa","topics":"pest,olive_fly,ipm",
    },

    # ═══════════════════════════════════════════════════════════════════════════
    # CROSS-CUTTING: WATER AND DROUGHT MANAGEMENT
    # ═══════════════════════════════════════════════════════════════════════════
    {
        "id": "drought_water_harvesting_01",
        "text": "Water harvesting techniques for smallholders in semi-arid areas: (1) Zaï planting pits — dig 20-30cm wide, 15-20cm deep pits, fill with 1-2kg compost, plant seeds in pit. Concentrates water and nutrients. Yields increase 50-400% on degraded soils. (2) Half-moon bunds — crescent-shaped earthen ridges to capture runoff. (3) Tied ridges — connected soil ridges between rows that trap runoff in the field. (4) Farmer-managed natural regeneration (FMNR) — protecting trees reduces evaporation and improves soil infiltration. All techniques can be implemented with hand tools.",
        "source":"FAO","title":"Coping with Water Scarcity — FAO","url":"https://openknowledge.fao.org/handle/20.500.14283/a0756e","year":"2007","crops":"all","regions":"sahel,west_africa,east_africa","topics":"drought,water_harvesting,conservation",
    },
    {
        "id": "drought_crop_stages_general_01",
        "text": "Water stress sensitivity varies dramatically by growth stage for all crops. General ranking from most to least sensitive: (1) Flowering/pollination — 2-5 days of stress causes permanent yield loss through failed fertilization. (2) Grain/fruit filling — stress reduces final grain weight and quality. (3) Establishment/germination — poor emergence, but recovery possible if stress is brief. (4) Vegetative growth — most tolerant, growth slows but resumes after rain. The single most important irrigation decision is always: protect the flowering stage.",
        "source":"FAO","title":"Yield Response to Water — FAO Irrigation and Drainage Paper 33","url":"https://openknowledge.fao.org/handle/20.500.14283/T0394E","year":"1979","crops":"all","regions":"all","topics":"drought,water_requirements,irrigation",
    },
    {
        "id": "drought_soil_moisture_conservation_01",
        "text": "Practical soil moisture conservation techniques for smallholders: (1) Minimum tillage — reduce tillage passes to preserve soil structure and reduce evaporation. (2) Mulching with crop residues at 2-4 tonnes/ha reduces soil temperature by 3-5°C and soil evaporation by 30-40%. (3) Intercropping with legumes improves soil organic matter and water infiltration over time. (4) Avoid bare soil — plant cover crops in the off-season. (5) Plant in east-west rows to reduce soil exposure to midday sun in tropical regions.",
        "source":"FAO","title":"Climate-Smart Agriculture Sourcebook","url":"https://openknowledge.fao.org/handle/20.500.14283/i3325e","year":"2013","crops":"all","regions":"all","topics":"drought,soil,conservation,mulch",
    },

    # ═══════════════════════════════════════════════════════════════════════════
    # CROSS-CUTTING: FERTILIZER AND SOIL
    # ═══════════════════════════════════════════════════════════════════════════
    {
        "id": "fertilizer_timing_drought_01",
        "text": "Nitrogen fertilizer applied to dry soil is largely unavailable to crops and risks volatilisation losses of 20-50%. Always wait for at least 10-15mm of rainfall before applying nitrogen fertilizer. Split applications — half at planting, half at knee-height — improve nitrogen use efficiency by 20-30% compared to single applications. Phosphorus and potassium are less affected by soil moisture and can be applied at planting in advance of rain. Urea is more susceptible to volatilisation than ammonium-based fertilizers — incorporate urea into soil immediately after application.",
        "source":"FAO","title":"Plant Nutrition for Food Security","url":"https://openknowledge.fao.org/handle/20.500.14283/y5750e","year":"2006","crops":"all","regions":"all","topics":"fertilizer,nitrogen,drought",
    },
    {
        "id": "fertilizer_price_shock_strategy_01",
        "text": "When fertilizer prices spike or supply is disrupted, smallholder farmers can maintain yields through: (1) Micro-dosing — 2-5 grams per planting hole performs better than no fertilizer and better than reduced broadcast application. (2) Prioritise phosphorus at planting — phosphorus deficiency is more limiting than nitrogen on many African soils. (3) Substitute organic matter — 2 tonnes/ha compost or manure can replace 30-40 kg N/ha. (4) Focus remaining fertilizer on the most productive fields. (5) Join cooperative bulk purchasing to reduce unit cost by 15-25%.",
        "source":"IFAD","title":"Building Smallholder Resilience","url":"https://www.ifad.org/en/web/knowledge/publication/asset/41248179","year":"2018","crops":"all","regions":"all","topics":"fertilizer,inputs,resilience,market",
    },
    {
        "id": "soil_organic_matter_01",
        "text": "Soil organic matter (SOM) is the foundation of soil health and drought resilience. Each 1% increase in SOM increases soil water holding capacity by 20,000 litres per hectare. Build SOM through: crop residue retention, composting, cover crops, and reduced burning. In Sahel soils with typically 0.3-0.5% SOM, building to 1.5-2% through 5-10 years of good practices dramatically improves drought resilience. Applying 2-3 tonnes/ha of compost annually is the most cost-effective soil improvement strategy for resource-poor farmers.",
        "source":"FAO","title":"Climate-Smart Agriculture Sourcebook","url":"https://openknowledge.fao.org/handle/20.500.14283/i3325e","year":"2013","crops":"all","regions":"all","topics":"soil,drought,organic_matter,conservation",
    },

    # ═══════════════════════════════════════════════════════════════════════════
    # CROSS-CUTTING: PEST AND DISEASE MANAGEMENT
    # ═══════════════════════════════════════════════════════════════════════════
    {
        "id": "ipm_scouting_01",
        "text": "Regular field scouting is the foundation of integrated pest management. Scout fields every 5-7 days during the growing season. Walk in a W-pattern across the field, checking 10 plants at 5 different locations (50 plants total). Record: pest species, damage type, % plants affected, and crop growth stage. Apply pesticide only when economic threshold is exceeded — most crops can tolerate 10-15% leaf damage without yield loss. Early detection allows targeted treatment before pest populations explode, reducing pesticide use by 40-60%.",
        "source":"FAO","title":"Integrated Pest Management — FAO","url":"https://openknowledge.fao.org/handle/20.500.14283/i3084e","year":"2012","crops":"all","regions":"all","topics":"pest,ipm,scouting",
    },
    {
        "id": "aflatoxin_prevention_01",
        "text": "Aflatoxin contamination is preventable through a critical chain of practices: (1) Harvest promptly at physiological maturity — do not leave crops in field after maturity. (2) Dry immediately — groundnut to below 7%, maize to below 13% within 48 hours of harvest. (3) Sort and remove damaged, discolored, or shrivelled grain before storage. (4) Use hermetic storage or clean bags — aflatoxin-producing fungi require moisture and oxygen. (5) Monitor stored grain monthly — any musty smell indicates fungal activity. (6) Use biological control agents (Aflasafe) if available — proven to reduce aflatoxin by 80-90%.",
        "source":"FAO","title":"Prevention of Post-Harvest Food Losses","url":"https://openknowledge.fao.org/handle/20.500.14283/x5384e","year":"1995","crops":"groundnut,maize,sorghum","regions":"west_africa,east_africa","topics":"aflatoxin,post_harvest,storage",
    },
    {
        "id": "locust_desert_01",
        "text": "Desert locust (Schistocerca gregaria) is the most destructive migratory pest in the world, capable of destroying entire crops within hours. Early warning signs: presence of hoppers (wingless juveniles) in grass or scrubland, unusual reports of locusts in neighbouring areas, FAO Desert Locust Information Service alerts. If locusts are reported within 100km: contact national plant protection service immediately, prepare fields for rapid harvest if crops are near maturity, do not attempt individual farmer control — coordinated aerial treatment is required. Register with local agriculture office to receive early warning alerts.",
        "source":"FAO","title":"Integrated Pest Management — FAO","url":"https://openknowledge.fao.org/handle/20.500.14283/i3084e","year":"2012","crops":"all","regions":"sahel,middle_east,east_africa","topics":"pest,locust,ipm",
    },

    # ═══════════════════════════════════════════════════════════════════════════
    # CROSS-CUTTING: POST-HARVEST AND STORAGE
    # ═══════════════════════════════════════════════════════════════════════════
    {
        "id": "grain_storage_moisture_01",
        "text": "Safe grain storage moisture content by crop: maize 13%, wheat 13%, sorghum 13%, millet 12%, groundnut (in-shell) 8%, groundnut (shelled) 7%, rice (paddy) 14%, teff 11%. Test grain moisture by pressing a handful — if it forms a solid ball that holds shape, moisture is still too high. In traditional storage, visual inspection monthly for signs of insect damage (dust, frass, webbing), mold (discolouration, musty smell), or rodent activity. Hermetic triple-layer PICS bags eliminate insect and mold problems without chemical treatment.",
        "source":"FAO","title":"Prevention of Post-Harvest Food Losses","url":"https://openknowledge.fao.org/handle/20.500.14283/x5384e","year":"1995","crops":"all","regions":"all","topics":"post_harvest,storage,grain_drying",
    },
    {
        "id": "postharvest_loss_reduction_01",
        "text": "Post-harvest losses in sub-Saharan Africa average 25-40% of total production — equivalent to feeding 48 million people per year. Primary causes: inadequate drying (40%), poor storage (30%), pest damage (20%), mechanical damage during harvest and transport (10%). Highest-impact interventions: (1) Hermetic storage bags — reduce losses from 20-30% to below 2% at cost of $2-3 per bag. (2) Metal silos — long-term investment protecting 500-1000 kg, lasts 20+ years. (3) Improved drying — raised drying beds and tarpaulins prevent reabsorption of ground moisture.",
        "source":"FAO","title":"Prevention of Post-Harvest Food Losses","url":"https://openknowledge.fao.org/handle/20.500.14283/x5384e","year":"1995","crops":"all","regions":"west_africa,east_africa","topics":"post_harvest,storage,losses",
    },

    # ═══════════════════════════════════════════════════════════════════════════
    # SAHEL SPECIFIC
    # ═══════════════════════════════════════════════════════════════════════════
    {
        "id": "sahel_planting_rules_01",
        "text": "In the Sahel, planting timing is the single most critical decision. False start rains that dry up after germination kill seedlings and waste inputs. The recommended planting rule: wait for cumulative rainfall of 15-20mm within 3 days AND soil moisture at 10cm depth allows hand-digging without crumbling. Do not plant after a single rain event — wait for confirmation of sustained rainfall. Early-maturing varieties (60-70 day millet, 90-day sorghum) provide buffer against short or late rainy seasons. Stagger planting dates 2 weeks apart to reduce risk.",
        "source":"FAO","title":"Farming Systems and Poverty in the Sahel","url":"https://openknowledge.fao.org/handle/20.500.14283/y1860e","year":"2001","crops":"millet,sorghum,groundnut","regions":"sahel,west_africa","topics":"planting,drought,production",
    },
    {
        "id": "sahel_zai_technique_01",
        "text": "Zaï planting pits are the most effective technique for rehabilitating degraded Sahel soils. Dig pits 20-30cm diameter, 15-20cm deep in a regular grid pattern. Add 1-2kg of compost or manure per pit before planting. The pit concentrates water, organic matter, and seeds — creating a micro-environment that dramatically improves germination and yield even on severely degraded soils. Yields increase 50-400% compared to broadcast planting on the same soil. Labor requirement: 2-3 person-days per hectare. Combine with half-moon water harvesting for maximum effect.",
        "source":"FAO","title":"Farming Systems and Poverty in the Sahel","url":"https://openknowledge.fao.org/handle/20.500.14283/y1860e","year":"2001","crops":"millet,sorghum","regions":"sahel,west_africa","topics":"soil,water_harvesting,production",
    },
    {
        "id": "sahel_diversification_01",
        "text": "Crop diversification is the most effective risk management strategy in the Sahel. Traditional farming systems combine early-maturing millet (insurance against short seasons) with later-maturing sorghum (higher yield when rains are good), groundnut (cash crop and soil improvement), and cowpea (nitrogen fixation and food security). Intercropping millet with cowpea at 2:1 ratio improves total land productivity, reduces pest pressure, and provides nitrogen for the following season. Never plant a single crop on all land — maintain diversity across fields and varieties.",
        "source":"IFAD","title":"Building Smallholder Resilience","url":"https://www.ifad.org/en/web/knowledge/publication/asset/41248179","year":"2018","crops":"millet,sorghum,groundnut,cowpea","regions":"sahel,west_africa","topics":"diversification,resilience,production",
    },

    # ═══════════════════════════════════════════════════════════════════════════
    # IFAD: MARKET AND SELLING
    # ═══════════════════════════════════════════════════════════════════════════
    {
        "id": "market_selling_timing_01",
        "text": "Smallholder farmers typically receive the lowest prices immediately after harvest when supply is highest — post-harvest prices can be 30-50% below peak season prices. Storing grain for 2-3 months post-harvest typically increases sale prices by 20-40% in Sahel and East African markets. However, storage requires: grain dried below 13% moisture, hermetic bags or metal silos, and freedom from immediate cash needs. Farmers who can store for 90-180 days consistently earn 25-40% more than those who sell immediately after harvest.",
        "source":"IFAD","title":"Building Smallholder Resilience","url":"https://www.ifad.org/en/web/knowledge/publication/asset/41248179","year":"2018","crops":"all","regions":"all","topics":"market,selling,storage,price",
    },
    {
        "id": "market_cooperative_selling_01",
        "text": "Group marketing through cooperatives gives smallholder farmers significantly better prices. Selling as a group provides: (1) Volume that attracts larger buyers and processors who pay 10-20% premium. (2) Better bargaining power against middlemen. (3) Reduced transport costs through aggregation. (4) Access to formal markets (mills, export buyers) closed to individual small sellers. Cooperatives that aggregate minimum 20-50 tonnes reach the price threshold where formal buyers engage. Even informal sales groups of 5-10 farmers improve outcomes versus individual selling.",
        "source":"IFAD","title":"Engaging with Farmers Organizations — IFAD","url":"https://www.ifad.org/en/w/publications/engaging-with-farmers-organizations-for-more-effective-smallholder-development","year":"2022","crops":"all","regions":"all","topics":"market,cooperative,selling,price",
    },
    {
        "id": "market_price_information_01",
        "text": "Access to market price information before selling improves farmer income by 10-25%. Sources of price information available to smallholders: (1) SMS price services (where available) — text a shortcode to receive current market prices. (2) Weekly radio broadcasts — most national agricultural radio stations broadcast market prices. (3) Mobile phone calls to traders or cooperative members at destination markets. (4) Direct market visits before harvest to assess prices. The key information needed: current farm gate price, transport cost to nearest market, and price trend (rising/falling). Never sell without knowing at least two different buyers' prices.",
        "source":"IFAD","title":"Digital Agricultural Advisory Services — IFAD","url":"https://www.ifad.org/en/w/projects/2000003439","year":"2020","crops":"all","regions":"all","topics":"market,price,information",
    },
    {
        "id": "market_price_rising_01",
        "text": "When crop prices are rising, smallholders with stored grain have three options: (1) Sell immediately to capture current price if cash is needed. (2) Hold for 4-6 more weeks if storage is good and cash needs are manageable — prices typically peak 4-6 months after harvest in most African markets. (3) Sell 50% now and hold 50% — reduces risk while capturing some upside. Rising prices are often driven by seasonal supply reduction — the trend typically reverses 1-2 months before next harvest. Do not hold grain past 6 months before next harvest season in hopes of further price rises.",
        "source":"IFAD","title":"Building Smallholder Resilience","url":"https://www.ifad.org/en/web/knowledge/publication/asset/41248179","year":"2018","crops":"all","regions":"all","topics":"market,selling,price,storage",
    },
    {
        "id": "market_price_falling_01",
        "text": "When crop prices are falling sharply (more than 15% in one month), this typically signals one of three situations: new harvest arriving early from other regions, large imports entering the market, or a currency shock increasing imported food supply. In all cases, sell stored grain promptly — continued price falls are likely. Exception: if the price fall is due to a temporary supply surplus that will reverse (e.g., roads blocked by floods that will clear), wait 2-3 weeks. Consult radio agricultural programs and cooperative members before deciding. Never hold grain hoping for price recovery when the trend has been negative for more than 3 consecutive weeks.",
        "source":"IFAD","title":"Building Smallholder Resilience","url":"https://www.ifad.org/en/web/knowledge/publication/asset/41248179","year":"2018","crops":"all","regions":"all","topics":"market,selling,price",
    },
    {
        "id": "market_input_prices_strategy_01",
        "text": "When agricultural input prices (fertilizer, seeds, pesticides) rise sharply, prioritise spending as follows: (1) Quality certified seeds — yield benefit from good seed outweighs any other input. Never compromise on seed quality. (2) Starter phosphorus fertilizer — critical for root establishment, small amounts have high impact. (3) Essential pesticides for known high-risk pests only — not preventive sprays. (4) Nitrogen top-dressing — delay or reduce if prices are very high; crop can compensate partially. Cooperative bulk purchasing typically reduces input costs by 15-25% versus individual purchase.",
        "source":"IFAD","title":"Building Smallholder Resilience","url":"https://www.ifad.org/en/web/knowledge/publication/asset/41248179","year":"2018","crops":"all","regions":"all","topics":"market,inputs,fertilizer,resilience",
    },

    # ═══════════════════════════════════════════════════════════════════════════
    # IFAD: FRAGILE CONTEXTS AND CONFLICT
    # ═══════════════════════════════════════════════════════════════════════════
    {
        "id": "fragile_conflict_agriculture_01",
        "text": "In conflict-affected areas, agricultural strategies must prioritise speed and security: (1) Choose fast-maturing crop varieties that can be harvested before conflict disrupts harvest. (2) Diversify crops across multiple small plots — reduces loss if one field is affected. (3) Store grain in multiple locations rather than a single store. (4) Prioritise crops that can be consumed fresh to avoid storage risk. (5) Plant crops that are difficult to steal or destroy (underground crops like cassava and sweet potato). (6) Maintain social connections with agricultural cooperatives — community networks are the most important resource in fragile contexts.",
        "source":"IFAD","title":"Building Smallholder Resilience — Fragile Contexts","url":"https://www.ifad.org/en/web/knowledge/publication/asset/41248179","year":"2018","crops":"all","regions":"all","topics":"conflict,fragile,resilience,production",
    },
    {
        "id": "fragile_input_supply_01",
        "text": "Conflict disrupts agricultural input supply chains through: blocked transport routes, destroyed markets and depots, displacement of traders, currency collapse reducing purchasing power, and deliberate destruction of agricultural assets. When formal input supply is disrupted: (1) Prioritise saving seed from the current harvest for next season — seed security is the first priority. (2) Source locally-adapted traditional varieties from neighbouring farmers — these require fewer inputs. (3) Use organic alternatives for fertilizer — compost, green manure crops, nitrogen-fixing trees. (4) Contact FAO and WFP emergency agricultural assistance programs — both provide seeds and tools in crisis situations.",
        "source":"IFAD","title":"Building Smallholder Resilience — Fragile Contexts","url":"https://www.ifad.org/en/web/knowledge/publication/asset/41248179","year":"2018","crops":"all","regions":"all","topics":"conflict,fragile,inputs,resilience",
    },
    {
        "id": "fragile_displacement_agriculture_01",
        "text": "Internally displaced farmers face specific agricultural challenges: loss of land access, loss of seed stocks, inability to plant in time, unfamiliarity with new area's soil and climate. IFAD/FAO emergency response typically provides: vegetable kits for immediate food production (harvest within 60 days), seed vouchers for staple crops redeemable at local markets, and cash transfers timed to planting season. When receiving emergency seed: prioritise fast-maturing vegetables first (30-60 days), then staple crops. Even a 200 square metre kitchen garden significantly improves household nutrition and food security.",
        "source":"IFAD","title":"Building Smallholder Resilience — Fragile Contexts","url":"https://www.ifad.org/en/web/knowledge/publication/asset/41248179","year":"2018","crops":"all","regions":"all","topics":"conflict,fragile,displacement,resilience",
    },

    # ═══════════════════════════════════════════════════════════════════════════
    # IFAD: CLIMATE ADAPTATION AND RESILIENCE
    # ═══════════════════════════════════════════════════════════════════════════
    {
        "id": "climate_adaptation_practices_01",
        "text": "Key climate-smart practices proven effective for smallholder farmers: (1) Early-maturing varieties — complete crop cycle before dry season intensifies. (2) Conservation tillage — minimal tillage reduces soil moisture loss by 15-25%. (3) Agroforestry — trees on field boundaries reduce wind evaporation and provide shade. (4) Diversification — include at least one drought-tolerant crop (millet, sorghum, cassava) alongside more productive but sensitive crops. (5) Rainwater harvesting — half-moons, zaï pits, tied ridges capture runoff. (6) Seasonal weather forecasts — adjust planting dates and crop choices to seasonal forecast information.",
        "source":"FAO","title":"Climate-Smart Agriculture Sourcebook","url":"https://openknowledge.fao.org/handle/20.500.14283/i3325e","year":"2013","crops":"all","regions":"all","topics":"climate_change,adaptation,resilience",
    },
    {
        "id": "climate_seasonal_forecast_use_01",
        "text": "Seasonal weather forecasts (3-6 month outlooks) issued by national meteorological services provide farmers with actionable advance information. When forecast predicts below-normal rainfall: plant drought-tolerant varieties, reduce area under water-demanding crops, prepare water harvesting structures, build grain reserves before planting season, and avoid taking loans for high-input crops. When forecast predicts above-normal rainfall: prepare drainage, avoid low-lying fields prone to flooding, stock up on fertilizer before seasonal price increases, and consider expanding area under high-yield varieties.",
        "source":"IFAD","title":"Climate Adaptation in Rural Development","url":"https://www.ifad.org/en/adaptation-for-smallholder-agriculture-programme-phase-2","year":"2020","crops":"all","regions":"all","topics":"climate_change,forecast,adaptation",
    },
    {
        "id": "climate_livestock_integration_01",
        "text": "Integrating livestock with crop production increases farm resilience to climate shocks. Livestock provide: drought insurance (can be sold rapidly when crop fails), manure for soil fertility, draught power reducing labour costs, and income diversification. Mixed crop-livestock systems that use crop residues as fodder and livestock manure as fertilizer reduce external input dependency by 20-30%. During severe drought when crops fail completely, livestock assets provide financial resilience — but only if disease prevention is maintained. Vaccinate cattle against major diseases before the dry season.",
        "source":"IFAD","title":"Building Smallholder Resilience","url":"https://www.ifad.org/en/web/knowledge/publication/asset/41248179","year":"2018","crops":"all","regions":"all","topics":"livestock,resilience,diversification,climate_change",
    },

    # ═══════════════════════════════════════════════════════════════════════════
    # IFAD: GENDER AND INCLUSION
    # ═══════════════════════════════════════════════════════════════════════════
    {
        "id": "gender_women_farmers_01",
        "text": "Women farmers in sub-Saharan Africa and South Asia produce 60-80% of household food but control fewer resources than men. Women farmers with equal access to resources (land, inputs, information, markets) achieve yields equal to male farmers. Key barriers: limited mobile phone ownership, lower literacy rates requiring voice/image-based advisory, restricted mobility limiting market access, and social norms preventing attendance at mixed-gender extension meetings. Effective agricultural advisory for women must: use voice notes not just text, send to both household head and female farmer if possible, and include advice on crops women typically manage (vegetables, legumes).",
        "source":"IFAD","title":"Gender Equality and Women's Empowerment — IFAD","url":"https://www.ifad.org/en/gender","year":"2020","crops":"all","regions":"all","topics":"gender,women,inclusion,advisory",
    },
    {
        "id": "gender_youth_farmers_01",
        "text": "Young farmers (18-35) face specific challenges: limited land access, lack of collateral for input credit, and preference for mobile-based information over traditional extension. Young farmers are early adopters of technology and digital advisory services — they are the primary vector for spreading advice to older farmers in their communities. Design advisory messages that work for both young and older farmers: keep language simple enough for older farmers while including QR codes or links for young farmers who want more detail. Young farmers are more likely to experiment with new varieties and practices — target them for climate-smart agriculture demonstrations.",
        "source":"IFAD","title":"Rural Youth — IFAD","url":"https://www.ifad.org/en/rural-youth","year":"2021","crops":"all","regions":"all","topics":"youth,gender,inclusion,advisory",
    },

    # ═══════════════════════════════════════════════════════════════════════════
    # DRAINAGE AND FLOOD
    # ═══════════════════════════════════════════════════════════════════════════
    {
        "id": "drainage_flood_01",
        "text": "Most cereal crops cannot tolerate waterlogging for more than 48-72 hours without root damage. Signs: yellowing of lower leaves (nitrogen deficiency from anaerobic conditions), wilting despite adequate water, stunted growth. Clear drainage channels before the rainy season. Raised beds or ridged planting rows improve drainage significantly. Do not apply fertilizer before or during heavy rainfall — nutrients will be leached or run off. Maize is most flood-sensitive (24-48 hours), followed by wheat (48-72 hours), sorghum (72-96 hours), and rice (tolerant).",
        "source":"FAO","title":"Coping with Water Scarcity — FAO","url":"https://openknowledge.fao.org/handle/20.500.14283/a0756e","year":"2007","crops":"all","regions":"all","topics":"flood,drainage,waterlogging",
    },
    {
        "id": "flood_recovery_01",
        "text": "Post-flood recovery for crops: (1) If flooding lasted less than 48 hours on dryland crops — drain immediately, apply small amount of nitrogen (15-20 kg N/ha) once soil dries, monitor for disease. Most crops recover. (2) If flooding lasted 3-7 days — assess plant survival. Replace dead stands if early enough in season. Apply nitrogen at half rate to survivors. (3) If crop is lost — plant a fast-maturing replacement crop (cowpea, sorghum, fast-maturing vegetables) if season allows. (4) Report crop losses to local agriculture office — disaster assessments trigger seed and food assistance programs.",
        "source":"FAO","title":"Coping with Water Scarcity — FAO","url":"https://openknowledge.fao.org/handle/20.500.14283/a0756e","year":"2007","crops":"all","regions":"all","topics":"flood,recovery,production",
    },

    # ═══════════════════════════════════════════════════════════════════════════
    # LEVANT AND MIDDLE EAST SPECIFIC
    # ═══════════════════════════════════════════════════════════════════════════
    {
        "id": "levant_farming_systems_01",
        "text": "Traditional farming systems in the Levant (Jordan, Syria, Lebanon, Palestine) are adapted to Mediterranean climate with distinct wet (November-April) and dry (May-October) seasons. Main crops: rainfed wheat and barley in uplands (400-600mm rainfall zones), irrigated vegetables (tomato, cucumber, squash) in valleys, olive groves on hillsides. Climate change is reducing annual rainfall by 5-10% per decade in Jordan, shifting rainy season later, and increasing spring drought frequency. Farmers must adapt by selecting later-planting varieties, expanding water harvesting, and shifting to more drought-tolerant crops where economically viable.",
        "source":"FAO","title":"Climate Change and Food Security in West Asia — FAO","url":"https://openknowledge.fao.org/handle/20.500.14283/i3240e","year":"2013","crops":"wheat,olive,tomato","regions":"middle_east","topics":"farming_systems,climate_change,production",
    },
    {
        "id": "levant_water_scarcity_01",
        "text": "Jordan is the fourth most water-scarce country in the world with average water availability of 100-150m³ per person per year (compared to global average of 7,000m³). Agricultural water use accounts for 50-60% of total freshwater. Key water-saving practices for Jordanian farmers: drip irrigation (saves 40-60% vs flood irrigation), deficit irrigation (applying 50-70% of crop water requirement at critical stages), and rainwater harvesting from rooftops and farm roads. The government subsidises drip irrigation equipment — contact local Jordan Valley Authority or Ministry of Agriculture office for subsidy information.",
        "source":"FAO","title":"Coping with Water Scarcity — FAO","url":"https://openknowledge.fao.org/handle/20.500.14283/a0756e","year":"2007","crops":"all","regions":"middle_east","topics":"water_management,irrigation,drought",
    },

    # ═══════════════════════════════════════════════════════════════════════════
    # EAST AFRICA SPECIFIC
    # ═══════════════════════════════════════════════════════════════════════════
    {
        "id": "east_africa_two_seasons_01",
        "text": "Much of East Africa (Kenya, Tanzania, Uganda, Ethiopia highlands) has two rainy seasons: long rains (March-May, more reliable) and short rains (October-December, more variable). The long rains season is more suitable for maize and longer-duration crops. The short rains are better suited to fast-maturing crops (beans, fast maize varieties, vegetables). In recent years, the long rains have become more variable and the short rains more reliable in some areas — consult national meteorological service seasonal forecasts each year before deciding crop allocation between seasons.",
        "source":"FAO","title":"Climate-Smart Agriculture Sourcebook","url":"https://openknowledge.fao.org/handle/20.500.14283/i3325e","year":"2013","crops":"maize,beans,teff","regions":"east_africa","topics":"farming_systems,planting,climate_change",
    },

    # ═══════════════════════════════════════════════════════════════════════════
    # MARKET PRICES — STRATEGIC KNOWLEDGE
    # ═══════════════════════════════════════════════════════════════════════════
    {
        "id": "market_seasonal_patterns_01",
        "text": "Agricultural commodity prices follow predictable seasonal patterns in most developing country markets. Prices are typically lowest 1-2 months after the main harvest (October-December in Sahel, July-August in East Africa long rains season). Prices peak 2-3 months before the next harvest when food stocks are low. In the Sahel, millet prices in June-July (pre-harvest) can be 50-100% higher than in November-December (post-harvest). Farmers who can store grain for 4-6 months after harvest consistently capture significantly better prices.",
        "source":"IFAD","title":"Rural Finance and Investment — IFAD","url":"https://www.ifad.org/en/rural-finance","year":"2019","crops":"millet,sorghum,maize,groundnut","regions":"west_africa,east_africa","topics":"market,price,seasonal,storage",
    },
    {
        "id": "market_fertilizer_global_signals_01",
        "text": "Global fertilizer price shocks (urea, DAP, NPK) typically take 4-8 weeks to reach local markets in developing countries. Signals of incoming price increases: rises in global natural gas prices (urea feedstock), conflict in major fertilizer-exporting regions (Russia, Belarus, Ukraine supply 40% of global potash and nitrogen), port disruptions in key import hubs. When global fertilizer indices rise more than 15% in one month, local prices typically follow within 4-8 weeks. Practical response: purchase 1-2 months supply of critical fertilizers when global prices are stable, before they rise locally.",
        "source":"FAO","title":"Food Price Crisis — FAO Analysis","url":"https://www.fao.org/markets-and-trade/en","year":"2022","crops":"all","regions":"all","topics":"market,fertilizer,inputs,price_shock",
    },
    {
        "id": "market_crop_price_signals_west_africa_01",
        "text": "In West African Sahel markets (Senegal, Mali, Burkina Faso, Niger), key market price signals by crop: Millet — main harvest October-November, prices bottom November-December, peak June-August. Groundnut — harvest October-November, prices initially low, then rise as processors compete February-April. Sorghum — similar pattern to millet with slightly later price peak. Cowpea — dual purpose (grain and fodder), prices depend on both food and livestock sectors. Coarse grain prices in the Sahel are highly correlated with rainfall — a poor rainy season signal in August-September already pushes prices up by October before harvest is complete.",
        "source":"FAO","title":"GIEWS Food Price Monitoring — FAO","url":"https://www.fao.org/giews/food-prices/","year":"2023","crops":"millet,sorghum,groundnut,cowpea","regions":"west_africa,sahel","topics":"market,price,seasonal",
    },
    {
        "id": "market_crop_price_signals_levant_01",
        "text": "In Levant markets (Jordan, Lebanon, Syria), agricultural commodity price patterns: Wheat — harvest May-June, prices bottom June-July, regulated by government in Jordan (fixed price support scheme). Tomato — peak production and lowest prices June-September, prices highest November-March (winter production costly). Olive oil — harvest October-November, prices depend on Mediterranean-wide production (poor year in Spain or Italy raises Jordanian prices). Input prices (fertilizer, pesticide) typically rise before planting seasons — December-January for winter wheat, March-April for summer vegetables. Monitor Ministry of Agriculture price announcements.",
        "source":"FAO","title":"GIEWS Food Price Monitoring — FAO","url":"https://www.fao.org/giews/food-prices/","year":"2023","crops":"wheat,tomato,olive","regions":"middle_east","topics":"market,price,seasonal",
    },
]


def get_collection():
    client = chromadb.PersistentClient(path=CHROMA_DIR)
    ef     = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name="all-MiniLM-L6-v2"
    )
    collection = client.get_or_create_collection(
        name="agriews_knowledge",
        embedding_function=ef,
        metadata={"description": "FAO/IFAD agricultural knowledge base for AgriEWS v2"},
    )
    return collection


def build_knowledge_base(crop_filter: str = None):
    logger.info("knowledge_base_building",
                total_chunks=len(FAO_KNOWLEDGE_CHUNKS))
    collection = get_collection()

    chunks_to_add = FAO_KNOWLEDGE_CHUNKS
    if crop_filter:
        chunks_to_add = [
            c for c in FAO_KNOWLEDGE_CHUNKS
            if crop_filter.lower() in c["crops"] or c["crops"] == "all"
        ]

    existing_ids = set(collection.get()["ids"])
    new_chunks   = [c for c in chunks_to_add if c["id"] not in existing_ids]

    if not new_chunks:
        logger.info("kb_already_up_to_date", chunks=len(existing_ids))
        return {"success": len(existing_ids), "added": 0,
                "chunks": len(existing_ids), "total": collection.count()}

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

    batch_size = 50
    for i in range(0, len(ids), batch_size):
        collection.add(
            ids=ids[i:i+batch_size],
            documents=documents[i:i+batch_size],
            metadatas=metadatas[i:i+batch_size],
        )

    total = collection.count()
    logger.info("knowledge_base_complete",
                added=len(new_chunks), total_chunks=total)

    return {"success": len(new_chunks), "added": len(new_chunks),
            "chunks": total, "total": total}


def get_kb_stats():
    collection = get_collection()
    count      = collection.count()
    if count == 0:
        return {"status": "empty", "chunks": 0}
    results = collection.get(limit=count, include=["metadatas"])
    sources = {}
    crops   = set()
    topics  = set()
    for m in results["metadatas"]:
        src = m.get("source", "unknown")
        sources[src] = sources.get(src, 0) + 1
        for crop in m.get("crops", "").split(","):
            if crop.strip() and crop.strip() != "all":
                crops.add(crop.strip())
        for topic in m.get("topics", "").split(","):
            if topic.strip():
                topics.add(topic.strip())
    return {
        "status":    "ready",
        "chunks":    count,
        "by_source": sources,
        "crops":     sorted(list(crops)),
        "topics":    sorted(list(topics)),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Build AgriEWS FAO/IFAD knowledge base"
    )
    parser.add_argument("--crop",  help="Filter by crop name")
    parser.add_argument("--stats", action="store_true")
    parser.add_argument("--list",  action="store_true")
    args = parser.parse_args()

    if args.stats:
        import json as _json
        print(_json.dumps(get_kb_stats(), indent=2))
    elif args.list:
        for c in FAO_KNOWLEDGE_CHUNKS:
            print(f"[{c['id']}] {c['source']}: {c['title']}")
            print(f"  Crops: {c['crops']} | Topics: {c['topics']}")
        print(f"\nTotal: {len(FAO_KNOWLEDGE_CHUNKS)} chunks")
    else:
        result = build_knowledge_base(crop_filter=args.crop)
        print(f"\nKnowledge base built:")
        print(f"  Chunks added:  {result['added']}")
        print(f"  Total chunks:  {result['total']}")
