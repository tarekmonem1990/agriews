"""
api/main.py
AgriEWS web server — serves the control room dashboard
and provides REST API for managing districts, farmers, and crops.
"""
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
import os, json
from database import (
    init_db, get_all_districts, get_district, create_district, delete_district,
    get_farmers, create_farmer, delete_farmer,
    get_crops, create_crop,
    get_pipeline_runs, get_field_reports, log_pipeline_run
)

app = FastAPI(title="AgriEWS Control Room")

@app.on_event("startup")
async def startup():
    init_db()

# ── Dashboard ──────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    with open("templates/dashboard.html") as f:
        return HTMLResponse(f.read())

# ── Districts API ──────────────────────────────────────────────────────────────

@app.get("/api/districts")
async def api_districts():
    districts = get_all_districts()
    for d in districts:
        d['crops']     = json.loads(d['crops'])
        d['languages'] = json.loads(d['languages'])
        d['channels']  = json.loads(d['channels'])
        d['farmers']   = len(get_farmers(d['id']))
        runs = get_pipeline_runs(d['id'], limit=1)
        d['last_run']  = runs[0] if runs else None
    return districts

@app.post("/api/districts")
async def api_create_district(request: Request):
    data = await request.json()
    try:
        district_id = create_district(data)
        return {"id": district_id, "status": "created"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.delete("/api/districts/{district_id}")
async def api_delete_district(district_id: str):
    delete_district(district_id)
    return {"status": "deactivated"}

# ── Farmers API ────────────────────────────────────────────────────────────────

@app.get("/api/farmers")
async def api_farmers(district_id: str = None):
    farmers = get_farmers(district_id)
    for f in farmers:
        f['crops'] = json.loads(f['crops'])
    return farmers

@app.post("/api/farmers")
async def api_create_farmer(request: Request):
    data = await request.json()
    try:
        farmer_id = create_farmer(data)
        return {"id": farmer_id, "status": "created"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.delete("/api/farmers/{farmer_id}")
async def api_delete_farmer(farmer_id: str):
    delete_farmer(farmer_id)
    return {"status": "deactivated"}

# ── Crops API ──────────────────────────────────────────────────────────────────

@app.get("/api/crops")
async def api_crops():
    return get_crops()

@app.post("/api/crops")
async def api_create_crop(request: Request):
    data = await request.json()
    try:
        crop_id = create_crop(data)
        return {"id": crop_id, "status": "created"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# ── Pipeline API ───────────────────────────────────────────────────────────────

@app.get("/api/pipeline/runs")
async def api_pipeline_runs(district_id: str = None):
    return get_pipeline_runs(district_id, limit=50)

@app.post("/api/pipeline/log")
async def api_log_run(request: Request):
    data = await request.json()
    log_pipeline_run(data)
    return {"status": "logged"}

# ── Field reports API ──────────────────────────────────────────────────────────

@app.get("/api/reports")
async def api_reports():
    return get_field_reports()

# ── Health ─────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "service": "AgriEWS Control Room"}
