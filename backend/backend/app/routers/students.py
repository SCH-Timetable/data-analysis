"""
Student endpoints.

GET /api/students/me          → current student profile + sessions + credits
GET /api/students/me/sessions → timetable sessions for the current student
GET /api/students/me/credits  → credit summary
GET /api/students             → managed student roster (mirrors StudentManagerModal)
POST /api/students            → add a student {name, email, group, year}
PATCH /api/students/{id}      → update group (or name/email/year)
DELETE /api/students/{id}     → remove a student
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from app.models.schema import StudentProfile, StudentSession, Credit
from app.data_store import STUDENT_PROFILE, MANAGED_STUDENTS
from app.database import delete_student, save_student

router = APIRouter()


class StudentCreate(BaseModel):
    name: str
    email: str
    group: str
    year: str = 'Year 2'


class StudentUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    group: Optional[str] = None
    year: Optional[str] = None


@router.get('/me', response_model=StudentProfile)
def get_my_profile():
    return STUDENT_PROFILE


@router.get('/me/sessions', response_model=list[StudentSession])
def get_my_sessions():
    return STUDENT_PROFILE.sessions


@router.get('/me/credits', response_model=list[Credit])
def get_my_credits():
    return STUDENT_PROFILE.credits


@router.get('')
def list_students(q: Optional[str] = None):
    if not q:
        return MANAGED_STUDENTS
    ql = q.lower()
    return [s for s in MANAGED_STUDENTS
            if ql in s['name'].lower() or ql in s['group'].lower() or ql in s['email'].lower()]


@router.post('', status_code=201)
def add_student(body: StudentCreate):
    if not body.name.strip() or not body.email.strip():
        raise HTTPException(status_code=422, detail='name and email are required')
    if any(s['email'].lower() == body.email.lower() for s in MANAGED_STUDENTS):
        raise HTTPException(status_code=409, detail='email already exists')
    new = {'id': f"st-{len(MANAGED_STUDENTS) + 100}", 'name': body.name.strip(),
           'email': body.email.strip(), 'group': body.group.strip() or 'GEN', 'year': body.year}
    MANAGED_STUDENTS.append(new)
    save_student(new)
    return new


@router.patch('/{student_id}')
def update_student(student_id: str, body: StudentUpdate):
    s = next((x for x in MANAGED_STUDENTS if x['id'] == student_id), None)
    if s is None:
        raise HTTPException(status_code=404, detail=f"Student '{student_id}' not found")
    for k in ('name', 'email', 'group', 'year'):
        v = getattr(body, k)
        if v is not None and str(v).strip():
            s[k] = str(v).strip()
    save_student(s)
    return s


@router.delete('/{student_id}')
def remove_student(student_id: str):
    before = len(MANAGED_STUDENTS)
    MANAGED_STUDENTS[:] = [x for x in MANAGED_STUDENTS if x['id'] != student_id]
    if len(MANAGED_STUDENTS) == before:
        raise HTTPException(status_code=404, detail=f"Student '{student_id}' not found")
    delete_student(student_id)
    return {'ok': True, 'deleted': student_id}
