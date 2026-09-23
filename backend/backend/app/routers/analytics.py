"""
Analytics endpoints.

GET /api/analytics/summary           → aggregate stats (matches AnalyticsScreen.tsx)
GET /api/analytics/utilization/rooms → per-room utilization
GET /api/analytics/utilization/days  → per-day utilization
GET /api/analytics/utilization/hours → per-hour utilization
GET /api/analytics/conflicts         → conflict type breakdown
"""

from fastapi import APIRouter
from app.data_store import TIMETABLE, CONFLICTS, ALL_ROOMS, DAYS, TIME_SLOTS
from app.models.schema import AnalyticsSummary, UtilizationPoint, ConflictStat

router = APIRouter()


def _room_utilization() -> list[UtilizationPoint]:
    """Utilization as % of sessions filled across all days."""
    rooms_view = TIMETABLE.get('rooms', {})
    result = []
    for room_name, days in rooms_view.items():
        total = len(days)
        filled = sum(1 for s in days.values() if s is not None)
        pct = round(filled / total * 100) if total else 0
        result.append(UtilizationPoint(name=room_name, utilization=pct))
    return sorted(result, key=lambda x: x.utilization, reverse=True)


def _day_utilization() -> list[UtilizationPoint]:
    """How many sessions happen on each weekday (rooms view)."""
    rooms_view = TIMETABLE.get('rooms', {})
    day_counts: dict[int, int] = {d: 0 for d in range(5)}
    total_rows = max(len(rooms_view), 1)
    for days in rooms_view.values():
        for day_idx, sess in days.items():
            if sess is not None:
                day_counts[day_idx] = day_counts.get(day_idx, 0) + 1
    return [
        UtilizationPoint(name=DAYS[d], utilization=round(cnt / total_rows * 100))
        for d, cnt in day_counts.items()
    ]


def _hour_utilization() -> list[UtilizationPoint]:
    """How busy each time slot is across all rooms."""
    rooms_view = TIMETABLE.get('rooms', {})
    slot_counts: dict[int, int] = {s: 0 for s in range(len(TIME_SLOTS))}
    total_rooms = max(len(rooms_view), 1)
    for days in rooms_view.values():
        for slot_idx, sess in days.items():
            if sess is not None:
                slot_counts[slot_idx] = slot_counts.get(slot_idx, 0) + 1
    return [
        UtilizationPoint(name=TIME_SLOTS[s], utilization=round(cnt / total_rooms * 100))
        for s, cnt in slot_counts.items()
    ]


def _conflict_breakdown() -> list[ConflictStat]:
    colours = {
        'double_booking': '#ef4444',
        'capacity':       '#f59e0b',
        'staff_overlap':  '#8b5cf6',
        'equipment':      '#06b6d4',
        'student_group':  '#10b981',
        'room_type':      '#f97316',
        'closure':        '#64748b',
    }
    counts: dict[str, int] = {}
    for c in CONFLICTS:
        counts[c.type] = counts.get(c.type, 0) + 1
    labels = {
        'double_booking': 'Double Booking',
        'capacity':       'Capacity',
        'staff_overlap':  'Staff Overlap',
        'equipment':      'Equipment',
        'student_group':  'Student Group',
        'room_type':      'Room Type',
        'closure':        'Closure',
    }
    return [
        ConflictStat(name=labels.get(t, t), value=v, color=colours.get(t, '#94a3b8'))
        for t, v in counts.items()
    ]


def _total_sessions() -> int:
    return sum(
        1
        for rows in TIMETABLE.values()
        for days in rows.values()
        for s in days.values()
        if s is not None
    )


def _rooms_at_capacity() -> int:
    rooms_view = TIMETABLE.get('rooms', {})
    count = 0
    for days in rooms_view.values():
        for s in days.values():
            if s and s.enrolled >= s.capacity:
                count += 1
    return count


@router.get('/summary', response_model=AnalyticsSummary)
def get_summary():
    room_util = _room_utilization()
    avg_util = round(sum(p.utilization for p in room_util) / len(room_util)) if room_util else 0
    return AnalyticsSummary(
        total_sessions=_total_sessions(),
        total_conflicts=len(CONFLICTS),
        avg_utilization=avg_util,
        rooms_at_capacity=_rooms_at_capacity(),
        utilization_by_room=room_util,
        utilization_by_day=_day_utilization(),
        utilization_by_hour=_hour_utilization(),
        conflict_breakdown=_conflict_breakdown(),
    )


@router.get('/utilization/rooms', response_model=list[UtilizationPoint])
def util_by_room():
    return _room_utilization()


@router.get('/utilization/days', response_model=list[UtilizationPoint])
def util_by_day():
    return _day_utilization()


@router.get('/utilization/hours', response_model=list[UtilizationPoint])
def util_by_hour():
    return _hour_utilization()


@router.get('/conflicts', response_model=list[ConflictStat])
def conflict_stats():
    return _conflict_breakdown()
