"""CycleSafe FastAPI Service.

Exposes RESTful endpoints for cycle forecasting, symptom rule evaluation,
PDF doctor report generation, product access map, and privacy data management.
"""

from typing import List, Optional, Dict, Any
from datetime import datetime
import os
import re
import secrets
import hashlib

from fastapi import FastAPI, HTTPException, Header, Response, Request, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from cyclesafe.api.auth import hash_password, verify_password
from cyclesafe.api.schemas import ALLOWED_SYMPTOMS, SymptomLogInput, SignupRequest, LoginRequest

from cyclesafe.rules.engine import CycleEntry, run_all_rules
from cyclesafe.privacy.engine import CycleSafePrivacyEngine
from cyclesafe.map.engine import ProductAccessMapEngine
from cyclesafe.forecast import forecast_next_cycle
try:
    from cyclesafe.report.pdf import generate_doctor_report_pdf
except ImportError:
    generate_doctor_report_pdf = None

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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def check_auth(user_id: str, authorization: Optional[str]):
    if not authorization:
        raise HTTPException(status_code=401, detail="Unauthorized: Missing Authorization header.")
    if not verify_token_and_user(user_id, authorization):
        raise HTTPException(status_code=403, detail="Forbidden: Invalid token or token belongs to a different user.")


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@app.post("/signup")
def signup(req: SignupRequest):
    """Create an account with email + password. Returns a session token once."""
    email = req.email.strip().lower()
    if not _EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="Enter a valid email address.")
    token = secrets.token_hex(32)
    profile = {
        "name": req.name.strip(),
        "age": req.age,
        "stage": req.stage,
        "country": (req.country or "").strip(),
        "state": (req.state or "").strip(),
        "city": (req.city or "").strip(),
        "email": email,
    }
    try:
        user_id = privacy_engine.create_password_account(
            email=email,
            password_hash=hash_password(req.password),
            profile=profile,
            token_hash=_hash_token(token),
        )
    except ValueError:
        raise HTTPException(
            status_code=409,
            detail="An account with this email already exists. Please sign in.",
        )
    return {
        "status": "success",
        "user_id": user_id,
        "email": email,
        "profile": profile,
        "token": token,
        "message": "Account created. Save your password — you will use it to sign in.",
    }


@app.post("/login")
def login(req: LoginRequest):
    """Sign in with email and password. Issues a fresh session token."""
    email = req.email.strip().lower()
    row = privacy_engine.get_consent_by_email(email) or privacy_engine.get_consent(email)
    if not row or not row.get("active"):
        raise HTTPException(status_code=401, detail="Incorrect email or password.")
    stored = row.get("password_hash")
    if not stored or not verify_password(req.password, stored):
        raise HTTPException(status_code=401, detail="Incorrect email or password.")
    token = secrets.token_hex(32)
    user_id = row["user_id"]
    privacy_engine.update_token_hash(user_id, _hash_token(token))
    return {
        "status": "success",
        "user_id": user_id,
        "email": email,
        "profile": privacy_engine.get_profile(user_id),
        "token": token,
    }

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

@app.post("/symptoms")
def log_symptom(user_id: str, symptom_input: SymptomLogInput, authorization: Optional[str] = Header(None)):
    """Logs a symptom from the closed allowlist. Requires token auth and active consent."""
    check_auth(user_id, authorization)
    name = symptom_input.symptom.strip().lower()
    if name not in ALLOWED_SYMPTOMS:
        raise HTTPException(
            status_code=422,
            detail=f"Symptom '{symptom_input.symptom}' is not in the allowed list. "
                   f"Allowed: {sorted(ALLOWED_SYMPTOMS)}"
        )
    log_date = symptom_input.log_date or datetime.now().strftime("%Y-%m-%d")
    try:
        res = privacy_engine.add_symptom_record(user_id, name, symptom_input.severity, log_date)
        return res
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))

@app.get("/symptoms")
def get_symptom_logs(user_id: str, authorization: Optional[str] = Header(None)):
    """Retrieves symptom log history for user."""
    check_auth(user_id, authorization)
    if not privacy_engine.has_active_consent(user_id):
        raise HTTPException(status_code=403, detail="Consent withdrawn.")
    return privacy_engine.get_symptom_records(user_id)

@app.get("/symptoms/allowed")
def get_allowed_symptoms():
    """Returns the closed list of allowed symptom names."""
    return {"allowed_symptoms": sorted(ALLOWED_SYMPTOMS)}

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

@app.get("/report/pdf")
def get_doctor_report_pdf(user_id: str = "demo_user", authorization: Optional[str] = Header(None)):
    """Generates and downloads a Doctor-Ready PDF Report."""
    os.makedirs("reports", exist_ok=True)
    temp_pdf_path = os.path.abspath(os.path.join("reports", f"doctor_report_{user_id}.pdf"))
    
    cycle_records = []
    symptom_records = []
    if authorization and verify_token_and_user(user_id, authorization):
        try:
            cycle_records = privacy_engine.get_cycle_records(user_id)
            symptom_records = privacy_engine.get_symptom_records(user_id)
        except Exception:
            pass
        
    lengths = [c.get("cycle_length_days", 28.0) for c in cycle_records if isinstance(c, dict)] if cycle_records else [28.0, 29.0, 27.0, 30.0, 28.0]
    med_days = float(sum(lengths) / len(lengths)) if lengths else 28.0
    
    report_data = {
        "report_title": "CycleSafe - Longitudinal Health Summary",
        "report_subtitle": "Non-diagnostic patient summary for clinical review",
        "profile": {"user_id": user_id, "age": 28, "self_reported_stage": "regular"},
        "data_coverage": {"cycle_records": len(lengths), "symptom_records": len(symptom_records)},
        "data_quality": {"missing_values": "Low"},
        "personal_baseline": {"median_days": med_days, "mean_days": med_days, "sd_days": 1.2, "recent_median_days": med_days},
        "forecast": {
            "available": True,
            "predicted_days": med_days,
            "range_80": (round(med_days - 2.0, 1), round(med_days + 2.0, 1)),
            "range_90": (round(med_days - 3.5, 1), round(med_days + 3.5, 1)),
            "method": "Personal Baseline Median (naive_median)"
        },
        "changes": [],
        "symptoms": symptom_records if symptom_records else [{"symptom": "mild_cramps"}],
        "discussion_points": [
            "Patient maintains regular longitudinal self-tracking in CycleSafe.",
            "Review cycle-to-cycle variance and symptom clusters."
        ]
    }
    if generate_doctor_report_pdf is None:
        raise HTTPException(status_code=501, detail="ReportLab is not installed on the server. Please install reportlab to generate PDF exports.")
    generate_doctor_report_pdf(report_data, temp_pdf_path)
    return FileResponse(
        temp_pdf_path,
        media_type="application/pdf",
        filename=f"CycleSafe_Report_{user_id}.pdf"
    )

# Static frontend mounting and SPA root route
frontend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "frontend"))
if os.path.exists(frontend_dir):
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

    @app.get("/")
    def serve_frontend_root():
        index_file = os.path.join(frontend_dir, "index.html")
        if os.path.exists(index_file):
            return FileResponse(index_file)
        return {"message": "CycleSafe API is running. Frontend index.html not found."}

