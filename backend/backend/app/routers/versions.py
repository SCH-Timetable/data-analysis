"""
Schedule version endpoints.

GET    /api/versions              → list all versions
GET    /api/versions/{id}         → one version
POST   /api/versions              → create a new draft
POST   /api/versions/{id}/publish → publish a draft
POST   /api/versions/{id}/archive → archive a published version
DELETE /api/versions/{id}         → delete a draft
"""

from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
from app.models.schema import ScheduleVersion
from app.data_store import VERSIONS
from app.database import delete_version, save_version

router = APIRouter()


@router.get('', response_model=list[ScheduleVersion])
def list_versions():
    return VERSIONS


@router.get('/{version_id}', response_model=ScheduleVersion)
def get_version(version_id: str):
    v = next((v for v in VERSIONS if v.id == version_id), None)
    if v is None:
        raise HTTPException(status_code=404, detail=f"Version '{version_id}' not found")
    return v


@router.post('', response_model=ScheduleVersion, status_code=201)
def create_version(label: str, author: str = 'Scheduler'):
    new_id = f"v{len(VERSIONS) + 1}"
    latest_conflicts = next((v.conflicts for v in VERSIONS if v.status == 'draft'), 0)
    new_version = ScheduleVersion(
        id=new_id,
        label=label,
        status='draft',
        timestamp=datetime.now(timezone.utc).isoformat(),
        author=author,
        changes=0,
        conflicts=latest_conflicts,
    )
    VERSIONS.insert(0, new_version)
    save_version(new_version)
    return new_version


@router.post('/{version_id}/publish', response_model=ScheduleVersion)
def publish_version(version_id: str):
    idx = next((i for i, v in enumerate(VERSIONS) if v.id == version_id), None)
    if idx is None:
        raise HTTPException(status_code=404, detail=f"Version '{version_id}' not found")
    v = VERSIONS[idx]
    if v.status != 'draft':
        raise HTTPException(status_code=409, detail=f"Version '{version_id}' is not a draft")
    # Archive existing published version
    for i, existing in enumerate(VERSIONS):
        if existing.status == 'published':
            VERSIONS[i] = existing.model_copy(update={'status': 'archived'})
            save_version(VERSIONS[i])
    VERSIONS[idx] = v.model_copy(
        update={'status': 'published',
                'timestamp': datetime.now(timezone.utc).isoformat()}
    )
    save_version(VERSIONS[idx])
    return VERSIONS[idx]


@router.post('/{version_id}/archive', response_model=ScheduleVersion)
def archive_version(version_id: str):
    idx = next((i for i, v in enumerate(VERSIONS) if v.id == version_id), None)
    if idx is None:
        raise HTTPException(status_code=404, detail=f"Version '{version_id}' not found")
    VERSIONS[idx] = VERSIONS[idx].model_copy(update={'status': 'archived'})
    save_version(VERSIONS[idx])
    return VERSIONS[idx]


@router.delete('/{version_id}')
def delete_version(version_id: str):
    original_len = len(VERSIONS)
    matching = next((v for v in VERSIONS if v.id == version_id), None)
    if matching is None:
        raise HTTPException(status_code=404, detail=f"Version '{version_id}' not found")
    if matching.status != 'draft':
        raise HTTPException(status_code=409, detail='Only draft versions can be deleted')
    VERSIONS[:] = [v for v in VERSIONS if v.id != version_id]
    delete_version(version_id)
    return {'ok': True, 'deleted': version_id}
