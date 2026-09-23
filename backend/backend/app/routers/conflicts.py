"""
Conflict endpoints.

GET  /api/conflicts                  → list all unresolved conflicts
GET  /api/conflicts/{id}             → one conflict with alternatives
POST /api/conflicts/{id}/apply       → apply an alternative (resolves the conflict)
DELETE /api/conflicts/{id}           → dismiss / ignore a conflict
"""

from fastapi import APIRouter, HTTPException
from app.models.schema import Conflict, ApplyAlternativeRequest
from app.data_store import CONFLICTS, TIMETABLE
from app.database import save_setting, save_timetable_cell

router = APIRouter()


@router.get('', response_model=list[Conflict])
def list_conflicts():
    return CONFLICTS


@router.get('/{conflict_id}', response_model=Conflict)
def get_conflict(conflict_id: str):
    c = next((c for c in CONFLICTS if c.id == conflict_id), None)
    if c is None:
        raise HTTPException(status_code=404, detail=f"Conflict '{conflict_id}' not found")
    return c


@router.post('/{conflict_id}/apply')
def apply_alternative(conflict_id: str, body: ApplyAlternativeRequest):
    """
    Apply an alternative resolution for a conflict.
    Moves the affected session to the new slot and removes the conflict.
    """
    c = next((c for c in CONFLICTS if c.id == conflict_id), None)
    if c is None:
        raise HTTPException(status_code=404, detail=f"Conflict '{conflict_id}' not found")

    alt = next((a for a in c.alternatives if a.id == body.alternative_id), None)
    if alt is None:
        raise HTTPException(status_code=404, detail=f"Alternative '{body.alternative_id}' not found")

    # Find the session in the timetable and move it
    old_row = c.cell.row
    old_day = c.cell.day

    for view_data in TIMETABLE.values():
        if old_row in view_data and old_day in view_data[old_row]:
            session = view_data[old_row][old_day]
            if session:
                # Clear old slot
                view_data[old_row][old_day] = None
                save_timetable_cell('rooms' if 'LT' in old_row or 'SEM' in old_row else 'staff', old_row, old_day, None)
                # Set new slot (in the target room for the rooms view)
                new_row = alt.room if 'LT' in alt.room or 'SEM' in alt.room else old_row
                if new_row in view_data:
                    view_data[new_row][alt.day] = session.model_copy(
                        update={'conflict_id': None}
                    )
                    save_timetable_cell('rooms' if 'LT' in new_row or 'SEM' in new_row else 'staff', new_row, alt.day, view_data[new_row][alt.day])

    # Remove conflict from list
    CONFLICTS[:] = [x for x in CONFLICTS if x.id != conflict_id]
    save_setting('conflicts', [c.model_dump(by_alias=True) for c in CONFLICTS])

    return {'ok': True, 'applied_alternative': alt.id, 'conflict_removed': conflict_id}


@router.delete('/{conflict_id}')
def dismiss_conflict(conflict_id: str):
    original_len = len(CONFLICTS)
    CONFLICTS[:] = [c for c in CONFLICTS if c.id != conflict_id]
    if len(CONFLICTS) == original_len:
        raise HTTPException(status_code=404, detail=f"Conflict '{conflict_id}' not found")
    save_setting('conflicts', [c.model_dump(by_alias=True) for c in CONFLICTS])
    return {'ok': True, 'dismissed': conflict_id}
