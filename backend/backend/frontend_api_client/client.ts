/**
 * src/api/client.ts
 *
 * Thin fetch wrapper for the ScheduleAI backend.
 * Drop this file into your frontend at src/api/client.ts and set
 * VITE_API_URL in a local .env file:
 *
 *   VITE_API_URL=http://localhost:8000
 *
 * Then enable the Vite proxy in vite.config.ts (already commented-out there):
 *
 *   server: {
 *     proxy: { '/api': { target: 'http://localhost:8000', changeOrigin: true } },
 *   }
 *
 * With the proxy you can leave VITE_API_URL empty and all /api/* requests
 * will be forwarded automatically during development.
 */

const BASE = import.meta.env.VITE_API_URL ?? '';

// ─── Auth token (stored in memory; swap for httpOnly cookie in production) ────

let _token: string | null = null;

export function setToken(t: string | null) { _token = t; }
export function getToken() { return _token; }


// ─── Low-level fetch helper ────────────────────────────────────────────────────

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (_token) headers['Authorization'] = `Bearer ${_token}`;

  const res = await fetch(`${BASE}${path}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(detail?.detail ?? `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

const get  = <T>(path: string)               => request<T>('GET',    path);
const post = <T>(path: string, body?: unknown) => request<T>('POST',   path, body);
const put  = <T>(path: string, body?: unknown) => request<T>('PUT',    path, body);
const del  = <T>(path: string)               => request<T>('DELETE', path);


// ─── Auth ──────────────────────────────────────────────────────────────────────

export interface LoginResponse {
  role: 'admin' | 'lecturer' | 'student';
  token: string;
  display_name: string;
}

export const auth = {
  login:  (email: string, password: string) =>
    post<LoginResponse>('/api/auth/login', { email, password }),
  logout: () => post<{ ok: boolean }>('/api/auth/logout'),
  me:     () => get<LoginResponse>('/api/auth/me'),
};


// ─── Timetable ─────────────────────────────────────────────────────────────────

export type ViewMode = 'rooms' | 'labs' | 'staff';

export interface Session {
  id: string;
  code: string;
  name: string;
  staff: string;
  group: string;
  capacity: number;
  enrolled: number;
  color: string;
  conflictId?: string;
}

export type TimetableRow   = Record<string, Session | null>;   // day-index → Session
export type TimetableView  = Record<string, TimetableRow>;      // row-label → TimetableRow

export interface TimetableConstants {
  days: string[];
  fullDays: string[];
  timeSlots: string[];
  rooms: string[];
  labs: string[];
  staff: string[];
}

export const timetable = {
  constants: ()                                   => get<TimetableConstants>('/api/timetable/constants'),
  full:      ()                                   => get<Record<ViewMode, TimetableView>>('/api/timetable'),
  view:      (v: ViewMode)                        => get<TimetableView>(`/api/timetable/${v}`),
  row:       (v: ViewMode, row: string)           => get<TimetableRow>(`/api/timetable/${v}/${encodeURIComponent(row)}`),
  setSlot:   (v: ViewMode, row: string, day: number, session: Session | null) =>
    put(`/api/timetable/${v}/${encodeURIComponent(row)}/${day}`, session),
};


// ─── Rooms ─────────────────────────────────────────────────────────────────────

export interface Room {
  id: string;
  name: string;
  building: string;
  floor: number;
  type: string;
  capacity: number;
  examCapacity: number;
  accessibility: string[];
  equipment: string[];
  closures: { label: string; from: string; to: string; reason: string }[];
  status: 'Available' | 'Maintenance' | 'Closed';
  bookingRate: number;
  notes: string;
}

export const rooms = {
  list:      (params?: { type?: string; status?: string; building?: string; q?: string }) => {
    const qs = params ? '?' + new URLSearchParams(params as Record<string,string>).toString() : '';
    return get<Room[]>(`/api/rooms${qs}`);
  },
  get:       (id: string)           => get<Room>(`/api/rooms/${id}`),
  update:    (id: string, data: Partial<Room>) => put<Room>(`/api/rooms/${id}`, data),
  buildings: ()                     => get<string[]>('/api/rooms/buildings'),
};


// ─── Conflicts ─────────────────────────────────────────────────────────────────

export interface Alternative {
  id: string;
  score: number;
  day: number;
  slot: number;
  room: string;
  reasons: string[];
}

export interface Conflict {
  id: string;
  type: 'double_booking' | 'capacity' | 'staff_overlap' | 'equipment' | 'student_group' | 'room_type' | 'closure';
  severity: 'hard' | 'soft';
  description: string;
  cell: { row: string; day: number; slot: number };
  alternatives: Alternative[];
}

export const conflicts = {
  list:    ()                                              => get<Conflict[]>('/api/conflicts'),
  get:     (id: string)                                   => get<Conflict>(`/api/conflicts/${id}`),
  apply:   (conflictId: string, alternativeId: string)    =>
    post(`/api/conflicts/${conflictId}/apply`, { conflict_id: conflictId, alternative_id: alternativeId }),
  dismiss: (id: string)                                   => del(`/api/conflicts/${id}`),
};


// ─── Analytics ─────────────────────────────────────────────────────────────────

export interface AnalyticsSummary {
  total_sessions: number;
  total_conflicts: number;
  avg_utilization: number;
  rooms_at_capacity: number;
  utilization_by_room: { name: string; utilization: number }[];
  utilization_by_day:  { name: string; utilization: number }[];
  utilization_by_hour: { name: string; utilization: number }[];
  conflict_breakdown:  { name: string; value: number; color: string }[];
}

export const analytics = {
  summary: () => get<AnalyticsSummary>('/api/analytics/summary'),
};


// ─── Versions ──────────────────────────────────────────────────────────────────

export interface ScheduleVersion {
  id: string;
  label: string;
  status: 'draft' | 'published' | 'archived';
  timestamp: string;
  author: string;
  changes: number;
  conflicts: number;
}

export const versions = {
  list:    ()                           => get<ScheduleVersion[]>('/api/versions'),
  get:     (id: string)                 => get<ScheduleVersion>(`/api/versions/${id}`),
  create:  (label: string, author?: string) =>
    post<ScheduleVersion>(`/api/versions?label=${encodeURIComponent(label)}${author ? `&author=${encodeURIComponent(author)}` : ''}`),
  publish: (id: string)                 => post<ScheduleVersion>(`/api/versions/${id}/publish`),
  archive: (id: string)                 => post<ScheduleVersion>(`/api/versions/${id}/archive`),
  delete:  (id: string)                 => del(`/api/versions/${id}`),
};


// ─── Student portal ────────────────────────────────────────────────────────────

export interface StudentSession {
  id: string; code: string; name: string; staff: string;
  room: string; day: number; slot: number; color: string;
}

export interface Credit {
  code: string; name: string; credits: number;
  grade: string | null; status: 'completed' | 'in_progress' | 'planned';
}

export interface StudentProfile {
  id: string; name: string; group: string;
  programme: string; year: number;
  sessions: StudentSession[];
  credits: Credit[];
  total_credits_required: number;
  total_credits_earned: number;
}

export const students = {
  me:       () => get<StudentProfile>('/api/students/me'),
  sessions: () => get<StudentSession[]>('/api/students/me/sessions'),
  credits:  () => get<Credit[]>('/api/students/me/credits'),
  list:     (q?: string) => get<ManagedStudent[]>(`/api/students${q ? `?q=${encodeURIComponent(q)}` : ''}`),
  add:      (data: { name: string; email: string; group: string; year?: string }) => post<ManagedStudent>('/api/students', data),
  updateGroup: (id: string, group: string) => request<ManagedStudent>('PATCH', `/api/students/${id}`, { group }),
  remove:   (id: string) => del(`/api/students/${id}`),
};

export interface ManagedStudent {
  id: string; name: string; email: string; group: string; year: string;
}

export const staff = {
  list:   () => get<string[]>('/api/staff'),
  add:    (name: string) => post('/api/staff', { name }),
  remove: (name: string) => del(`/api/staff/${encodeURIComponent(name)}`),
};
