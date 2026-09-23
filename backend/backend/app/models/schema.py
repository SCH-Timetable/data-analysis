"""
Pydantic models that mirror the TypeScript types in the frontend.

Frontend file → Python model(s):
  data.ts        → Session, Conflict, Alternative, ConflictType, ViewMode
  roomsData.ts   → Room, ClosureWindow, RoomType, AccessTag, EquipmentItem
  LoginScreen.tsx → LoginRequest, LoginResponse
  App.tsx         → ScheduleVersion
  StudentPortal.tsx → StudentSession, Credit
"""

from __future__ import annotations
from typing import Literal, Optional
from pydantic import BaseModel, Field


# ── Shared enumerations ────────────────────────────────────────────────────────

ViewMode      = Literal["rooms", "labs", "staff"]
ConflictType  = Literal["double_booking", "capacity", "staff_overlap", "equipment", "student_group", "room_type", "closure"]
Severity      = Literal["hard", "soft"]
RoomStatus    = Literal["Available", "Maintenance", "Closed"]
VersionStatus = Literal["draft", "published", "archived"]

RoomType = Literal[
    "Lecture Theatre", "Seminar Room", "Computer Lab",
    "Science Lab", "Studio", "Workshop"
]

AccessTag = Literal[
    "Wheelchair Access", "Hearing Loop", "Braille Signage",
    "Elevator Access", "Accessible WC Nearby", "Level Access"
]

EquipmentItem = Literal[
    "Projector (4K)", "Smartboard", "Document Camera", "PA System",
    "Video Conferencing", "Whiteboards", "PC Workstations", "Mac Workstations",
    "Oscilloscopes", "Fume Hoods", "3D Printers", "Laser Cutters",
    "Recording Studio Gear", "Microscopes", "Centrifuges", "Spectrometers"
]

UserRole = Literal["admin", "lecturer", "student"]


# ── Auth ───────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: str
    password: str

class LoginResponse(BaseModel):
    role: UserRole
    token: str          # JWT or opaque session token
    display_name: str


# ── Timetable / Session ────────────────────────────────────────────────────────

class ConflictCell(BaseModel):
    row: str            # room / lab / staff name
    day: int            # 0-4 (Mon-Fri)
    slot: int           # 0-9 (08:00-17:00)

class Alternative(BaseModel):
    id: str
    score: int          # 0-100 fitness score
    day: int
    slot: int
    room: str
    reasons: list[str]

class Conflict(BaseModel):
    id: str
    type: ConflictType
    severity: Severity
    description: str
    cell: ConflictCell
    alternatives: list[Alternative]

class Session(BaseModel):
    id: str
    code: str           # e.g. "CS301"
    name: str           # e.g. "Algorithms"
    staff: str
    group: str          # student group, e.g. "CS-3A"
    capacity: int
    enrolled: int
    color: str          # hex colour for the cell
    conflict_id: Optional[str] = Field(None, alias="conflictId")

    class Config:
        populate_by_name = True

# Grid: { view_mode → { row_label → { day_index → Session | null } } }
# Serialised as dict of dicts in the response (None = empty slot).
TimetableGrid = dict[str, dict[str, dict[int, Optional[Session]]]]


# ── Rooms ──────────────────────────────────────────────────────────────────────

class ClosureWindow(BaseModel):
    label: str
    from_date: str = Field(..., alias="from")   # ISO date string
    to_date: str   = Field(..., alias="to")
    reason: str

    class Config:
        populate_by_name = True

class Room(BaseModel):
    id: str
    name: str
    building: str
    floor: int
    type: RoomType
    capacity: int
    exam_capacity: int   = Field(..., alias="examCapacity")
    accessibility: list[AccessTag]
    equipment: list[EquipmentItem]
    closures: list[ClosureWindow]
    status: RoomStatus
    booking_rate: int    = Field(..., alias="bookingRate")   # % utilisation
    notes: str

    class Config:
        populate_by_name = True


# ── Schedule versions ──────────────────────────────────────────────────────────

class ScheduleVersion(BaseModel):
    id: str
    label: str              # e.g. "v2.3 — Spring 2026"
    status: VersionStatus
    timestamp: str          # ISO datetime string
    author: str
    changes: int            # number of changes vs previous version
    conflicts: int          # unresolved conflict count


# ── Analytics ─────────────────────────────────────────────────────────────────

class UtilizationPoint(BaseModel):
    name: str       # e.g. room name, day abbreviation, or hour string
    utilization: int

class ConflictStat(BaseModel):
    name: str
    value: int
    color: str

class AnalyticsSummary(BaseModel):
    total_sessions: int
    total_conflicts: int
    avg_utilization: float
    rooms_at_capacity: int
    utilization_by_room: list[UtilizationPoint]
    utilization_by_day: list[UtilizationPoint]
    utilization_by_hour: list[UtilizationPoint]
    conflict_breakdown: list[ConflictStat]


# ── Student portal ─────────────────────────────────────────────────────────────

class StudentSession(BaseModel):
    id: str
    code: str
    name: str
    staff: str
    room: str
    day: int            # 0-4
    slot: int           # 0-9
    color: str

class Credit(BaseModel):
    code: str
    name: str
    credits: int
    grade: Optional[str]
    status: Literal["completed", "in_progress", "planned"]

class StudentProfile(BaseModel):
    id: str
    name: str
    group: str
    programme: str
    year: int
    sessions: list[StudentSession]
    credits: list[Credit]
    total_credits_required: int
    total_credits_earned: int


# ── Apply-alternative request ─────────────────────────────────────────────────

class ApplyAlternativeRequest(BaseModel):
    conflict_id: str
    alternative_id: str
