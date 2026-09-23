"""
Timetable endpoints.

GET  /api/timetable                   → full grid (all view modes)
GET  /api/timetable/{view}            → grid for one view mode (rooms|labs|staff)
GET  /api/timetable/{view}/{row}      → one row (e.g. a single room or staff member)
PUT  /api/timetable/{view}/{row}/{day} → overwrite a day's slots for one row
GET  /api/timetable/constants         → DAYS, TIME_SLOTS, ROOMS, LABS, STAFF lists
"""

from fastapi import APIRouter, Header, HTTPException
from app.models.schema import Session, ViewMode
from app.data_store import TIMETABLE, DAYS, TIME_SLOTS, ROOMS, LABS, STAFF
from app.routers.auth import is_admin_authorization
from app.database import save_setting, save_timetable_cell, save_timetable_row

router = APIRouter()


@router.get('/constants')
def get_constants():
    return {
        'days': DAYS,
        'fullDays': ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday'],
        'timeSlots': TIME_SLOTS,
        'rooms': ROOMS,
        'labs': LABS,
        'staff': STAFF,
    }


@router.get('')
def get_full_grid():
    """Return the entire timetable (all view modes)."""
    return _serialize_grid(TIMETABLE)


@router.get('/{view}')
def get_view_grid(view: ViewMode):
    if view not in TIMETABLE:
        raise HTTPException(status_code=404, detail=f"View '{view}' not found")
    return _serialize_grid({view: TIMETABLE[view]})[view]


@router.post('/columns')
def create_column(payload: dict, authorization: str = Header(default='')):
    if not is_admin_authorization(authorization):
        raise HTTPException(status_code=403, detail='Only admins can create columns.')
    name = str(payload.get('name', '')).strip()
    if not name:
        raise HTTPException(status_code=422, detail='Column name is required.')
    if name in DAYS:
        raise HTTPException(status_code=400, detail=f"Column '{name}' already exists.")
    DAYS.append(name)
    new_day = len(DAYS) - 1
    for rows in TIMETABLE.values():
        for days in rows.values():
            days[new_day] = None
    save_setting('days', DAYS)
    for view, rows in TIMETABLE.items():
        for row_name, days in rows.items():
            save_timetable_cell(view, row_name, new_day, None)
    return {'ok': True, 'column': name, 'day': new_day}


@router.post('/{view}/rows')
def create_row(view: ViewMode, payload: dict, authorization: str = Header(default='')):
    if not is_admin_authorization(authorization):
        raise HTTPException(status_code=403, detail='Only admins can create rows.')
    name = str(payload.get('name', '')).strip()
    view_data = TIMETABLE.get(view)
    if view_data is None:
        raise HTTPException(status_code=404, detail=f"View '{view}' not found")
    if not name:
        raise HTTPException(status_code=422, detail='Row name is required.')
    if name in view_data:
        raise HTTPException(status_code=400, detail=f"Row '{name}' already exists.")
    view_data[name] = {day: None for day in range(len(DAYS))}
    if view == 'rooms' and name not in ROOMS:
        ROOMS.append(name)
    elif view == 'labs' and name not in LABS:
        LABS.append(name)
    elif view == 'staff' and name not in STAFF:
        STAFF.append(name)
    save_setting(view, {'rooms': ROOMS, 'labs': LABS, 'staff': STAFF}.get(view, STAFF))
    save_timetable_row(view, name, view_data[name])
    return {'ok': True, 'row': name}


@router.get('/{view}/{row}')
def get_row(view: ViewMode, row: str):
    view_data = TIMETABLE.get(view)
    if view_data is None:
        raise HTTPException(status_code=404, detail=f"View '{view}' not found")
    row_data = view_data.get(row)
    if row_data is None:
        raise HTTPException(status_code=404, detail=f"Row '{row}' not found in view '{view}'")
    return {str(day): (sess.model_dump(by_alias=True) if sess else None)
            for day, sess in row_data.items()}


@router.put('/{view}/{row}/{day}')
def update_slot(view: ViewMode, row: str, day: int, session: Session | None = None, authorization: str = Header(default='')):
    """Set (or clear) a single slot. Auto-creates the row for new staff."""
    if not is_admin_authorization(authorization):
        raise HTTPException(status_code=403, detail='Only admins can edit the timetable.')
    if day < 0 or day >= len(DAYS):
        raise HTTPException(status_code=422, detail=f'day must be 0-{len(DAYS) - 1}')
    view_data = TIMETABLE.get(view)
    if view_data is None:
        raise HTTPException(status_code=404, detail=f"View '{view}' not found")
    if row not in view_data:
        # allow admin to add new staff rows on the fly (mirrors Manage staff)
        if view == 'staff':
            view_data[row] = {d: None for d in range(5)}
            if row not in STAFF:
                STAFF.append(row)
        else:
            raise HTTPException(status_code=404, detail=f"Row '{row}' not found")
    view_data[row][day] = session
    save_timetable_cell(view, row, day, session)
    return {'ok': True, 'slot': session.model_dump(by_alias=True) if session else None}


# ── helpers ───────────────────────────────────────────────────────────────────

def _serialize_grid(grid: dict) -> dict:
    """Convert Session objects to dicts; keep None as null."""
    result = {}
    for view, rows in grid.items():
        result[view] = {}
        for row, days in rows.items():
            result[view][row] = {
                str(day): (sess.model_dump(by_alias=True) if sess else None)
                for day, sess in days.items()
            }
    return result
