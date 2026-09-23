// Single adapter: UI talks only to these functions.
// USE_MOCK=false -> talks to the real FastAPI backend (http://localhost:8000).
// If the backend is down, every function falls back to the local mock engine
// so the demo never breaks (deterministic baseline + fallback, project Rule 5).
// sch-chatbot-starter/api.js
import * as mock from "./mockData.js";
import { checkMove } from "./conflictEngine.js";
import { recommendAlternatives, occupancy } from "./recommender.js";

export const USE_MOCK = false;
export const BACKEND_URL = "http://localhost:8000";

function ctxFromMock() {
  return {
    allocations: mock.sch_allocation,
    rooms: mock.sch_room,
    days: mock.sch_day,
    slots: mock.sch_time_slot,
    closures: mock.sch_room_closure,
    availability: mock.sch_availability_constraint,
    roomEquipment: mock.sch_room_equipment,
  };
}

async function fetchJSON(url, options) {
  const r = await fetch(url, options);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

// ── Primary: backend chat (NLU + facts + Arabic answer in one call) ──────────
export async function sendChat(message) {
  const data = await fetchJSON(`${BACKEND_URL}/api/chatbot/message`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
  return data; // {intent, entities, answer_ar, facts, gemini_used}
}

// ── Timetable ────────────────────────────────────────────────────────────────
// Accepts both shapes: {staff, day} (names, real backend) and
// {staff_id, day_id} (mock ids). Returns enriched rows with BOTH flat fields
// (room, day_name, time) and nested objects (room.room_number ...) so old UI
// code keeps working.
export async function getTimetable({ staff_id, day_id, staff, day } = {}) {
  if (!USE_MOCK) {
    try {
      const q = new URLSearchParams();
      if (staff) q.set("staff", staff);
      if (day !== undefined && day !== null) q.set("day", String(day));
      const rows = await fetchJSON(`${BACKEND_URL}/api/chatbot/timetable?${q}`);
      return rows.map((r) => ({
        ...r,
        day: { day_name: r.day_name },
        slot: { start_time: (r.time || "").split("-")[0] || r.time || "", end_time: "" },
        course: { course_name: r.name, course_code: r.code },
        room: { room_number: r.room, ...r.room },
        section: { id: r.id },
      }));
    } catch {
      // fall through to mock
    }
  }
  let rows = mock.sch_allocation;
  if (staff_id) rows = rows.filter((a) => a.staff_id === staff_id);
  if (day_id) rows = rows.filter((a) => a.day_id === day_id);
  if (staff) {
    const found = mock.sch_staff.find((s) =>
      `${s.first_name} ${s.last_name}`.toLowerCase().includes(String(staff).toLowerCase()));
    if (found) rows = rows.filter((a) => a.staff_id === found.id);
    else rows = [];
  }
  if (day !== undefined && day !== null && !day_id) {
    const dayIdx = mock.sch_day.findIndex((d) => d.day_name.toLowerCase() === String(day).toLowerCase());
    const id = mock.sch_day[dayIdx]?.id;
    if (id) rows = rows.filter((a) => a.day_id === id);
  }
  return rows.map((a) => ({
    ...a,
    staff: mock.sch_staff.find((s) => s.id === a.staff_id),
    room: mock.sch_room.find((r) => r.id === a.room_id),
    day: mock.sch_day.find((d) => d.id === a.day_id),
    slot: mock.sch_time_slot.find((s) => s.id === a.time_slot_id),
    section: mock.sch_section.find((s) => s.id === a.section_id),
    course: mock.sch_course.find((c) => c.id === (mock.sch_section.find((s) => s.id === a.section_id) || {}).course_id),
  }));
}

// ── What-if dry run — never writes ───────────────────────────────────────────
// Real shape: {staff, room, day (0-4 or name), group?, enrolled?}
// Mock shape:  {section_id, staff_id, room_id, day_id, time_slot_id}
export async function validateMove(candidate) {
  const isRealShape =
    candidate && (candidate.staff || candidate.room || candidate.group) &&
    (candidate.day !== undefined && candidate.day !== null);
  if (!USE_MOCK && isRealShape) {
    try {
      const res = await fetchJSON(`${BACKEND_URL}/api/allocations/check`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(candidate),
      });
      return normalizeCheck(res);
    } catch {
      // fall through to mock only if candidate also has mock ids
    }
  }
  if (!USE_MOCK && isRealShape) {
    // backend unreachable and no mock ids -> honest no-hallucination answer
    return {
      ok: false,
      conflicts: [{ conflict_type: "BACKEND_UNREACHABLE", description: "Backend is down, cannot verify against live data." }],
      recommendations: [],
    };
  }
  const ctx = ctxFromMock();
  const res = checkMove(candidate, ctx);
  const alternatives = res.ok ? [] : recommendAlternatives(candidate, ctx, 3);
  return { ...res, recommendations: alternatives };
}

function normalizeCheck(res) {
  const recs = (res.recommendations || []).map((a) => ({
    day_name: a.day_name,
    start_time: a.start_time || "",
    end_time: a.end_time || "",
    room_number: a.room_number || a.room,
    explanation: a.explanation || (a.reasons || []).join("، "),
    score: a.score,
    _raw: a,
  }));
  return { ...res, recommendations: recs };
}

export async function searchRooms({ minCapacity, day_id, time_slot_id, day } = {}) {
  if (!USE_MOCK) {
    try {
      const q = new URLSearchParams();
      if (minCapacity) q.set("minCapacity", String(minCapacity));
      const d = day !== undefined && day !== null ? day : day_id;
      if (d !== undefined && d !== null) q.set("day", String(d));
      const rooms = await fetchJSON(`${BACKEND_URL}/api/search/rooms?${q}`);
      return rooms;
    } catch {
      // fall through to mock
    }
  }
  const ctx = ctxFromMock();
  const did = day_id ?? day ?? null;
  return ctx.rooms
    .filter((r) => !minCapacity || r.capacity >= minCapacity)
    .filter((r) => !ctx.closures.some((c) => c.room_id === r.id && c.day_id === did && c.time_slot_id === (time_slot_id ?? did)))
    .filter((r) => !ctx.allocations.some((a) => a.room_id === r.id && a.day_id === did && (time_slot_id == null || a.time_slot_id === time_slot_id)));
}

export async function getOccupancy() {
  if (!USE_MOCK) {
    try {
      return await fetchJSON(`${BACKEND_URL}/api/analytics/occupancy`);
    } catch {
      // fall through to mock
    }
  }
  const ctx = ctxFromMock();
  return occupancy(ctx.allocations, ctx.rooms, ctx.days, ctx.slots);
}
