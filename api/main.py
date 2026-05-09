"""
api/main.py
AgriEWS Control Room — web server and REST API.
"""
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
import json, os

app = FastAPI(title="AgriEWS Control Room")

@app.on_event("startup")
async def startup():
    from api.database import init_db
    init_db()

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    template_path = os.path.join(os.path.dirname(__file__), "..", "templates", "dashboard.html")
    with open(template_path) as f:
        return HTMLResponse(f.read())

# ── Districts ─────────────────────────────────────────────────────────────────

@app.get("/api/districts")
async def api_districts():
    from api.database import get_all_districts, get_farmers, get_pipeline_runs
    districts = get_all_districts()
    for d in districts:
        try: d['crops'] = json.loads(d['crops'])
        except: d['crops'] = []
        try: d['languages'] = json.loads(d['languages'])
        except: d['languages'] = []
        try: d['channels'] = json.loads(d['channels'])
        except: d['channels'] = []
        d['farmers']  = len(get_farmers(d['id']))
        runs = get_pipeline_runs(d['id'], limit=1)
        d['last_run'] = runs[0] if runs else None
    return districts

@app.post("/api/districts")
async def api_create_district(request: Request):
    from api.database import create_district
    data = await request.json()
    try:
        district_id = create_district(data)
        return {"id": district_id, "status": "created"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.delete("/api/districts/{district_id}")
async def api_delete_district(district_id: str):
    from api.database import delete_district
    delete_district(district_id)
    return {"status": "deactivated"}

# ── Farmers ───────────────────────────────────────────────────────────────────

@app.get("/api/farmers")
async def api_farmers(district_id: str = None):
    from api.database import get_farmers
    farmers = get_farmers(district_id)
    for f in farmers:
        try: f['crops'] = json.loads(f['crops'])
        except: f['crops'] = []
    return farmers

@app.post("/api/farmers")
async def api_create_farmer(request: Request):
    from api.database import create_farmer
    data = await request.json()
    try:
        farmer_id = create_farmer(data)
        return {"id": farmer_id, "status": "created"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.delete("/api/farmers/{farmer_id}")
async def api_delete_farmer(farmer_id: str):
    from api.database import delete_farmer
    delete_farmer(farmer_id)
    return {"status": "deactivated"}

# ── Crops ─────────────────────────────────────────────────────────────────────

@app.get("/api/crops")
async def api_crops():
    from api.database import get_crops
    return get_crops()

@app.post("/api/crops")
async def api_create_crop(request: Request):
    from api.database import create_crop
    data = await request.json()
    try:
        crop_id = create_crop(data)
        return {"id": crop_id, "status": "created"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# ── Pipeline ──────────────────────────────────────────────────────────────────

@app.get("/api/pipeline/runs")
async def api_pipeline_runs(district_id: str = None):
    from api.database import get_pipeline_runs
    return get_pipeline_runs(district_id, limit=50)

@app.post("/api/pipeline/log")
async def api_log_run(request: Request):
    from api.database import log_pipeline_run
    data = await request.json()
    log_pipeline_run(data)
    return {"status": "logged"}

# ── Reports ───────────────────────────────────────────────────────────────────

@app.get("/api/reports")
async def api_reports():
    from api.database import get_field_reports
    return get_field_reports()

# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "service": "AgriEWS Control Room"}
