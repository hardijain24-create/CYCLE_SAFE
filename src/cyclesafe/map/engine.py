"""CycleSafe Product Access Map Module.

Implements access point listings, distance sorting, filters,
anonymous check-ins (majority voting of last 3 reports), device rate-limiting,
product allowlist validation, and anti-tampering verification rules.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional, Set
import math
import re

ALLOWED_PRODUCTS = {"sanitary_pads", "tampons", "pain_relief", "menstrual_cups", "wipes"}

@dataclass
class AccessPoint:
    id: str
    name: str
    city: str
    country: str
    latitude: float
    longitude: float
    category: str               # e.g., 'transit_station', 'university', 'community_center'
    status: str                 # 'stocked', 'low', 'empty'
    products: List[str]         # e.g., ['sanitary_pads', 'tampons', 'pain_relief']
    is_free: bool
    last_checked: datetime
    report_count: int = 1
    is_demo: bool = True
    recent_reports: List[str] = field(default_factory=list) # max 3 recent statuses
    contributing_tokens: Set[str] = field(default_factory=set)
    contributing_ips: Set[str] = field(default_factory=set)

    def to_dict(self, user_lat: Optional[float] = None, user_lon: Optional[float] = None) -> Dict:
        now = datetime.now(timezone.utc)
        hours_ago = (now - self.last_checked).total_seconds() / 3600.0
        
        display_status = self.status
        if hours_ago > 72:
            display_status = "unverified (last checked > 72h ago)"

        distance_km = None
        if user_lat is not None and user_lon is not None:
            distance_km = round(haversine_distance(user_lat, user_lon, self.latitude, self.longitude), 2)

        return {
            "id": self.id,
            "name": self.name,
            "city": self.city,
            "country": self.country,
            "category": self.category,
            "status": display_status,
            "products": self.products,
            "is_free": self.is_free,
            "last_checked": self.last_checked.isoformat(),
            "last_checked_hours_ago": round(hours_ago, 1),
            "report_count": self.report_count,
            "is_demo": self.is_demo,
            "data_label": "Prototype Data" if self.is_demo else "Verified Community Data",
            "distance_km": distance_km
        }

def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0 # Earth radius in kilometers
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def sanitize_note(note: Optional[str]) -> Optional[str]:
    if not note:
        return None
    # Strip HTML tags and cap length at 100 chars
    clean = re.sub(r'<[^>]*>', '', str(note)).strip()
    return clean[:100] if clean else None

class ProductAccessMapEngine:
    def __init__(self):
        self.access_points: Dict[str, AccessPoint] = {}
        self.device_checkin_history: Dict[str, datetime] = {}
        self.ip_checkin_history: Dict[str, List[datetime]] = {}
        self._seed_demo_data()

    def _seed_demo_data(self):
        now = datetime.now(timezone.utc)
        demo_points = [
            AccessPoint("loc_01", "Dadar Central Station Restroom", "Mumbai", "India", 19.0178, 72.8478, "transit_station", "low", ["sanitary_pads"], True, now - timedelta(hours=4), 1, True, ["low"], set(), set()),
            AccessPoint("loc_02", "IIT Bombay Student Center", "Mumbai", "India", 19.1334, 72.9133, "university", "stocked", ["sanitary_pads", "tampons", "pain_relief"], True, now - timedelta(hours=12), 1, True, ["stocked"], set(), set()),
            AccessPoint("loc_03", "Churchgate Station Community Desk", "Mumbai", "India", 18.9322, 72.8264, "transit_station", "empty", [], True, now - timedelta(hours=85), 1, True, ["empty"], set(), set()),
            AccessPoint("loc_04", "Connaught Place Public Restroom", "New Delhi", "India", 28.6315, 77.2167, "public_restroom", "stocked", ["sanitary_pads"], True, now - timedelta(hours=2), 1, True, ["stocked"], set(), set()),
            AccessPoint("loc_05", "Koramangala Community Health Hub", "Bengaluru", "India", 12.9352, 77.6245, "community_center", "stocked", ["sanitary_pads", "tampons"], True, now - timedelta(hours=1), 1, True, ["stocked"], set(), set()),
        ]
        for ap in demo_points:
            self.access_points[ap.id] = ap

    def get_nearby(self, lat: float, lon: float, radius_km: float = 20.0, 
                   free_only: bool = False, product_filter: Optional[str] = None) -> List[Dict]:
        results = []
        for ap in self.access_points.values():
            if free_only and not ap.is_free:
                continue
            if product_filter and product_filter not in ap.products:
                continue
            dist = haversine_distance(lat, lon, ap.latitude, ap.longitude)
            if dist <= radius_km:
                d = ap.to_dict(user_lat=lat, user_lon=lon)
                results.append(d)
        
        results.sort(key=lambda x: x["distance_km"])
        return results

    def submit_checkin(self, device_token: str, location_id: str = "", 
                       status: str = "", products: List[str] = None, note: Optional[str] = None, client_ip: str = "127.0.0.1") -> Dict:
        """Anonymous check-in with rate limiting, input validation, and multi-IP verification."""
        if products is None:
            products = []
        if not device_token or device_token.strip() == "":
            return {"status": "error", "message": "Missing device token header."}

        if status not in ["stocked", "low", "empty"]:
            return {"status": "error", "message": "Invalid status value. Must be 'stocked', 'low', or 'empty'."}

        if location_id not in self.access_points:
            return {"status": "error", "message": "Location ID not found."}

        # Validate products against allowlist
        invalid = [p for p in products if p not in ALLOWED_PRODUCTS]
        if invalid:
            return {"status": "error", "message": f"Invalid products: {invalid}. Must be in allowlist."}

        now = datetime.now(timezone.utc)

        # Per-IP rate limiting: max 3 checkins per IP within 10 minutes
        ip_history = self.ip_checkin_history.get(client_ip, [])
        recent_ip_checkins = [t for t in ip_history if (now - t).total_seconds() < 600]
        if len(recent_ip_checkins) >= 3:
            return {
                "status": "error",
                "message": "IP rate limit exceeded. Max 3 check-ins per IP every 10 minutes."
            }

        # Per-device token rate limiting
        if device_token in self.device_checkin_history:
            last_sub = self.device_checkin_history[device_token]
            if (now - last_sub).total_seconds() < 600: # 10 minutes
                return {
                    "status": "error",
                    "message": "Device rate limit exceeded. Please wait 10 minutes between check-ins."
                }

        recent_ip_checkins.append(now)
        self.ip_checkin_history[client_ip] = recent_ip_checkins
        self.device_checkin_history[device_token] = now
        ap = self.access_points[location_id]

        clean_note = sanitize_note(note)

        # Update recent reports list (keep max 3)
        ap.recent_reports.append(status)
        if len(ap.recent_reports) > 3:
            ap.recent_reports.pop(0)

        # Majority voting of last 3 reports (most recent report breaks ties)
        status_counts = {}
        for s in reversed(ap.recent_reports):
            status_counts[s] = status_counts.get(s, 0) + 1
        majority_status = max(reversed(ap.recent_reports), key=lambda s: status_counts[s])

        ap.status = majority_status
        ap.products = products
        ap.last_checked = now
        ap.report_count += 1
        ap.contributing_tokens.add(device_token)
        ap.contributing_ips.add(client_ip)

        # Anti-tampering: Requires >= 3 reports from >= 2 distinct tokens AND >= 3 distinct IPs before is_demo = False
        if ap.report_count >= 3 and len(ap.contributing_tokens) >= 2 and len(ap.contributing_ips) >= 3:
            ap.is_demo = False

        return {
            "status": "success",
            "message": "Check-in recorded anonymously.",
            "updated_location": ap.to_dict(),
            "note_saved": clean_note
        }

def test_map():
    engine = ProductAccessMapEngine()
    mumbai_lat, mumbai_lon = 19.0760, 72.8777
    nearby = engine.get_nearby(mumbai_lat, mumbai_lon, radius_km=20.0)
    assert len(nearby) == 3

    # Checkin test token 1 from IP 1
    res1 = engine.submit_checkin("dev_token_01", "192.168.1.1", "loc_01", "stocked", ["sanitary_pads", "tampons"])
    assert res1["status"] == "success"
    assert res1["updated_location"]["is_demo"] == True

    # Token rotation attack from SAME IP: 4 rotating tokens from 1 IP
    for i in range(2, 5):
        tok = f"dev_token_0{i}"
        res = engine.submit_checkin(tok, "192.168.1.1", "loc_01", "empty", ["sanitary_pads"])
        # Should be rejected or blocked due to per-IP rate limit (max 3 per IP) or keep is_demo = True
        if res["status"] == "success":
            assert res["updated_location"]["is_demo"] == True, "Token rotation attack from single IP must NOT set Verified status"

    print("ALL MAP TESTS PASSED")

if __name__ == "__main__":
    test_map()
