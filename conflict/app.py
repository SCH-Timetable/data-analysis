# Local API server for SCH conflict engine — run: uvicorn app:app --reload --port 5000
# Open in browser: http://localhost:5000/docs
# Path: sch-chatbot-starter/backend-contract/app.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
from conflict_engine import check_move, recommend_alternatives

app = FastAPI(title="SCH Timetable Conflict API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

# ---- Mock DB (same shape as mockData.js) ----
DAYS = [{"id": 1, "day_name": "Sunday"}, {"id": 2, "day_name": "Monday"},
        {"id": 3, "day_name": "Tuesday"}, {"id": 4, "day_name": "Wednesday"},
        {"id": 5, "day_name": "Thursday"}]
SLOTS = [{"id": 1, "start_time": "09:00", "end_time": "11:00"},
         {"id": 2, "start_time": "11:00", "end_time": "13:00"},
         {"id": 3, "start_time": "13:00", "end_time": "15:00"},
         {"id": 4, "start_time": "15:00", "end_time": "17:00"}]
ROOMS = [{"id": 1, "room_number": "A101", "capacity": 60, "room_type": "classroom"},
         {"id": 2, "room_number": "A102", "capacity": 40, "room_type": "classroom"},
         {"id": 3, "room_number": "Lab 2", "capacity": 30, "room_type": "lab"},
         {"id": 4, "room_number": "B203", "capacity": 80, "room_type": "classroom"}]
STAFF = [{"id": 1, "first_name": "Ahmed", "last_name": "Hassan"},
         {"id": 2, "first_name": "Sara", "last_name": "Ali"}]
ALLOCATIONS = [
    {"id": 1, "section_id": 1, "staff_id": 1, "room_id": 1, "day_id": 2, "time_slot_id": 1},
    {"id": 2, "section_id": 2, "staff_id": 1, "room_id": 3, "day_id": 2, "time_slot_id": 2},
    {"id": 3, "section_id": 3, "staff_id": 2, "room_id": 4, "day_id": 3, "time_slot_id": 2},
]

def build_ctx():
    return {
        "allocations": ALLOCATIONS, "rooms": ROOMS, "days": DAYS, "slots": SLOTS, "staff": STAFF,
        "closures": [{"room_id": 3, "day_id": 3, "time_slot_id": 1}],
        "availability": [{"staff_id": 1, "day_id": 3, "time_slot_id": 2}],
        "roomEquipment": [{"room_id": 3, "equipment_id": 1, "quantity": 25}],
        "section_groups": [{"section_id": 1, "student_group_id": 1},
                           {"section_id": 2, "student_group_id": 1},
                           {"section_id": 3, "student_group_id": 1}],
        "groupSizes": {1: 55}, "holidays": [],
    }

# ---- Schemas (match openapi-conflict.yaml) ----
class CheckMoveRequest(BaseModel):
    section_id: int
    staff_id: int
    room_id: int
    day_id: int
    time_slot_id: int
    exclude_allocation_id: Optional[int] = None
    required_equipment_id: Optional[int] = None
    room_type_required: Optional[str] = None
    duration_slots: int = 1

@app.get("/")
def root():
    return {"ok": True, "docs": "http://localhost:5000/docs"}

@app.post("/api/allocations/check")
def check(req: CheckMoveRequest):
    ctx = build_ctx()
    res = check_move(req.model_dump(), ctx)
    recs = [] if res["ok"] else recommend_alternatives(req.model_dump(), ctx, 3)
    return {"ok": res["ok"], "conflicts": res["conflicts"], "recommendations": recs}

@app.get("/api/timetable")
def timetable(staff_id: Optional[int] = None, day_id: Optional[int] = None):
    rows = ALLOCATIONS
    if staff_id: rows = [a for a in rows if a["staff_id"] == staff_id]
    if day_id: rows = [a for a in rows if a["day_id"] == day_id]
    return rows

@app.get("/api/analytics/occupancy")
def occupancy():
    total = len(DAYS) * len(SLOTS)
    out = []
    for r in ROOMS:
        used = len([a for a in ALLOCATIONS if a["room_id"] == r["id"]])
        out.append({"room_id": r["id"], "room_number": r["room_number"],
                    "used": used, "total": total, "pct": round(used/total*100) if total else 0})
    return sorted(out, key=lambda x: -x["pct"])
