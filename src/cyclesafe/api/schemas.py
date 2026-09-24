"""Pydantic schemas for CycleSafe API."""

from typing import List, Optional
from pydantic import BaseModel, Field

class ConsentRequest(BaseModel):
    user_id: str
    consent_given: bool = True

class CycleLogInput(BaseModel):
    cycle_length_days: float = Field(..., ge=15, le=90, description="Cycle length in days (15-90)")
    log_date: Optional[str] = Field(None, description="Cycle log date (YYYY-MM-DD)")
    last_period_date: Optional[str] = Field(None, description="Last period start date (YYYY-MM-DD)")
    pain_score: int = Field(0, ge=0, le=3)
    bleeding_heaviness: int = Field(0, ge=0, le=3)
    bleeding_days: int = Field(0, ge=0, le=7)
    heavy_soaking_hourly: bool = Field(False, description="Soaking a pad/tampon every hour for several hours")
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
