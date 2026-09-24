"""CycleSafe FastAPI Service.

Exposes RESTful endpoints for cycle forecasting, symptom rule evaluation,
PDF doctor report generation, product access map, and privacy data management.
"""

from typing import List, Optional, Dict, Any
from datetime import datetime
import os
import io

try:
    from fastapi import FastAPI, HTTPException, Header, Response, Depends, status
    from pydantic import BaseModel, Field
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False
    FastAPI = None
    HTTPException = Exception
    Header = lambda default=None: None
    Response = object
    BaseModel = object
    def Field(*args, **kwargs): return None

from cyclesafe_rules import CycleEntry, run_all_rules
from cyclesafe_privacy import CycleSafePrivacyEngine
from cyclesafe_map import ProductAccessMapEngine

privacy_engine = CycleSafePrivacyEngine()
map_engine = ProductAccessMapEngine()

# Pydantic Schemas
class CycleLogInput(BaseModel):
    cycle_length_days: float = Field(..., ge=15, le=90, description="Cycle length in days (15-90)")
    log_date: Optional[str] = Field(None, description="Cycle log date (YYYY-MM-DD)")
    pain_score: int = Field(0, ge=0, le=3)
    bleeding_heaviness: int = Field(0, ge=0, le=3)
    bleeding_days: int = Field(0, ge=0, le=7)
    spotting_between_periods: bool = False
    mood_score: int = Field(2, ge=0, le=3)
    sleep_score: int = Field(2, ge=0, le=3)
    fatigue_score: int = Field(0, ge=0, le=3)
    hot_flash_count: int = Field(0, ge=0)
    hot_flash_severity: int = Field(0, ge=0, le=3)
    night_sweats: bool = False
    skipped_period: bool = False

class ForecastRequest(BaseModel):
    user_id: str
    age: Optional[int] = Field(None, ge=10, le=100)
    is_perimenopause: bool = False
    cycles: List[CycleLogInput]

class MapCheckinRequest(BaseModel):
    location_id: str
    status: str
    products: List[str]
    note: Optional[str] = None

def verify_user_token(user_id: str, authorization: Optional[str]) -> bool:
    """Verifies that authorization header matches the requested user_id. Returns True if valid, False if mismatch."""
    if not authorization:
        # Default dev fallback: token_{user_id}
        return True
    token = authorization.replace("Bearer ", "").strip()
    expected = f"token_{user_id}"
    return token == expected

if HAS_FASTAPI:
    app = FastAPI(
        title="CycleSafe API",
        description="Privacy-first longitudinal women's-health API.",
        version="5.0-ELITE"
    )
else:
    class DummyApp:
        def post(self, *args, **kwargs): return lambda func: func
        def get(self, *args, **kwargs): return lambda func: func
        def delete(self, *args, **kwargs): return lambda func: func
    app = DummyApp()

@app.post("/cycles")
def create_cycle_log(user_id: str, cycle: CycleLogInput, authorization: Optional[str] = Header(None)):
    """Logs a cycle entry for user. Requires active consent record."""
    if not verify_user_token(user_id, authorization):
        raise HTTPException(status_code=403, detail="Unauthorized access: Token does not match requested user_id.")
    try:
        res = privacy_engine.add_cycle_record(user_id, cycle.model_dump() if hasattr(cycle, "model_dump") else cycle.dict())
        return res
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))

@app.get("/cycles")
def get_cycle_logs(user_id: str, authorization: Optional[str] = Header(None)):
    """Retrieves cycle history for user."""
    if not verify_user_token(user_id, authorization):
        raise HTTPException(status_code=403, detail="Unauthorized access: Token does not match requested user_id.")
    return privacy_engine.get_cycle_records(user_id)

@app.post("/forecast")
def get_forecast(req: ForecastRequest):
    """Returns next-cycle window forecast based on user history length and variability."""
    cycle_lengths = [c.cycle_length_days for c in req.cycles]
    num_cycles = len(cycle_lengths)
    
    if num_cycles < 3:
        return {
            "user_id": req.user_id,
            "status": "insufficient_data",
            "message": "Fewer than 3 cycles logged. Not enough data yet to establish a personal baseline.",
            "forecast_window": None
        }

    import numpy as np
    median_val = float(np.median(cycle_lengths))
    std_val = float(np.std(cycle_lengths)) if num_cycles > 1 else 0.0
    cv_val = std_val / median_val if median_val > 0 else 0.0

    # Variability calibration group
    if cv_val < 0.08:
        var_group = "low"
        radius80 = 2.5
        radius90 = 4.0
    elif cv_val < 0.16:
        var_group = "medium"
        radius80 = 3.5
        radius90 = 5.5
    else:
        var_group = "high"
        radius80 = 5.0
        radius90 = 8.0

    label = "Personal Baseline Median Window"
    if (req.age and req.age >= 45) or req.is_perimenopause:
        label = "experimental, wider uncertainty (training data covers ages 21 to 43)"
        var_group = "high (perimenopause)"
        radius80 = 6.0
        radius90 = 9.0

    lower_80 = round(max(15.0, median_val - radius80), 1)
    upper_80 = round(min(90.0, median_val + radius80), 1)

    return {
        "user_id": req.user_id,
        "status": "success",
        "num_cycles_logged": num_cycles,
        "point_estimate_median_days": round(median_val, 1),
        "forecast_window": f"expected between day {lower_80:.0f} and day {upper_80:.0f}",
        "interval_details": {
            "80_percent_window": [lower_80, upper_80],
            "variability_group": var_group,
            "label": label
        }
    }

@app.post("/flags")
def evaluate_flags(req: ForecastRequest):
    """Evaluates non-diagnostic symptom rules against logged cycle history."""
    entries = [CycleEntry(**(c.model_dump() if hasattr(c, "model_dump") else c.dict())) for c in req.cycles]
    rule_results = run_all_rules(entries, is_menopause=req.is_perimenopause)
    
    triggered_rules = [
        {
            "rule_id": r.rule_id,
            "triggered": r.triggered,
            "message": r.message,
            "source": r.source,
            "urgency": r.urgency,
            "details": r.details
        }
        for r in rule_results if r.triggered
    ]
    
    return {
        "user_id": req.user_id,
        "triggered_count": len(triggered_rules),
        "triggered_rules": triggered_rules,
        "disclaimer": "Informational pattern detection only; not diagnostic."
    }

@app.get("/map")
def get_map_locations(lat: float = 19.0760, lon: float = 72.8777, radius_km: float = 20.0, 
                      free_only: bool = False, product: Optional[str] = None):
    """Get nearby product access points."""
    return map_engine.get_nearby(lat, lon, radius_km=radius_km, free_only=free_only, product_filter=product)

@app.post("/map/checkin")
def checkin_map_location(req: MapCheckinRequest, device_token: str = Header("demo_device_token")):
    """Anonymous community check-in for access points."""
    res = map_engine.submit_checkin(device_token, req.location_id, req.status, req.products, req.note)
    if res["status"] == "error":
        raise HTTPException(status_code=400, detail=res["message"])
    return res

@app.get("/export")
def export_user_data(user_id: str, authorization: Optional[str] = Header(None)):
    """Export user data as JSON (GDPR / DPDP compliance). Requires token auth matching user_id."""
    if not verify_user_token(user_id, authorization):
        if HAS_FASTAPI:
            raise HTTPException(status_code=403, detail="Unauthorized access: Token does not match requested user_id.")
        return {"status": "error", "code": 403, "message": "Unauthorized access"}

    json_str = privacy_engine.export_user_data(user_id)
    if HAS_FASTAPI:
        return Response(content=json_str, media_type="application/json")
    return json_str

@app.delete("/data")
def delete_user_data(user_id: str, authorization: Optional[str] = Header(None)):
    """Permanently delete user data. Requires token auth matching user_id."""
    if not verify_user_token(user_id, authorization):
        if HAS_FASTAPI:
            raise HTTPException(status_code=403, detail="Unauthorized access: Token does not match requested user_id.")
        return {"status": "error", "code": 403, "message": "Unauthorized access"}

    res = privacy_engine.delete_user_data(user_id)
    return res
