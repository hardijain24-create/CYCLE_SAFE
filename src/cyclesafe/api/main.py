"""CycleSafe FastAPI Service.

Exposes RESTful endpoints for cycle forecasting, symptom rule evaluation,
PDF doctor report generation, product access map, and privacy data management.
"""

from typing import List, Optional, Dict, Any
from datetime import datetime
import os
import secrets
import hashlib

from fastapi import FastAPI, HTTPException, Header, Response, Request, Depends, status
from pydantic import BaseModel, Field

from cyclesafe.rules.engine import CycleEntry, run_all_rules
from cyclesafe.privacy.engine import CycleSafePrivacyEngine
from cyclesafe.map.engine import ProductAccessMapEngine
from cyclesafe.forecast import forecast_next_cycle

privacy_engine = CycleSafePrivacyEngine()
map_engine = ProductAccessMapEngine()


def _hash_token(token: str) -> str:
    """One-way SHA-256 hash of a bearer token for storage."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_token_and_user(user_id: str, authorization: Optional[str]) -> bool:
    """Verifies that Authorization header contains a valid token matching user_id.
    
    Looks up the stored token_hash for the user and compares against the hash
    of the presented bearer token.
    """
    if not authorization:
        return False
    token = authorization.replace("Bearer ", "").strip()
    if not token:
        return False
    
    consent = privacy_engine.get_consent(user_id)
    if not consent:
        return False
    
    stored_hash = consent.get("token_hash")
    if not stored_hash:
        return False

    presented_hash = _hash_token(token)
    # Constant-time comparison
    return secrets.compare_digest(stored_hash, presented_hash)


# Pydantic Schemas
class CycleLogInput(BaseModel):
    cycle_length_days: float = Field(..., ge=15, le=90, description="Cycle length in days (15-90)")
    log_date: Optional[str] = Field(None, description="Cycle log date (YYYY-MM-DD)")
    last_period_date: Optional[str] = Field(None, description="Last period date (YYYY-MM-DD)")
    heavy_soaking_hourly: bool = Field(False, description="Heavy soaking pad/tampon hourly indicator")
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

app = FastAPI(
    title="CycleSafe API",
    description="Privacy-first longitudinal women's-health API.",
    version="5.0-ELITE"
)

def check_auth(user_id: str, authorization: Optional[str]):
    if not authorization:
        raise HTTPException(status_code=401, detail="Unauthorized: Missing Authorization header.")
    if not verify_token_and_user(user_id, authorization):
        raise HTTPException(status_code=403, detail="Forbidden: Invalid token or token belongs to a different user.")

@app.post("/consent")
def register_consent(user_id: str):
    """Registers active consent for a NEW user and returns a random bearer token.
    
    If the user already has an active consent record, returns 409 Conflict.
    The plaintext token is shown exactly once; only its SHA-256 hash is stored.
    """
    if not user_id or not user_id.strip():
        raise HTTPException(status_code=400, detail="User ID required.")
    
    # Check if user already exists with active consent
    existing = privacy_engine.get_consent(user_id)
    if existing and existing.get("active"):
        raise HTTPException(
            status_code=409,
            detail="User already registered. Token was shown at registration and cannot be retrieved again."
        )
    
    # Generate a cryptographically random token
    token = secrets.token_hex(32)  # 64-char hex string
    token_hash = _hash_token(token)
    
    privacy_engine.register_consent(user_id, token_hash=token_hash)
    return {
        "status": "success",
        "user_id": user_id,
        "token": token,
        "message": "Consent registered. Save your token securely — it will not be shown again."
    }

@app.post("/consent/withdraw")
def withdraw_consent(user_id: str, authorization: Optional[str] = Header(None)):
    """Withdraws consent for user."""
    check_auth(user_id, authorization)
    res = privacy_engine.withdraw_consent(user_id)
    return res

@app.post("/cycles")
def create_cycle_log(user_id: str, cycle: CycleLogInput, authorization: Optional[str] = Header(None)):
    """Logs a cycle entry for user. Requires token auth and active consent."""
    check_auth(user_id, authorization)
    try:
        data = cycle.model_dump() if hasattr(cycle, "model_dump") else cycle.dict()
        res = privacy_engine.add_cycle_record(user_id, data)
        return res
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))

@app.get("/cycles")
def get_cycle_logs(user_id: str, authorization: Optional[str] = Header(None)):
    """Retrieves cycle history for user."""
    check_auth(user_id, authorization)
    if not privacy_engine.has_active_consent(user_id):
        raise HTTPException(status_code=403, detail="Consent withdrawn.")
    return privacy_engine.get_cycle_records(user_id)

@app.post("/forecast")
def get_forecast(req: ForecastRequest):
    """Returns next-cycle window forecast using single unified forecast entrypoint."""
    cycle_lengths = [c.cycle_length_days for c in req.cycles]
    res = forecast_next_cycle(cycle_lengths, age=req.age, is_perimenopause=req.is_perimenopause)
    return {
        "user_id": req.user_id,
        "status": "success" if res["forecast_available"] else "insufficient_data",
        **res
    }

@app.post("/flags")
def evaluate_flags(req: ForecastRequest):
    """Evaluates non-diagnostic symptom rules against logged cycle history."""
    entries = []
    for c in req.cycles:
        data = c.model_dump() if hasattr(c, "model_dump") else c.dict()
        entries.append(CycleEntry(**data))
    
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
def checkin_map_location(req: MapCheckinRequest, request: Request, device_token: Optional[str] = Header(None, alias="device-token"), device_token_alt: Optional[str] = Header(None, alias="device_token")):
    """Anonymous community check-in for access points."""
    token = device_token or device_token_alt
    if not token:
        raise HTTPException(status_code=400, detail="Missing required header 'device-token'.")
    
    client_ip = request.client.host if request.client else "127.0.0.1"
    res = map_engine.submit_checkin(token, req.location_id, req.status, req.products, req.note, client_ip=client_ip)
    if res["status"] == "error":
        if "Rate limit" in res.get("message", ""):
            raise HTTPException(status_code=429, detail=res["message"])
        raise HTTPException(status_code=400, detail=res["message"])
    return res

@app.get("/export")
def export_user_data(user_id: str, authorization: Optional[str] = Header(None)):
    """Export user data as JSON (GDPR / DPDP compliance). Requires token auth matching user_id."""
    check_auth(user_id, authorization)
    json_str = privacy_engine.export_user_data(user_id)
    return Response(content=json_str, media_type="application/json")

@app.delete("/data")
def delete_user_data(user_id: str, authorization: Optional[str] = Header(None)):
    """Permanently delete user data. Requires token auth matching user_id."""
    check_auth(user_id, authorization)
    res = privacy_engine.delete_user_data(user_id)
    return res
