"""MySQL persistence for the BUA scheduling API."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.types import JSON
from dotenv import load_dotenv

load_dotenv()


DATABASE_URL = os.getenv(
    'DATABASE_URL',
    'mysql+pymysql://root:password@127.0.0.1:3306/bua_project',
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class UserRow(Base):
    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(32))
    display_name: Mapped[str] = mapped_column(String(255))


class TimetableCellRow(Base):
    __tablename__ = 'timetable_cells'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    view: Mapped[str] = mapped_column(String(32))
    row_name: Mapped[str] = mapped_column(String(255))
    day_index: Mapped[int] = mapped_column(Integer)
    session_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    __table_args__ = (UniqueConstraint('view', 'row_name', 'day_index', name='uq_timetable_cell'),)


class RoomRow(Base):
    __tablename__ = 'rooms'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class StudentRow(Base):
    __tablename__ = 'students'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class ScheduleVersionRow(Base):
    __tablename__ = 'schedule_versions'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class SettingRow(Base):
    __tablename__ = 'schedule_settings'
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


def _dump_model(value: Any) -> dict[str, Any]:
    if hasattr(value, 'model_dump'):
        return value.model_dump(by_alias=True)
    return dict(value)


def _load_settings(db: Session, key: str, fallback: list[str]) -> list[str]:
    row = db.get(SettingRow, key)
    if row is None:
        return fallback
    return json.loads(row.value)


def initialize_database() -> None:
    """Create the schema, seed once, then load persisted state into compatibility objects."""
    Base.metadata.create_all(engine)
    from app import data_store

    with SessionLocal.begin() as db:
        if db.scalar(select(UserRow.id).limit(1)) is None:
            for user in data_store.USERS:
                db.add(UserRow(email=user['email'].lower(), password=user['password'], role=user['role'], display_name=user['name']))
        if db.scalar(select(RoomRow.id).limit(1)) is None:
            for room in data_store.ALL_ROOMS:
                db.add(RoomRow(id=room.id, payload=_dump_model(room)))
        if db.scalar(select(StudentRow.id).limit(1)) is None:
            for student in data_store.MANAGED_STUDENTS:
                db.add(StudentRow(id=student['id'], payload=dict(student)))
        if db.scalar(select(ScheduleVersionRow.id).limit(1)) is None:
            for version in data_store.VERSIONS:
                db.add(ScheduleVersionRow(id=version.id, payload=_dump_model(version)))
        if db.scalar(select(SettingRow).where(SettingRow.key == 'days')) is None:
            db.add(SettingRow(key='days', value=json.dumps(data_store.DAYS)))
        if db.scalar(select(SettingRow).where(SettingRow.key == 'time_slots')) is None:
            db.add(SettingRow(key='time_slots', value=json.dumps(data_store.TIME_SLOTS)))
        for key, values in (('rooms', data_store.ROOMS), ('labs', data_store.LABS), ('staff', data_store.STAFF)):
            if db.scalar(select(SettingRow).where(SettingRow.key == key)) is None:
                db.add(SettingRow(key=key, value=json.dumps(values)))
        if db.scalar(select(SettingRow).where(SettingRow.key == 'conflicts')) is None:
            db.add(SettingRow(key='conflicts', value=json.dumps([_dump_model(conflict) for conflict in data_store.CONFLICTS])))
        if db.scalar(select(TimetableCellRow.id).limit(1)) is None:
            for view, rows in data_store.TIMETABLE.items():
                for row_name, days in rows.items():
                    for day, session in days.items():
                        db.add(TimetableCellRow(view=view, row_name=row_name, day_index=day, session_json=_dump_model(session) if session else None))

    load_persisted_state()


def load_persisted_state() -> None:
    from app import data_store
    from app.models.schema import Room, ScheduleVersion, Session

    with SessionLocal() as db:
        user_rows = db.scalars(select(UserRow)).all()
        if user_rows:
            data_store.USERS[:] = [
                {'email': row.email, 'password': row.password, 'role': row.role, 'name': row.display_name}
                for row in user_rows
            ]
        data_store.DAYS[:] = _load_settings(db, 'days', data_store.DAYS)
        data_store.TIME_SLOTS[:] = _load_settings(db, 'time_slots', data_store.TIME_SLOTS)
        data_store.ROOMS[:] = _load_settings(db, 'rooms', data_store.ROOMS)
        data_store.LABS[:] = _load_settings(db, 'labs', data_store.LABS)
        data_store.STAFF[:] = _load_settings(db, 'staff', data_store.STAFF)
        conflict_row = db.get(SettingRow, 'conflicts')
        if conflict_row is not None:
            from app.models.schema import Conflict
            data_store.CONFLICTS[:] = [Conflict.model_validate(item) for item in json.loads(conflict_row.value)]
        room_rows = db.scalars(select(RoomRow)).all()
        if room_rows:
            data_store.ALL_ROOMS[:] = [Room.model_validate(row.payload) for row in room_rows]
        student_rows = db.scalars(select(StudentRow)).all()
        if student_rows:
            data_store.MANAGED_STUDENTS[:] = [dict(row.payload) for row in student_rows]
        version_rows = db.scalars(select(ScheduleVersionRow)).all()
        if version_rows:
            data_store.VERSIONS[:] = [ScheduleVersion.model_validate(row.payload) for row in version_rows]
        cell_rows = db.scalars(select(TimetableCellRow)).all()
        if cell_rows:
            data_store.TIMETABLE.clear()
            for cell in cell_rows:
                data_store.TIMETABLE.setdefault(cell.view, {}).setdefault(cell.row_name, {})[cell.day_index] = Session.model_validate(cell.session_json) if cell.session_json else None
            for view in ('rooms', 'labs', 'staff'):
                data_store.TIMETABLE.setdefault(view, {})
            for rows in data_store.TIMETABLE.values():
                for days in rows.values():
                    for day in range(len(data_store.DAYS)):
                        days.setdefault(day, None)


def save_timetable_cell(view: str, row_name: str, day: int, session: Any | None) -> None:
    with SessionLocal.begin() as db:
        row = db.scalar(select(TimetableCellRow).where(TimetableCellRow.view == view, TimetableCellRow.row_name == row_name, TimetableCellRow.day_index == day))
        payload = _dump_model(session) if session else None
        if row is None:
            db.add(TimetableCellRow(view=view, row_name=row_name, day_index=day, session_json=payload))
        else:
            row.session_json = payload


def save_timetable_row(view: str, row_name: str, days: dict[int, Any | None]) -> None:
    for day, session in days.items():
        save_timetable_cell(view, row_name, day, session)


def save_setting(key: str, value: Any) -> None:
    with SessionLocal.begin() as db:
        row = db.get(SettingRow, key)
        if row is None:
            db.add(SettingRow(key=key, value=json.dumps(value)))
        else:
            row.value = json.dumps(value)


def save_staff_rows(staff: list[str]) -> None:
    save_setting('staff', staff)


def save_room(room: Any) -> None:
    with SessionLocal.begin() as db:
        row = db.get(RoomRow, room.id)
        payload = _dump_model(room)
        if row is None:
            db.add(RoomRow(id=room.id, payload=payload))
        else:
            row.payload = payload


def delete_room(room_id: str) -> None:
    with SessionLocal.begin() as db:
        row = db.get(RoomRow, room_id)
        if row is not None:
            db.delete(row)


def save_student(student: dict[str, Any]) -> None:
    with SessionLocal.begin() as db:
        row = db.get(StudentRow, student['id'])
        if row is None:
            db.add(StudentRow(id=student['id'], payload=student))
        else:
            row.payload = student


def delete_student(student_id: str) -> None:
    with SessionLocal.begin() as db:
        row = db.get(StudentRow, student_id)
        if row is not None:
            db.delete(row)


def save_version(version: Any) -> None:
    with SessionLocal.begin() as db:
        row = db.get(ScheduleVersionRow, version.id)
        payload = _dump_model(version)
        if row is None:
            db.add(ScheduleVersionRow(id=version.id, payload=payload))
        else:
            row.payload = payload


def delete_version(version_id: str) -> None:
    with SessionLocal.begin() as db:
        row = db.get(ScheduleVersionRow, version_id)
        if row is not None:
            db.delete(row)
