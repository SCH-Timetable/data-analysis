"""
Chatbot + deterministic scheduling baseline (SCH-FR-05 / FR-06 / FR-10).

This router is the bridge between:
  - sch-chatbot-starter/ (api.js expects these paths)
  - the real FastAPI backend (app/data_store.py)

Design rule (project Rule 5):
  - All FACTS come from data_store (TIMETABLE, ALL_ROOMS, CONFLICTS).
  - Gemini is used ONLY for NLU (text -> intent JSON) and NLG
    (facts -> Arabic explanation). It must never invent rooms/times.
  - If GEMINI_API_KEY is missing, everything still works with a
    rule-based Arabic fallback. That is the deterministic baseline.

Routes (full paths, mounted WITHOUT prefix in main.py):
  POST /api/allocations/check   <- what-if dry run, never writes (starter: validateMove)
  GET  /api/search/rooms        <- free-room search (starter: searchRooms)
  GET  /api/analytics/occupancy <- per-room occupancy (starter: getOccupancy)
  GET  /api/chatbot/timetable   <- ?staff=&day=  (starter: getTimetable adapter)
  POST /api/chatbot/message     <- {message} -> {intent, entities, answer_ar, facts}
"""

from __future__ import annotations

import base64
import json
import os
import urllib.request
from datetime import date, datetime, time, timedelta
from typing import Any, Optional
from urllib.parse import urlencode

from fastapi import APIRouter, File, Response, UploadFile
from pydantic import BaseModel

from app import data_store

router = APIRouter()

# ── Day / time helpers (Arabic + English) ─────────────────────────────────────
# Week tables are DATA-DRIVEN from data_store.DAYS (the live calendar).
# Demo seed is Mon-Fri; if the backend team reseeds to Sun-Thu for the
# Egyptian week, Sunday/الأحد starts working with zero code changes here.

_SHORT2FULL = {"Mon": "Monday", "Tue": "Tuesday", "Wed": "Wednesday",
               "Thu": "Thursday", "Fri": "Friday", "Sat": "Saturday", "Sun": "Sunday"}
_AR_BY_SHORT = {"Mon": ("الاثنين",), "Tue": ("الثلاثاء",),
                "Wed": ("الاربعاء", "الأربعاء"), "Thu": ("الخميس",),
                "Fri": ("الجمعة", "الجمعه"), "Sat": ("السبت",),
                "Sun": ("الأحد", "الاحد")}


def _build_day_tables(short_days: list[str]) -> tuple[list[str], list[str], dict[str, int]]:
    full, full_ar, aliases = [], [], {}
    for i, short in enumerate(short_days):
        fname = _SHORT2FULL.get(short, short)
        arnames = _AR_BY_SHORT.get(short, ())
        full.append(fname)
        full_ar.append(arnames[0] if arnames else fname)
        aliases[short.lower()] = i
        aliases[fname.lower()] = i
        for ar in arnames:
            aliases[ar] = i
    return full, full_ar, aliases


_FULL_DAYS, _FULL_DAYS_AR, _AR_DAYS = _build_day_tables(list(data_store.DAYS))
# NOTE: data_store.DAYS = ['Mon','Tue','Wed','Thu','Fri'] (5 columns).
# data_store.TIME_SLOTS has 10 clock times but the grid only has 5 day-columns,
# so a "slot" here = day column index. We keep slot param for starter compat
# and map it to the day column when slot is 0-4.


def _parse_day(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, int) and 0 <= value <= 4:
        return value
    s = str(value).strip().lower()
    if s.isdigit() and 0 <= int(s) <= 4:
        return int(s)
    return _AR_DAYS.get(s)


def _day_label(day: int) -> str:
    try:
        return _FULL_DAYS[day]
    except IndexError:
        return f"Day-{day}"


def _room_by_name(name: str):
    if not name:
        return None
    return next((r for r in data_store.ALL_ROOMS if r.name.lower() == str(name).lower()), None)


def _norm(s: Any) -> str:
    """Lowercase ASCII-folded text: Kovač==kovac, أحمد stays أحمد."""
    import unicodedata
    return unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower().strip()


def _find_matching_session(staff: Optional[str], room: Optional[str], day: Optional[int]):
    """Find a live session with same staff + room + day (an entry copied from reality).

    Staff matches on normalized last name so 'Lena Kovac' matches 'Dr. Lena Kovač'.
    Returns the Session or None.
    """
    if not staff or not room or day is None:
        return None
    parts = _norm(staff).split()
    if not parts:
        return None
    last = parts[-1]
    for view in ("rooms", "labs"):
        for row_name, days in data_store.TIMETABLE.get(view, {}).items():
            if _norm(row_name) != _norm(room):
                continue
            sess = days.get(day)
            if sess is not None and last in _norm(sess.staff):
                return sess
    return None


def _sessions_at(day: int, slot: Optional[int] = None) -> list[tuple[str, Any]]:
    """All (row, session) in rooms view at a day column."""
    out = []
    for row, days in data_store.TIMETABLE.get("rooms", {}).items():
        sess = days.get(day)
        if sess is not None:
            out.append((row, sess))
    # labs view too
    for row, days in data_store.TIMETABLE.get("labs", {}).items():
        sess = days.get(day)
        if sess is not None:
            out.append((row, sess))
    return out


def _staff_busy(staff: str, day: int, exclude_id: Optional[str] = None) -> Optional[Any]:
    for view in ("staff", "rooms", "labs"):
        for _row, days in data_store.TIMETABLE.get(view, {}).items():
            sess = days.get(day)
            if sess is not None and _norm(sess.staff) == _norm(staff):
                if exclude_id and sess.id == exclude_id:
                    continue
                return sess
    # direct staff row
    return None


# ── Core deterministic check (mirrors sch-chatbot-starter/conflictEngine.js) ──

class CheckMoveBody(BaseModel):
    # Real-backend shape (names)
    staff: Optional[str] = None
    group: Optional[str] = None
    room: Optional[str] = None
    day: Optional[Any] = None
    slot: Optional[Any] = None
    enrolled: Optional[int] = None
    # Starter SCH-ids shape (compat) — resolved best-effort to names
    staff_id: Optional[Any] = None
    room_id: Optional[Any] = None
    day_id: Optional[Any] = None
    time_slot_id: Optional[Any] = None
    section_id: Optional[Any] = None
    exclude_allocation_id: Optional[Any] = None
    required_equipment: Optional[str] = None


def _resolve_names(body: CheckMoveBody) -> dict:
    """Accept both shapes, return {staff, group, room, day, enrolled}."""
    staff = body.staff
    room = body.room
    day = _parse_day(body.day if body.day is not None else body.day_id)
    group = body.group
    enrolled = body.enrolled

    # SCH-ids compat: starter mock has its own tables; when USE_MOCK=false
    # the frontend should send names. If ids arrive, map day only and
    # leave staff/room to explicit name fields.
    if day is None and body.time_slot_id is not None:
        try:
            slot_as_day = int(body.time_slot_id)
            if 0 <= slot_as_day <= 4:
                day = slot_as_day
        except (TypeError, ValueError):
            pass
    return {"staff": staff, "group": group, "room": room, "day": day, "enrolled": enrolled}


def deterministic_check(staff=None, group=None, room=None, day=None,
                        enrolled=None, exclude_id=None,
                        required_equipment=None) -> dict:
    conflicts: list[dict] = []
    if day is None:
        return {"ok": False, "conflicts": [
            {"conflict_type": "MISSING_INPUT",
             "description": "حدد اليوم (Day 0-4 أو الأحد..الخميس)."}]}

    at = _sessions_at(day)

    # 1. STAFF_BUSY
    if staff:
        clash = next((s for _r, s in at if _norm(s.staff) == _norm(staff)
                      and (not exclude_id or s.id != exclude_id)), None)
        if clash is None:
            clash = _staff_busy(staff, day, exclude_id)
            # _staff_busy already searched rooms; avoid double count
            if clash is not None and any(s.id == clash.id for _r, s in at):
                clash = None
        if clash is not None:
            conflicts.append({
                "conflict_type": "STAFF_BUSY",
                "description": f"الدكتور {staff} عنده محاضرة تانية ({clash.code} - {clash.name}) في {_day_label(day)}.",
            })

    # 2. ROOM_BUSY
    if room:
        clash = next(((r, s) for r, s in at if _norm(r) == _norm(room)), None)
        if clash is not None:
            _r, s = clash
            conflicts.append({
                "conflict_type": "ROOM_BUSY",
                "description": f"القاعة {room} مشغولة بمادة {s.code} في {_day_label(day)}.",
            })

    # 3. GROUP_CLASH
    if group:
        clash = next((s for _r, s in at if _norm(s.group) == _norm(group)
                      and (not exclude_id or s.id != exclude_id)), None)
        if clash is not None:
            conflicts.append({
                "conflict_type": "GROUP_CLASH",
                "description": f"المجموعة {group} عندها مادة تانية ({clash.code}) في نفس المعاد.",
            })

    # 4. CAPACITY
    if room and enrolled:
        r = _room_by_name(room)
        if r is not None and enrolled > r.capacity:
            conflicts.append({
                "conflict_type": "CAPACITY",
                "description": f"سعة القاعة {r.capacity} أقل من عدد الطلاب {enrolled}.",
            })

    # 5. CLOSURE / status
    if room:
        r = _room_by_name(room)
        if r is not None and r.status != "Available":
            conflicts.append({
                "conflict_type": "CLOSURE",
                "description": f"القاعة {room} حالتها {r.status} ({r.notes}).",
            })

    # 6. EQUIPMENT / room_type
    if room and required_equipment:
        r = _room_by_name(room)
        if r is not None and required_equipment not in (r.equipment or []):
            conflicts.append({
                "conflict_type": "EQUIPMENT",
                "description": f"القاعة {room} مفيهاش {required_equipment}. المتاح: {', '.join(r.equipment) or 'لا يوجد'}.",
            })

    return {"ok": len(conflicts) == 0, "conflicts": conflicts}


def recommend_free_slots(staff=None, group=None, enrolled=None,
                         required_equipment=None, limit=3,
                         prefer_day: Optional[int] = None) -> list[dict]:
    """Scan rooms x days, keep feasible, rank by capacity fit (SCH-FR-06)."""
    cands = []
    rooms = [r for r in data_store.ALL_ROOMS if r.status == "Available"]
    for d in range(len(data_store.DAYS)):
        for r in rooms:
            if enrolled and r.capacity < enrolled:
                continue
            if required_equipment and required_equipment not in (r.equipment or []):
                continue
            res = deterministic_check(staff=staff, group=group, room=r.name,
                                      day=d, enrolled=enrolled,
                                      required_equipment=required_equipment)
            if not res["ok"]:
                continue
            waste = (r.capacity - enrolled) if enrolled else 0
            same_day = 0 if (prefer_day is not None and d == prefer_day) else 10
            # lower score = better (matches starter recommender convention)
            score = waste + same_day - (r.booking_rate // 10)
            expl = f"سعة {r.capacity} (هدر {waste})، {r.type}، إشغال {r.booking_rate}%"
            cands.append({
                "day": d, "day_name": _day_label(d),
                "slot": d, "room": r.name,
                "score": 100 - min(score, 99),
                "reasons": [expl,
                            "الدكتور فاضي" if staff else "بدون شرط دكتور",
                            "نفس اليوم المطلوب" if same_day == 0 else "يوم مختلف"],
            })
    cands.sort(key=lambda c: c["score"], reverse=True)
    return cands[:limit]


def explain_check_ar(result: dict) -> str:
    if result.get("ok"):
        return "✅ التغيير ممكن. مفيش أي تعارض (دكتور/قاعة/مجموعة/سعة)."
    lines = ["❌ لا يمكن تنفيذ النقل للأسباب التالية:"]
    for c in result.get("conflicts", []):
        lines.append(f"- [{c['conflict_type']}] {c['description']}")
    recs = result.get("recommendations") or []
    if recs:
        lines.append("\nأقرب البدائل المتاحة:")
        for a in recs:
            reasons = "، ".join(a.get("reasons", []))
            lines.append(f"- {a.get('day_name')} في {a.get('room')} (score {a.get('score')}) — {reasons}")
    return "\n".join(lines)


# ── Compatibility endpoints for sch-chatbot-starter/api.js ────────────────────

@router.post("/api/allocations/check")
def allocations_check(body: CheckMoveBody):
    r = _resolve_names(body)
    res = deterministic_check(staff=r["staff"], group=r["group"], room=r["room"],
                              day=r["day"], enrolled=r["enrolled"],
                              required_equipment=body.required_equipment)
    if not res["ok"]:
        res["recommendations"] = recommend_free_slots(
            staff=r["staff"], group=r["group"], enrolled=r["enrolled"],
            required_equipment=body.required_equipment, limit=3, prefer_day=r["day"])
    else:
        res["recommendations"] = []
    res["explanation_ar"] = explain_check_ar(res)
    return res


@router.get("/api/search/rooms")
def search_rooms(minCapacity: Optional[int] = None, day: Optional[Any] = None,
                 day_id: Optional[Any] = None, slot: Optional[Any] = None,
                 type: Optional[str] = None, equipment: Optional[str] = None):
    d = _parse_day(day if day is not None else day_id)
    out = []
    for r in data_store.ALL_ROOMS:
        if r.status != "Available":
            continue
        if minCapacity and r.capacity < minCapacity:
            continue
        if type and r.type != type:
            continue
        if equipment and equipment not in (r.equipment or []):
            continue
        busy = False
        if d is not None:
            busy = any(row.lower() == r.name.lower() for row, _s in _sessions_at(d))
        out.append({"id": r.id, "name": r.name, "building": r.building,
                    "type": r.type, "capacity": r.capacity,
                    "equipment": r.equipment, "bookingRate": r.booking_rate,
                    "free_at_requested_day": (not busy) if d is not None else None})
    out.sort(key=lambda x: x["capacity"])
    return out


@router.get("/api/analytics/occupancy")
def analytics_occupancy():
    total = max(len(data_store.DAYS), 1)
    occ = []
    for r in data_store.ALL_ROOMS:
        used = sum(1 for row, days in data_store.TIMETABLE.get("rooms", {}).items()
                   if row.lower() == r.name.lower()
                   for s in days.values() if s is not None)
        used += sum(1 for row, days in data_store.TIMETABLE.get("labs", {}).items()
                    if row.lower() == r.name.lower()
                    for s in days.values() if s is not None)
        pct = round(used / total * 100) if total else 0
        occ.append({"room_id": r.id, "room_number": r.name,
                    "used": used, "total": total, "pct": pct})
    occ.sort(key=lambda o: o["pct"], reverse=True)
    return occ


@router.get("/api/chatbot/timetable")
def chatbot_timetable(staff: Optional[str] = None, day: Optional[Any] = None):
    """Starter-compatible: ?staff=Ahmed&day=Monday -> enriched rows."""
    d = _parse_day(day)
    rows = []
    for view, grid in data_store.TIMETABLE.items():
        for row_name, days in grid.items():
            for day_idx, sess in days.items():
                if sess is None:
                    continue
                if staff and staff.lower() not in sess.staff.lower():
                    continue
                if d is not None and day_idx != d:
                    continue
                slot_label = data_store.TIME_SLOTS[day_idx] if day_idx < len(data_store.TIME_SLOTS) else ""
                rows.append({
                    "id": sess.id, "code": sess.code, "name": sess.name,
                    "staff": sess.staff, "group": sess.group,
                    "room": row_name, "view": view,
                    "day": day_idx, "day_name": _day_label(day_idx),
                    "slot": day_idx, "time": slot_label,
                    "enrolled": sess.enrolled, "capacity": sess.capacity,
                })
    return rows


# ── Chat endpoint: rule-based NLU baseline + optional Gemini polish ───────────

class ChatBody(BaseModel):
    message: str
    staff: Optional[str] = None  # optional context (logged-in user)


def _rule_parse(text: str) -> dict:
    t = (text or "").lower()
    intent = "show_schedule"
    entities: dict[str, Any] = {}
    if any(k in t for k in ["انقل", "ينفع", "move", "what if", "ماذا لو", "احطه", "احط"]):
        intent = "check_move"
    elif any(k in t for k in ["قاعة", "معمل", "room", "lab", "فاضية", "فاضي", "60 طالب", "سعة"]):
        intent = "find_room"
    elif any(k in t for k in ["استخدام", "occupancy", "utilization", "أكثر القاعات", "اكثر القاعات", "أقل", "اقل", "احصائيات", "peak"]):
        intent = "occupancy"
    elif any(k in t for k in ["insight", "تحليل", "ضغط", "متتالية", "مضغوط", "توزيع", "ورا بعض"]):
        intent = "insights"
    elif any(k in t for k in ["ics", "ical", "تقويم", "calendar", "export",
                              "تحميل", "احمل", "تنزيل", "نزل", "تصدير", "موبايل"]):
        intent = "export"
    elif any(k in t for k in ["جدول", "schedule", "show", "مواعيد", "حصص"]):
        intent = "show_schedule"

    for name in data_store.STAFF:
        if name.lower().split()[-1] in t or name.lower() in t:
            entities["staff"] = name
            break
    if "ahmed" in t or "أحمد" in t or "احمد" in t:
        entities.setdefault("staff", "Dr. Ahmed Hassan")
    if "سارة" in text or "ساره" in text or "sara" in t:
        entities.setdefault("staff", "Prof. Sara Johansson")
    if "فاطمة" in text or "فاطمه" in text or "fatma" in t:
        entities.setdefault("staff", "Dr. Fatma Ali")
    for i, dn in enumerate(_FULL_DAYS):
        if dn.lower() in t:
            entities["day"] = i
    for ar, idx in _AR_DAYS.items():
        if ar in t:
            entities["day"] = idx
    import re
    m = re.search(r"(\d{1,2}):(\d{2})", t)
    if m:
        entities["time"] = m.group(0)
    m2 = re.search(r"(\d+)\s*(طالب|student|capacity|سعة)", t)
    if m2:
        entities["minCapacity"] = int(m2.group(1))
    for r in data_store.ALL_ROOMS:
        if r.name.lower() in t:
            entities["room"] = r.name
    return {"intent": intent, "entities": entities}


_GEMINI_SYSTEM = (
    "You are SCH scheduling assistant. Return ONLY JSON like "
    '{"intent":"show_schedule|check_move|find_room|occupancy|insights|export",'
    '"entities":{"staff":null,"day":null,"room":null,"minCapacity":null}}. '
    "Days: Monday-Friday or الأحد-الخميس. "
    "export = user wants calendar file (ICS, تقويم, تحميل الجدول). "
    "insights = load/pressure analysis (ضغط, توزيع). "
    "Never invent data."
)


def _gemini_parse(text: str) -> Optional[dict]:
    key = os.getenv("GEMINI_API_KEY", "")
    if not key:
        return None
    try:
        payload = json.dumps({
            "system_instruction": {"parts": [{"text": _GEMINI_SYSTEM}]},
            "contents": [{"parts": [{"text": text}]}],
        }).encode()
        req = urllib.request.Request(
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key=" + key,
            data=payload, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        raw = data["candidates"][0]["content"]["parts"][0]["text"]
        raw = raw.replace("```json", "").replace("```", "").strip()
        parsed = json.loads(raw)
        if isinstance(parsed, dict) and "intent" in parsed:
            return parsed
        return None
    except Exception:
        return None


@router.post("/api/chatbot/message")
def chatbot_message(body: ChatBody):
    text = body.message or ""
    # 1. NLU: Gemini first, rule-based fallback (deterministic baseline)
    parsed = _gemini_parse(text) or _rule_parse(text)
    intent = parsed.get("intent", "show_schedule")
    ent = parsed.get("entities", {}) or {}
    if body.staff and "staff" not in ent:
        ent["staff"] = body.staff
    facts: dict[str, Any] = {}
    answer = ""

    if intent == "show_schedule":
        rows = chatbot_timetable(staff=ent.get("staff"), day=ent.get("day"))
        facts = {"rows": rows}
        if not rows:
            answer = "مفيش حصص مطابقة. جرب اسم دكتور تاني أو يوم تاني (Monday-Friday)."
        else:
            who = ent.get("staff") or "الكل"
            lines = [f"📅 جدول {who}:"]
            for r in rows[:20]:
                lines.append(f"- {r['day_name']} {r['time']} — {r['code']} {r['name']} — {r['room']} (مجموعة {r['group']})")
            answer = "\n".join(lines)

    elif intent == "check_move":
        day = _parse_day(ent.get("day"))
        res = deterministic_check(staff=ent.get("staff"), group=ent.get("group"),
                                  room=ent.get("room"), day=day,
                                  enrolled=ent.get("minCapacity"))
        if not res["ok"]:
            res["recommendations"] = recommend_free_slots(
                staff=ent.get("staff"), group=ent.get("group"),
                enrolled=ent.get("minCapacity"), limit=3, prefer_day=day)
        else:
            res["recommendations"] = []
        facts = res
        answer = explain_check_ar(res)
        if day is None or not ent.get("staff"):
            answer = "عشان أجاوبك بدقة قولي: اسم الدكتور + اليوم + القاعة. مثال: هل ينفع أحط د. أحمد حسن في LT-101 يوم Tuesday؟\n\n" + answer

    elif intent == "find_room":
        rooms = search_rooms(minCapacity=ent.get("minCapacity"), day=ent.get("day"))
        facts = {"rooms": rooms[:10]}
        if not rooms:
            answer = "مفيش قاعة متاحة بالمواصفات دي. قلل السعة أو غيّر اليوم."
        else:
            lines = [f"وجدت {len(rooms)} قاعة متاحة:"]
            for r in rooms[:5]:
                flag = "✅ فاضية في اليوم ده" if r["free_at_requested_day"] else ("🔴 مشغولة" if r["free_at_requested_day"] is False else "")
                lines.append(f"- {r['name']} ({r['type']}) سعة {r['capacity']} {flag}")
            answer = "\n".join(lines)

    elif intent == "export":
        rows = chatbot_timetable(staff=ent.get("staff"), day=ent.get("day"))
        if ent.get("group"):
            rows = [r for r in rows if r["group"].lower() == str(ent["group"]).lower()]
        q = urlencode({k: v for k, v in {
            "staff": ent.get("staff"), "day": ent.get("day"),
            "group": ent.get("group")}.items() if v is not None})
        url = "/api/chatbot/export-ics" + ("?" + q if q else "")
        facts = {"rows": rows, "export_url": url, "count": len(rows)}
        if not rows:
            answer = "مفيش حصص مطابقة للتصدير. حدد اسم الدكتور أو اليوم، مثال: صدّر جدول Dr Ahmed."
        else:
            who = ent.get("staff") or "الجدول"
            answer = (f"📅 {who}: {len(rows)} حصة جاهزة للتصدير.\n"
                      "دوس زرار ⬇ تحميل ملف التقويم (ICS) تحت، وافتحه على الموبايل أو Google Calendar.")

    elif intent in ("occupancy", "insights"):
        occ = analytics_occupancy()
        facts = {"occupancy": occ}
        top, low = (occ[0] if occ else None), (occ[-1] if occ else None)
        lines = ["📊 الإشغال:"]
        if top:
            lines.append(f"- أكثر قاعة: {top['room_number']} ({top['pct']}%)")
        if low:
            lines.append(f"- أقل قاعة: {low['room_number']} ({low['pct']}%)")
        # simple insight: busiest day
        counts: dict[int, int] = {}
        for grid in data_store.TIMETABLE.values():
            for days in grid.values():
                for di, s in days.items():
                    if s is not None:
                        counts[di] = counts.get(di, 0) + 1
        if counts:
            b = max(counts, key=lambda k: counts[k])
            lines.append(f"- أزحم يوم: {_day_label(b)} ({counts[b]} حصة).")
        press = group_pressure(threshold=2)[:5]
        facts["pressure"] = press
        if press:
            lines.append("- تنبيه ضغط المجموعات (2+ حصص في نفس اليوم):")
            for p in press:
                lines.append(f"  • {p['group']} يوم {p['day_name']}: {p['count']} حصص — يفضل توزيع الحمل.")
        else:
            lines.append("- مفيش ضغط مجموعات (كل مجموعة عندها حصة واحدة في اليوم بالكتير).")
        answer = "\n".join(lines)
    else:
        answer = "جرب: عرض جدول دكتور / هل ينفع نقل / قاعة فاضية لـ 60 طالب / إشغال القاعات."

    return {"intent": intent, "entities": ent,
            "answer_ar": answer, "facts": facts,
            "gemini_used": bool(os.getenv("GEMINI_API_KEY"))}


# ── Group pressure: تنبيه ضغط المجموعة ────────────────────────────────────────

def group_pressure(threshold: int = 2) -> list[dict]:
    """Groups having >= threshold sessions on the same day.

    Counts lectures (rooms view) + labs (labs view) per (group, day).
    """
    buckets: dict[tuple[str, int], list[dict]] = {}
    for view in ("rooms", "labs"):
        for row_name, days in data_store.TIMETABLE.get(view, {}).items():
            for day_idx, sess in days.items():
                if sess is None:
                    continue
                buckets.setdefault((sess.group, day_idx), []).append({
                    "code": sess.code, "name": sess.name,
                    "room": row_name, "staff": sess.staff,
                })
    out = [{"group": g, "day": d, "day_name": _day_label(d),
            "count": len(s), "sessions": s}
           for (g, d), s in buckets.items() if len(s) >= threshold]
    out.sort(key=lambda o: o["count"], reverse=True)
    return out


@router.get("/api/chatbot/pressure")
def pressure(threshold: int = 2):
    """List overloaded groups (default: 2+ sessions in the same day)."""
    return group_pressure(threshold=threshold)


# ── ICS export: تصدير الجدول للموبايل / Google Calendar ───────────────────────

def _upcoming_monday() -> date:
    today = date.today()
    return today + timedelta(days=(0 - today.weekday()) % 7)


def _ics_escape(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;").replace("\n", "\\n")


def _to_ics(rows: list[dict]) -> str:
    """Build an ICS calendar (2-hour sessions) for the upcoming Mon–Fri week."""
    monday = _upcoming_monday()
    now = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//BUA//SCH Chatbot//AR",
             "CALSCALE:GREGORIAN", "METHOD:PUBLISH"]
    for r in rows:
        try:
            day_idx = int(r.get("day", 0))
        except (TypeError, ValueError):
            day_idx = 0
        day_idx = max(0, min(day_idx, 4))
        ev_date = monday + timedelta(days=day_idx)
        start_raw = (r.get("time") or "08:00").split("-")[0].strip() or "08:00"
        try:
            hh, mm = (start_raw.split(":") + ["0"])[:2]
            h, m = int(hh), int(mm)
        except ValueError:
            h, m = 8, 0
        start = datetime.combine(ev_date, time(h, m))
        end = start + timedelta(hours=2)
        lines += [
            "BEGIN:VEVENT",
            f"UID:{r.get('id', 'ev')}-{ev_date.isoformat()}@bua.edu.eg",
            f"DTSTAMP:{now}",
            f"DTSTART:{start.strftime('%Y%m%dT%H%M%S')}",
            f"DTEND:{end.strftime('%Y%m%dT%H%M%S')}",
            f"SUMMARY:{_ics_escape(r.get('code', ''))} {_ics_escape(r.get('name', ''))}",
            f"LOCATION:{_ics_escape(r.get('room', ''))}",
            f"DESCRIPTION:{_ics_escape(r.get('staff', ''))} — {_ics_escape(r.get('group', ''))}",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


@router.get("/api/chatbot/export-ics")
def export_ics(staff: Optional[str] = None, group: Optional[str] = None,
               room: Optional[str] = None, day: Optional[Any] = None):
    """Download matching sessions as an .ics calendar file."""
    rows = chatbot_timetable(staff=staff, day=_parse_day(day))
    if group:
        rows = [r for r in rows if r["group"].lower() == group.lower()]
    if room:
        rows = [r for r in rows if r["room"].lower() == room.lower()]
    ics = _to_ics(rows)
    return Response(content=ics, media_type="text/calendar",
                    headers={"Content-Disposition": 'attachment; filename="timetable.ics"'})


# ── Image analysis: صورة جدول → معلومات + فحص ضد الداتا الحقيقية ─────────────
# Gemini vision = العين (يستخرج الحصص من الصورة فقط).
# الفحص والحقائق دائماً من data_store — نفس قاعدة "ممنوع الهلوسة".

_IMAGE_PROMPT = (
    "You are reading a dense university timetable grid photo. "
    "Transcribe EVERY readable lecture cell, row by row, without skipping any. "
    "For each cell return an object like "
    '{"course":"Database","staff":"Ahmed Hassan","day":"Tuesday","time":"11:00","room":"A101"}. '
    "Rules: map the column headers to English days (Sunday/Monday/Tuesday/Wednesday/Thursday); "
    "time as HH:MM 24h if visible else null; use null for any unreadable field; "
    "never invent entries that are not visible. "
    "Return ONLY a JSON array, no other text. If truly nothing is readable, return []."
)

# Cache for auto-detected models (refreshed on server restart).
_AUTO_MODELS: list[str] | None = None


def _pick_models(key: str) -> list[str]:
    """Ask Google which models exist and prefer the newest flash ones.

    Hardcoded names rot when Google retires models (HTTP 404), so we
    auto-detect instead. Falls back to [] (caller tries known names).
    """
    import re
    global _AUTO_MODELS
    if _AUTO_MODELS is not None:
        return _AUTO_MODELS
    try:
        req = urllib.request.Request(
            "https://generativelanguage.googleapis.com/v1beta/models?key=" + key + "&pageSize=100")
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        names = [m.get("name", "").replace("models/", "")
                 for m in data.get("models", []) if m.get("name")]

        def rank(n: str) -> tuple:
            m = re.search(r"(\d+)(?:\.(\d+))?", n)
            return (int(m.group(1)) if m else 0, int(m.group(2) or 0) if m else 0,
                    0 if "pro" in n.lower() else 1)

        flash = [n for n in names if "flash" in n.lower() and "exp" not in n.lower()]
        flash.sort(key=rank, reverse=True)
        _AUTO_MODELS = flash[:3]
        print(f"[chatbot] auto-detected vision models: {_AUTO_MODELS}")
    except Exception as e:  # noqa: BLE001 - offline? just use hardcoded names
        print(f"[chatbot] list models failed: {e}")
        _AUTO_MODELS = []
    return _AUTO_MODELS


def _split_tiles(content: bytes, mime: str) -> tuple[list[tuple[bytes, str, str]], bool, str]:
    """Split a dense/large sheet into overlapping tiles so cells stay legible.

    Returns (tiles, tiled, note) where each tile is (bytes, mime, label).
    Small images go through as a single shot. Needs Pillow; without it,
    falls back to single-shot with a note.
    """
    try:
        from PIL import Image
    except ImportError:
        return [(content, mime, "full")], False, "نصيحة: ثبتي Pillow (pip install pillow) لتقطيع الصور الكبيرة تلقائياً."
    import io as _io
    try:
        img = Image.open(_io.BytesIO(content)).convert("RGB")
    except Exception:
        return [(content, mime, "full")], False, ""
    w, h = img.size
    if max(w, h) <= 1600:
        return [(content, mime, "full")], False, ""
    cols = 2 if w <= 2600 else 3
    rows = 2 if h <= 2000 else 3
    ov = 0.06  # 6% overlap so border cells are not cut
    tiles: list[tuple[bytes, str, str]] = []
    for r in range(rows):
        for c in range(cols):
            x0 = max(0, int(c * w / cols - w * ov))
            x1 = min(w, int((c + 1) * w / cols + w * ov))
            y0 = max(0, int(r * h / rows - h * ov))
            y1 = min(h, int((r + 1) * h / rows + h * ov))
            buf = _io.BytesIO()
            img.crop((x0, y0, x1, y1)).save(buf, format="JPEG", quality=92)
            label = f"الجزء (صف {r + 1}/{rows}، عمود {c + 1}/{cols})"
            tiles.append((buf.getvalue(), "image/jpeg", label))
    return tiles, True, ""


def _gemini_vision_extract(content: bytes, mime: str, context: str = "") -> Optional[list]:
    """Try vision models in order; raise RuntimeError with the real cause."""
    import urllib.error
    key = os.getenv("GEMINI_API_KEY", "")
    if not key:
        return None
    models = [m for m in [os.getenv("GEMINI_MODEL", ""), *_pick_models(key),
                          "gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"] if m]
    seen, ordered = set(), []
    for m in models:
        if m not in seen:
            seen.add(m)
            ordered.append(m)
    last_err = "no response"
    prompt = _IMAGE_PROMPT + (f" NOTE: this image is {context} of a larger timetable; "
                              "transcribe only the cells visible here." if context else "")
    for model in ordered:
        for attempt in range(3):
            try:
                payload = json.dumps({
                    "contents": [{"parts": [
                        {"text": prompt},
                        {"inline_data": {"mime_type": mime,
                                         "data": base64.b64encode(content).decode()}},
                    ]}],
                    "generationConfig": {"temperature": 0, "maxOutputTokens": 8192},
                }).encode()
                req = urllib.request.Request(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key=" + key,
                    data=payload, headers={"Content-Type": "application/json"}, method="POST")
                with urllib.request.urlopen(req, timeout=60) as resp:
                    data = json.loads(resp.read().decode())
                raw = data["candidates"][0]["content"]["parts"][0]["text"]
                raw = raw.replace("```json", "").replace("```", "").strip()
                start, end = raw.find("["), raw.rfind("]")
                if start == -1 or end == -1:
                    return []
                parsed = json.loads(raw[start:end + 1])
                return parsed if isinstance(parsed, list) else []
            except urllib.error.HTTPError as e:
                try:
                    body = e.read().decode()[:300]
                except Exception:
                    body = ""
                if e.code == 503 and attempt < 2:
                    # Overloaded right now ("try again later") — wait and retry same model.
                    import time as _tmod
                    print(f"[chatbot] vision {model} overloaded (503), retry {attempt + 1}/2...")
                    _tmod.sleep(5)
                    continue
                print(f"[chatbot] vision {model} failed: HTTP {e.code}: {body}")
                last_err = f"HTTP {e.code} {body}"
                break
            except Exception as e:  # noqa: BLE001 - network/DNS etc.
                print(f"[chatbot] vision {model} failed: {e}")
                last_err = str(e)[:200]
                break
    raise RuntimeError(last_err)


@router.post("/api/chatbot/analyze-image")
async def analyze_image(file: UploadFile = File(...)):
    """Upload a timetable photo → extract entries → verify each vs live data."""
    base = {"intent": "image", "entities": {}, "facts": {}, "gemini_used": False}
    if not (file.content_type or "").startswith("image/"):
        return {**base, "answer_ar": "ابعت صورة (PNG/JPG) لجدول أو ورقة مواعيد."}
    content = await file.read()
    if len(content) > 5 * 1024 * 1024:
        return {**base, "answer_ar": "الصورة كبيرة (أكتر من 5MB). ابعت نسخة أصغر."}
    if not os.getenv("GEMINI_API_KEY"):
        return {**base, "answer_ar": (
            "تحليل الصور محتاج GEMINI_API_KEY في الباك (ملف .env). "
            "من غيره مقدرش أقرا الصور — ابعت سؤال نصي عادي.")}
    tiles, tiled, tile_note = _split_tiles(content, file.content_type or "image/png")
    items: list = []
    tile_errors = 0
    try:
        for tile_bytes, tile_mime, label in tiles:
            try:
                part = _gemini_vision_extract(
                    tile_bytes, tile_mime, context=label if tiled else "")
            except Exception as e:  # noqa: BLE001 - one bad tile must not kill the rest
                print(f"[chatbot] tile {label} failed: {e}")
                tile_errors += 1
                continue
            if part:
                items.extend(part)
    except Exception as e:  # noqa: BLE001 - report the real cause, in Arabic
        detail = str(e)
        print(f"[chatbot] analyze-image failed: {detail}")
        if "403" in detail or "API key not valid" in detail or "API_KEY_INVALID" in detail:
            msg = ("Gemini رفض المفتاح (403). اتأكدي إن Generative Language API مفعلة على المشروع "
                   "وإن الـ key restrictions = None للتجربة.")
        elif "503" in detail or "high demand" in detail or "UNAVAILABLE" in detail:
            msg = ("جوجل مضغوط دلوقتي والطلب اترفض مؤقتاً (503). استني دقيقة أو اتنين وجربي نفس الصورة تاني — "
                   "الباك بيعيد المحاولة لوحده 3 مرات قبل ما يفشل.")
        elif "400" in detail or "INVALID_ARGUMENT" in detail:
            if "image" in detail.lower():
                msg = "الصورة مش صالحة أو تالفة. ابعت PNG/JPG سليم (يفضل سكرين شوت مباشر مش تصوير شاشة)."
            else:
                msg = "Google رفض الطلب (400). غالباً المفتاح مقيد أو الـ API مش مفعلة على المشروع."
        elif "404" in detail:
            msg = ("مفيش موديل متاح من اللي الباك يعرفهم. حطي في .env سطر GEMINI_MODEL باسم موديل شغال "
                   "(مثال: gemini-2.5-flash) واعملي restart وجربي تاني.")
        else:
            msg = "فشل تحليل الصورة. جرب صورة أوضح أو سؤال نصي."
        return {**base, "answer_ar": msg}
    # Dedupe overlapping tiles: same (course, staff, day, time, room).
    seen_keys, merged = set(), []
    for it in items:
        if not isinstance(it, dict):
            continue
        k = tuple(str(it.get(f) or "").strip().lower()
                  for f in ("course", "staff", "day", "time", "room"))
        if k in seen_keys:
            continue
        seen_keys.add(k)
        merged.append(it)
    items = merged
    if not items:
        if tile_errors:
            return {**base, "answer_ar": "فشل تحليل كل أجزاء الصورة (Gemini). اتأكدي من المفتاح والـ API وجربي تاني."}
        return {**base, "answer_ar": (
            "مفيش حصص واضحة في الصورة — الخلايا صغيرة على القراءة. "
            "ابعتي crop مكبر لجزء واحد (يوم أو دكتور) أو الملف الأصلي للجدول."), "gemini_used": True}
    head = (f"📷 حللت الصورة على {len(tiles)} أجزاء (عشان الخلايا صغيرة) ولقيت {min(len(items), 20)} حصة، "
            "وفحصت كل واحدة ضد الجدول الحقيقي:" if tiled
            else f"📷 لقيت {min(len(items), 10)} حصة في الصورة، وفحصت كل واحدة ضد الجدول الحقيقي:")
    if tile_note:
        head += "\n" + tile_note
    lines = [head]
    facts_items = []
    ok_n = 0
    n_shown = 0
    for it in items[:20]:
        if not isinstance(it, dict):
            continue
        staff = (it.get("staff") or "").strip() or None
        room = (it.get("room") or "").strip() or None
        course = (it.get("course") or "").strip()
        day = _parse_day(it.get("day"))
        match = _find_matching_session(staff, room, day)
        if match is not None:
            # Entry mirrors reality — must NOT be flagged as busy with itself.
            ok_n += 1
            n_shown += 1
            status = f"✅ مطابق للجدول الحقيقي ({match.code} — {match.name})."
            res = {"ok": True, "conflicts": []}
        else:
            res = deterministic_check(staff=staff, room=room, day=day)
            n_shown += 1
            if res["ok"]:
                ok_n += 1
                status = "✅ سليم — مفيش تعارض."
            else:
                status = "❌ " + "; ".join(c["description"] for c in res["conflicts"][:2])
        label = " — ".join(x for x in
                           [course, staff or "",
                            _day_label(day) if day is not None else "يوم غير واضح",
                            room or ""] if x)
        lines.append(f"- {label}\n  {status}")
        facts_items.append({**it, "check": res})
    lines.append(f"\nالخلاصة: {ok_n} سليم / {n_shown - ok_n} متعارض من {n_shown} حصص.")
    return {"intent": "image", "entities": {"count": len(items)},
            "answer_ar": "\n".join(lines),
            "facts": {"items": facts_items}, "gemini_used": True}
