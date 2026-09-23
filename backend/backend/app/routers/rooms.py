"""
Room endpoints.

GET  /api/rooms                      → list all rooms (supports ?type=&status=&building=)
GET  /api/rooms/{id}                 → one room
PUT  /api/rooms/{id}                 → update room (status, notes, bookingRate, …)
GET  /api/rooms/buildings            → list of building names
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from app.models.schema import Room, RoomStatus, RoomType
from app.data_store import ALL_ROOMS
from app.database import delete_room, save_room

router = APIRouter()


@router.get('/buildings')
def get_buildings():
    return list({r.building for r in ALL_ROOMS})


@router.post('', response_model=Room, status_code=201)
def create_room(room_data: dict):
    room = Room(id=f"r{len(ALL_ROOMS) + 1}", **room_data)
    ALL_ROOMS.append(room)
    save_room(room)
    return room


@router.get('', response_model=list[Room])
def list_rooms(
    type_filter: Optional[str]   = Query(None, alias='type'),
    status:      Optional[RoomStatus] = None,
    building:    Optional[str]   = None,
    q:           Optional[str]   = None,   # search by name
):
    rooms = ALL_ROOMS
    if type_filter:
        rooms = [r for r in rooms if r.type == type_filter]
    if status:
        rooms = [r for r in rooms if r.status == status]
    if building:
        rooms = [r for r in rooms if building.lower() in r.building.lower()]
    if q:
        rooms = [r for r in rooms if q.lower() in r.name.lower()]
    return rooms


@router.get('/{room_id}', response_model=Room)
def get_room(room_id: str):
    room = next((r for r in ALL_ROOMS if r.id == room_id), None)
    if room is None:
        # also try by name
        room = next((r for r in ALL_ROOMS if r.name.lower() == room_id.lower()), None)
    if room is None:
        raise HTTPException(status_code=404, detail=f"Room '{room_id}' not found")
    return room


@router.put('/{room_id}', response_model=Room)
def update_room(room_id: str, updates: dict):
    idx = next((i for i, r in enumerate(ALL_ROOMS) if r.id == room_id), None)
    if idx is None:
        raise HTTPException(status_code=404, detail=f"Room '{room_id}' not found")
    existing = ALL_ROOMS[idx]
    updated = existing.model_copy(update=updates)
    ALL_ROOMS[idx] = updated
    save_room(updated)
    return updated


@router.delete('/{room_id}')
def delete_room(room_id: str):
    idx = next((i for i, r in enumerate(ALL_ROOMS) if r.id == room_id), None)
    if idx is None:
        raise HTTPException(status_code=404, detail=f"Room '{room_id}' not found")
    ALL_ROOMS.pop(idx)
    delete_room(room_id)
    return {'ok': True, 'deleted': room_id}
