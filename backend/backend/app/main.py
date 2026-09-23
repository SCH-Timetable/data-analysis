from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.database import initialize_database

from app.routers import auth, timetable, rooms, conflicts, analytics, students, versions, staff, chatbot

app = FastAPI(
    title="ScheduleAI API — Bua University",
    version="1.0.0",
    description="Backend for the Enterprise UI Dashboard timetable system.",
)

# Allow the Vite dev server (and any local origin) during development.
# In production, tighten origins to your actual domain.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:5174", "http://127.0.0.1:5174"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router,       prefix="/api/auth",      tags=["Auth"])
app.include_router(timetable.router,  prefix="/api/timetable", tags=["Timetable"])
app.include_router(rooms.router,      prefix="/api/rooms",     tags=["Rooms"])
app.include_router(conflicts.router,  prefix="/api/conflicts", tags=["Conflicts"])
app.include_router(analytics.router,  prefix="/api/analytics", tags=["Analytics"])
app.include_router(students.router,   prefix="/api/students",  tags=["Students"])
app.include_router(versions.router,   prefix="/api/versions",  tags=["Versions"])
app.include_router(staff.router,      prefix="/api/staff",     tags=["Staff"])
app.include_router(chatbot.router,    tags=["Chatbot"])


@app.on_event('startup')
def startup_database():
    # If MySQL is down / credentials are wrong, fall back to the in-memory
    # seed data in data_store so the API (incl. chatbot) still works.
    try:
        initialize_database()
    except Exception as exc:  # noqa: BLE001
        print(f"WARNING: database init failed, using in-memory data: {exc}")


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/health")
def health_alias():
    return {"status": "ok"}


@app.get("/")
def root():
    return {"name": "ScheduleAI API — Bua University", "docs": "/docs", "health": "/api/health"}
