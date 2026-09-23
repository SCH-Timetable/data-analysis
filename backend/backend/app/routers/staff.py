"""
Staff endpoints (mirrors Manage staff modal in the frontend).

GET /api/staff              → list staff names
POST /api/staff             → add staff {name}
DELETE /api/staff/{name}    → remove staff (sessions become Unassigned)
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.data_store import DAYS, STAFF, TIMETABLE
from app.database import save_setting, save_timetable_row

router = APIRouter()


class StaffCreate(BaseModel):
    name: str


@router.get('')
def list_staff():
    return STAFF


@router.post('', status_code=201)
def add_staff(body: StaffCreate):
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail='name is required')
    if name not in STAFF:
        STAFF.append(name)
        TIMETABLE.setdefault('staff', {})[name] = {d: None for d in range(len(DAYS))}
        save_setting('staff', STAFF)
        save_timetable_row('staff', name, TIMETABLE['staff'][name])
    return {'ok': True, 'name': name, 'staff': STAFF}


@router.delete('/{name}')
def remove_staff(name: str):
    if name not in STAFF:
        raise HTTPException(status_code=404, detail=f"Staff '{name}' not found")
    STAFF[:] = [s for s in STAFF if s != name]
    staff_view = TIMETABLE.get('staff', {})
    staff_view.pop(name, None)
    save_setting('staff', STAFF)
    for view_data in TIMETABLE.values():
        for row_days in view_data.values():
            for day, sess in list(row_days.items()):
                if sess is not None and sess.staff == name:
                    row_days[day] = sess.model_copy(update={'staff': 'Unassigned'})
    return {'ok': True, 'deleted': name, 'staff': STAFF}
