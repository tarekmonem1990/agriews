"""
api/database.py
Database models and connection for AgriEWS.
Uses SQLite for simplicity (no extra setup needed on Railway).
Automatically creates tables on first run.
"""
import sqlite3
import os
import json
from datetime import datetime

DB_PATH = os.getenv("DATABASE_PATH", "/tmp/agriews.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS districts (
            id TEXT PRIMARY KEY,
            country_iso TEXT NOT NULL,
            name TEXT NOT NULL,
            region TEXT NOT NULL,
            lat REAL NOT NULL,
            lon REAL NOT NULL,
            crops TEXT NOT NULL,
            languages TEXT NOT NULL,
            channels TEXT NOT NULL,
            timezone TEXT DEFAULT 'UTC',
            fragile INTEGER DEFAULT 0,
            active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS farmers (
            id TEXT PRIMARY KEY,
            district_id TEXT NOT NULL,
            name TEXT,
            phone TEXT NOT NULL UNIQUE,
            preferred_channel TEXT NOT NULL,
            preferred_language TEXT NOT NULL,
            crops TEXT NOT NULL,
            voice_notes INTEGER DEFAULT 1,
            active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (district_id) REFERENCES districts(id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS crops (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            name_local TEXT,
            category TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS pipeline_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            district_id TEXT,
            ran_at TEXT DEFAULT CURRENT_TIMESTAMP,
            status TEXT,
            rain_7d REAL,
            spi REAL,
            hazard_level TEXT,
            prices_count INTEGER DEFAULT 0,
            shocks_count INTEGER DEFAULT 0,
            pests_count INTEGER DEFAULT 0,
            advisories_sent INTEGER DEFAULT 0,
            notes TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS field_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            farmer_phone TEXT,
            district_id TEXT,
            report_type TEXT,
            message TEXT,
            received_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Seed default crops
    default_crops = [
        ("groundnut","Groundnut","Arachide","legume"),
        ("millet","Millet","Mil","cereal"),
        ("sorghum","Sorghum","Sorgho","cereal"),
        ("maize","Maize","Maïs","cereal"),
        ("rice","Rice","Riz","cereal"),
        ("wheat","Wheat","Blé","cereal"),
        ("teff","Teff","Teff","cereal"),
        ("cassava","Cassava","Manioc","root"),
        ("potato","Potato","Pomme de terre","root"),
        ("tomato","Tomato","Tomate","vegetable"),
        ("onion","Onion","Oignon","vegetable"),
        ("cowpea","Cowpea","Niébé","legume"),
        ("sesame","Sesame","Sésame","oilseed"),
        ("sugarcane","Sugarcane","Canne à sucre","cash"),
        ("cotton","Cotton","Coton","cash"),
    ]
    for crop_id, name, name_local, category in default_crops:
        c.execute("""
            INSERT OR IGNORE INTO crops (id, name, name_local, category)
            VALUES (?,?,?,?)
        """, (crop_id, name, name_local, category))

    # Seed default district if empty
    c.execute("SELECT COUNT(*) FROM districts")
    if c.fetchone()[0] == 0:
        c.execute("""
            INSERT INTO districts
            (id, country_iso, name, region, lat, lon, crops, languages, channels, timezone, fragile)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (
            "sn_kaffrine_nord", "SN", "Kaffrine Nord", "west_africa",
            14.105, -15.551,
            json.dumps(["groundnut","millet","sorghum"]),
            json.dumps(["french"]),
            json.dumps(["whatsapp"]),
            "Africa/Dakar", 0
        ))

    conn.commit()
    conn.close()

# ── CRUD helpers ──────────────────────────────────────────────────────────────

def get_all_districts():
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM districts WHERE active=1 ORDER BY name"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_district(district_id):
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM districts WHERE id=?", (district_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None

def create_district(data):
    import re
    district_id = re.sub(r'[^a-z0-9_]', '_',
        f"{data['country_iso'].lower()}_{data['name'].lower().replace(' ','_')}"
    )
    conn = get_db()
    conn.execute("""
        INSERT INTO districts
        (id, country_iso, name, region, lat, lon, crops, languages, channels, timezone, fragile)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, (
        district_id,
        data['country_iso'].upper(),
        data['name'],
        data.get('region','other'),
        float(data['lat']),
        float(data['lon']),
        json.dumps(data['crops'] if isinstance(data['crops'], list)
                   else data['crops'].split(',')),
        json.dumps(data['languages'] if isinstance(data['languages'], list)
                   else data['languages'].split(',')),
        json.dumps(data.get('channels', ['whatsapp']) if isinstance(data.get('channels'), list)
                   else data.get('channels','whatsapp').split(',')),
        data.get('timezone','UTC'),
        1 if data.get('fragile') else 0
    ))
    conn.commit()
    conn.close()
    return district_id

def delete_district(district_id):
    conn = get_db()
    conn.execute("UPDATE districts SET active=0 WHERE id=?", (district_id,))
    conn.commit()
    conn.close()

def get_farmers(district_id=None):
    conn = get_db()
    if district_id:
        rows = conn.execute(
            "SELECT * FROM farmers WHERE active=1 AND district_id=? ORDER BY name",
            (district_id,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM farmers WHERE active=1 ORDER BY district_id, name"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def create_farmer(data):
    import uuid
    farmer_id = "f_" + str(uuid.uuid4())[:8]
    conn = get_db()
    conn.execute("""
        INSERT INTO farmers
        (id, district_id, name, phone, preferred_channel, preferred_language,
         crops, voice_notes)
        VALUES (?,?,?,?,?,?,?,?)
    """, (
        farmer_id,
        data['district_id'],
        data.get('name',''),
        data['phone'],
        data.get('channel','whatsapp'),
        data.get('language','french'),
        json.dumps(data['crops'] if isinstance(data['crops'], list)
                   else data['crops'].split(',')),
        1 if data.get('voice_notes', True) else 0
    ))
    conn.commit()
    conn.close()
    return farmer_id

def delete_farmer(farmer_id):
    conn = get_db()
    conn.execute("UPDATE farmers SET active=0 WHERE id=?", (farmer_id,))
    conn.commit()
    conn.close()

def get_crops():
    conn = get_db()
    rows = conn.execute("SELECT * FROM crops ORDER BY category, name").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def create_crop(data):
    import re
    crop_id = re.sub(r'[^a-z0-9_]', '_', data['name'].lower().strip())
    conn = get_db()
    conn.execute("""
        INSERT OR IGNORE INTO crops (id, name, name_local, category)
        VALUES (?,?,?,?)
    """, (crop_id, data['name'], data.get('name_local',''), data.get('category','other')))
    conn.commit()
    conn.close()
    return crop_id

def log_pipeline_run(data):
    conn = get_db()
    conn.execute("""
        INSERT INTO pipeline_runs
        (district_id, status, rain_7d, spi, hazard_level,
         prices_count, shocks_count, pests_count, advisories_sent, notes)
        VALUES (?,?,?,?,?,?,?,?,?,?)
    """, (
        data.get('district_id'),
        data.get('status','ok'),
        data.get('rain_7d'),
        data.get('spi'),
        data.get('hazard_level'),
        data.get('prices_count',0),
        data.get('shocks_count',0),
        data.get('pests_count',0),
        data.get('advisories_sent',0),
        data.get('notes',''),
    ))
    conn.commit()
    conn.close()

def get_pipeline_runs(district_id=None, limit=20):
    conn = get_db()
    if district_id:
        rows = conn.execute(
            "SELECT * FROM pipeline_runs WHERE district_id=? ORDER BY ran_at DESC LIMIT ?",
            (district_id, limit)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM pipeline_runs ORDER BY ran_at DESC LIMIT ?",
            (limit,)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_field_reports(limit=50):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM field_reports ORDER BY received_at DESC LIMIT ?",
        (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def save_field_report(phone, district_id, report_type, message):
    conn = get_db()
    conn.execute("""
        INSERT INTO field_reports (farmer_phone, district_id, report_type, message)
        VALUES (?,?,?,?)
    """, (phone, district_id, report_type, message))
    conn.commit()
    conn.close()
