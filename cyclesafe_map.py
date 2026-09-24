"""CycleSafe Product Access Map Module.

Implements access point listings, distance sorting, filters,
anonymous check-ins (majority voting of last 3 reports), device rate-limiting,
and prototype data flagging.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional
import math

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

class ProductAccessMapEngine:
    def __init__(self):
        self.access_points: Dict[str, AccessPoint] = {}
        self.device_checkin_history: Dict[str, datetime] = {}
        self._seed_demo_data()

    def _seed_demo_data(self):
        now = datetime.now(timezone.utc)
        demo_points = [
            AccessPoint("loc_01", "Dadar Central Station Restroom", "Mumbai", "India", 19.0178, 72.8478, "transit_station", "low", ["sanitary_pads"], True, now - timedelta(hours=4), 12, True, ["low"]),
            AccessPoint("loc_02", "IIT Bombay Student Center", "Mumbai", "India", 19.1334, 72.9133, "university", "stocked", ["sanitary_pads", "tampons", "pain_relief"], True, now - timedelta(hours=12), 25, True, ["stocked"]),
            AccessPoint("loc_03", "Churchgate Station Community Desk", "Mumbai", "India", 18.9322, 72.8264, "transit_station", "empty", [], True, now - timedelta(hours=85), 5, True, ["empty"]),
            AccessPoint("loc_04", "Connaught Place Public Restroom", "New Delhi", "India", 28.6315, 77.2167, "public_restroom", "stocked", ["sanitary_pads"], True, now - timedelta(hours=2), 18, True, ["stocked"]),
            AccessPoint("loc_05", "Koramangala Community Health Hub", "Bengaluru", "India", 12.9352, 77.6245, "community_center", "stocked", ["sanitary_pads", "tampons"], True, now - timedelta(hours=1), 30, True, ["stocked"]),
            AccessPoint("loc_06", "Hitec City Metro Station", "Hyderabad", "India", 17.4474, 78.3762, "transit_station", "stocked", ["sanitary_pads"], True, now - timedelta(hours=6), 14, True, ["stocked"]),
            AccessPoint("loc_07", "Park Street Metro Desk", "Kolkata", "India", 22.5539, 88.3531, "transit_station", "low", ["sanitary_pads"], True, now - timedelta(hours=18), 8, True, ["low"]),
            AccessPoint("loc_08", "Cyber Hub Wellness Center", "Gurugram", "India", 28.4950, 77.0895, "commercial_hub", "low", ["sanitary_pads", "pain_relief"], False, now - timedelta(hours=5), 10, True, ["low"]),
            AccessPoint("loc_09", "King's Cross Station Facility", "London", "UK", 51.5309, -0.1233, "transit_station", "stocked", ["sanitary_pads", "tampons"], True, now - timedelta(hours=3), 42, True, ["stocked"]),
            AccessPoint("loc_10", "Grand Central Terminal Restroom", "New York", "USA", 40.7527, -73.9772, "transit_station", "stocked", ["sanitary_pads", "tampons"], True, now - timedelta(hours=10), 55, True, ["stocked"]),
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
        
        # Sort by distance
        results.sort(key=lambda x: x["distance_km"])
        return results

    def submit_checkin(self, device_token: str, location_id: str, 
                       status: str, products: List[str], note: Optional[str] = None) -> Dict:
        """Anonymous check-in. Rate-limited per device token (1 per 10 mins)."""
        if status not in ["stocked", "low", "empty"]:
            return {"status": "error", "message": "Invalid status value. Must be 'stocked', 'low', or 'empty'."}

        if location_id not in self.access_points:
            return {"status": "error", "message": "Location ID not found."}

        now = datetime.now(timezone.utc)
        if device_token in self.device_checkin_history:
            last_sub = self.device_checkin_history[device_token]
            if (now - last_sub).total_seconds() < 600: # 10 minutes
                return {
                    "status": "error",
                    "message": "Rate limit exceeded. Please wait 10 minutes between check-ins."
                }

        self.device_checkin_history[device_token] = now
        ap = self.access_points[location_id]

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
        # Once community checks in, mark as verified community data
        ap.is_demo = False

        return {
            "status": "success",
            "message": "Check-in recorded anonymously.",
            "updated_location": ap.to_dict()
        }

def test_map():
    engine = ProductAccessMapEngine()
    # Nearby test (Mumbai center)
    mumbai_lat, mumbai_lon = 19.0760, 72.8777
    nearby = engine.get_nearby(mumbai_lat, mumbai_lon, radius_km=20.0)
    assert len(nearby) == 3
    assert nearby[0]["id"] == "loc_01" # Dadar (~7km)

    # Checkin test
    res = engine.submit_checkin("dev_token_123", "loc_01", "stocked", ["sanitary_pads", "tampons"])
    assert res["status"] == "success"
    assert res["updated_location"]["status"] == "stocked"
    assert res["updated_location"]["is_demo"] == False

    # Rate limit test
    res2 = engine.submit_checkin("dev_token_123", "loc_01", "empty", [])
    assert res2["status"] == "error"
    assert "Rate limit" in res2["message"]

    print("ALL MAP TESTS PASSED")

if __name__ == "__main__":
    test_map()
