# Deterministic conflict engine — SCH-FR-05 baseline for Backend (Python).
# Rule: same-day + same-slot overlap. No AI / no ML here.
# Backend can port this 1:1 into Express/NestJS/FastAPI. Messages are bilingual.
# Path: sch-chatbot-starter/backend-contract/conflict_engine.py

from typing import Dict, List, Any


def _groups_of_section(section_id: int, section_groups: List[Dict]) -> List[int]:
    return [r["student_group_id"] for r in section_groups if r["section_id"] == section_id]


def _lookup(table: List[Dict], _id: Any):
    for r in table or []:
        if r.get("id") == _id:
            return r
    return None


def check_move(candidate: Dict, ctx: Dict) -> Dict:
    """candidate: {section_id, staff_id, room_id, day_id, time_slot_id,
                   exclude_allocation_id?, required_equipment_id?,
                   room_type_required?, duration_slots? (default 1)}
       ctx: {allocations, rooms, closures, availability, roomEquipment,
             section_groups, groupSizes, holidays?, slots?}
       returns: {ok: bool, conflicts: [{conflict_type, message_en, message_ar}]}
    """
    conflicts: List[Dict] = []

    allocations = ctx.get("allocations", [])
    rooms = ctx.get("rooms", [])
    closures = ctx.get("closures", [])
    availability = ctx.get("availability", [])
    room_equipment = ctx.get("roomEquipment", ctx.get("room_equipment", []))
    section_groups = ctx.get("section_groups", ctx.get("sectionGroups", []))
    group_sizes = ctx.get("groupSizes", ctx.get("group_sizes", {}))
    holidays = ctx.get("holidays", [])
    slots = ctx.get("slots", [])

    duration = int(candidate.get("duration_slots", 1) or 1)
    cand_slots = [candidate["time_slot_id"] + i for i in range(duration)]

    # helper: names for messages (optional enrichment)
    staff = _lookup(ctx.get("staff", []), candidate.get("staff_id")) or {}
    room = _lookup(rooms, candidate.get("room_id")) or {}
    day = _lookup(ctx.get("days", []), candidate.get("day_id")) or {}
    staff_name = f"{staff.get('first_name','')} {staff.get('last_name','')}".strip() or f"#{candidate.get('staff_id')}"
    room_name = room.get("room_number", f"#{candidate.get('room_id')}")
    day_name = day.get("day_name", f"day #{candidate.get('day_id')}")

    def slot_label(sid):
        s = _lookup(slots, sid)
        if s:
            return f"{s.get('start_time')}-{s.get('end_time')}"
        return f"slot #{sid}"

    # 0. HOLIDAY / invalid day
    if any(h.get("day_id") == candidate["day_id"] for h in holidays):
        conflicts.append({
            "conflict_type": "HOLIDAY",
            "message_en": f"{day_name} is a holiday — no teaching allowed.",
            "message_ar": f"يوم {day_name} أجازة رسمية — مينفعش تحط فيه أي محاضرة.",
        })

    # 0b. DURATION_OVERFLOW — consecutive slots must exist
    if slots and duration > 1:
        slot_ids = [s.get("id") for s in slots]
        for sid in cand_slots:
            if sid not in slot_ids:
                conflicts.append({
                    "conflict_type": "DURATION_OVERFLOW",
                    "message_en": f"Duration {duration} slots overflows timetable (slot #{sid} does not exist).",
                    "message_ar": f"المدة {duration} حصص بتخرج بره الجدول (مفيش حصة برقم {sid}).",
                })
                break

    # expand same-slot allocations across all candidate slots (consecutive duration)
    same_slot = [
        a for a in allocations
        if a.get("day_id") == candidate["day_id"]
        and a.get("time_slot_id") in cand_slots
        and a.get("id") != candidate.get("exclude_allocation_id")
    ]

    # 1. STAFF_BUSY
    clash = next((a for a in same_slot if a.get("staff_id") == candidate["staff_id"]), None)
    if clash:
        conflicts.append({
            "conflict_type": "STAFF_BUSY",
            "message_en": f"Staff {staff_name} already teaches allocation #{clash.get('id')} at {day_name} {slot_label(clash.get('time_slot_id'))}.",
            "message_ar": f"الدكتور {staff_name} عنده محاضرة تانية في نفس الوقت ({day_name} {slot_label(clash.get('time_slot_id'))}) — رقم الحجز {clash.get('id')}.",
        })

    # 2. ROOM_BUSY
    clash = next((a for a in same_slot if a.get("room_id") == candidate["room_id"]), None)
    if clash:
        conflicts.append({
            "conflict_type": "ROOM_BUSY",
            "message_en": f"Room {room_name} is occupied by allocation #{clash.get('id')} at {day_name} {slot_label(clash.get('time_slot_id'))}.",
            "message_ar": f"القاعة/المعمل {room_name} محجوزة في نفس الوقت ({day_name} {slot_label(clash.get('time_slot_id'))}) — رقم الحجز {clash.get('id')}.",
        })

    # 3. GROUP_CLASH
    cand_groups = _groups_of_section(candidate["section_id"], section_groups)
    group_clash = None
    for a in same_slot:
        g = _groups_of_section(a.get("section_id"), section_groups)
        if any(x in cand_groups for x in g):
            group_clash = a
            break
    if group_clash:
        conflicts.append({
            "conflict_type": "GROUP_CLASH",
            "message_en": f"Student group already has allocation #{group_clash.get('id')} at {day_name} {slot_label(group_clash.get('time_slot_id'))}.",
            "message_ar": f"المجموعة الطلابية عندها محاضرة تانية في نفس الوقت ({day_name} {slot_label(group_clash.get('time_slot_id'))}) — رقم الحجز {group_clash.get('id')}.",
        })

    # 4. CAPACITY
    max_group = max([int(group_sizes.get(g, 0) or 0) for g in cand_groups] + [0])
    if room and max_group > int(room.get("capacity", 0) or 0):
        conflicts.append({
            "conflict_type": "CAPACITY",
            "message_en": f"Room {room_name} capacity {room.get('capacity')} < group size {max_group}.",
            "message_ar": f"عدد الطلاب ({max_group}) أكبر من سعة القاعة {room_name} ({room.get('capacity')}).",
        })

    # 5. ROOM_TYPE_MISMATCH (e.g. practical needs lab)
    required_type = candidate.get("room_type_required") or candidate.get("required_room_type")
    if required_type and room and room.get("room_type") and room.get("room_type") != required_type:
        conflicts.append({
            "conflict_type": "ROOM_TYPE_MISMATCH",
            "message_en": f"Room {room_name} type '{room.get('room_type')}' != required '{required_type}'.",
            "message_ar": f"نوع القاعة {room_name} ({room.get('room_type')}) مش مناسب — المطلوب: {required_type}.",
        })

    # 6. CLOSURE (check every slot in duration)
    for sid in cand_slots:
        if any(c.get("room_id") == candidate["room_id"] and c.get("day_id") == candidate["day_id"] and c.get("time_slot_id") == sid for c in closures):
            conflicts.append({
                "conflict_type": "CLOSURE",
                "message_en": f"Room {room_name} is closed at {day_name} {slot_label(sid)}.",
                "message_ar": f"القاعة {room_name} مغلقة في الوقت ده ({day_name} {slot_label(sid)}).",
            })
            break

    # 7. AVAILABILITY (staff ban)
    for sid in cand_slots:
        if any(c.get("staff_id") == candidate["staff_id"] and c.get("day_id") == candidate["day_id"] and c.get("time_slot_id") == sid for c in availability):
            conflicts.append({
                "conflict_type": "AVAILABILITY",
                "message_en": f"Staff {staff_name} marked unavailable at {day_name} {slot_label(sid)}.",
                "message_ar": f"الدكتور {staff_name} غير متاح في الوقت ده ({day_name} {slot_label(sid)}).",
            })
            break

    # 8. EQUIPMENT
    req_eq = candidate.get("required_equipment_id")
    if req_eq:
        has = any(e.get("room_id") == candidate["room_id"] and e.get("equipment_id") == req_eq and int(e.get("quantity", 0) or 0) > 0 for e in room_equipment)
        if not has:
            conflicts.append({
                "conflict_type": "EQUIPMENT",
                "message_en": f"Room {room_name} lacks required equipment #{req_eq}.",
                "message_ar": f"القاعة {room_name} مفيهاش المعدات المطلوبة (كود {req_eq}).",
            })

    return {"ok": len(conflicts) == 0, "conflicts": conflicts}


def recommend_alternatives(candidate: Dict, ctx: Dict, limit: int = 3) -> List[Dict]:
    """Deterministic baseline for SCH-FR-06: try every day/slot/room, keep feasible, score by waste."""
    out = []
    days = ctx.get("days", [])
    slots = ctx.get("slots", [])
    rooms = ctx.get("rooms", [])
    section_groups = ctx.get("section_groups", ctx.get("sectionGroups", []))
    group_sizes = ctx.get("groupSizes", ctx.get("group_sizes", {}))
    cand_groups = _groups_of_section(candidate["section_id"], section_groups)
    max_group = max([int(group_sizes.get(g, 0) or 0) for g in cand_groups] + [0])

    for d in days:
        for s in slots:
            for r in rooms:
                trial = {**candidate, "day_id": d.get("id"), "time_slot_id": s.get("id"), "room_id": r.get("id")}
                res = check_move(trial, ctx)
                if not res["ok"]:
                    continue
                waste = int(r.get("capacity", 0) or 0) - max_group
                bonus = -10 if d.get("id") == candidate.get("day_id") else 0
                out.append({
                    "day_id": d.get("id"), "day_name": d.get("day_name"),
                    "time_slot_id": s.get("id"), "start_time": s.get("start_time"), "end_time": s.get("end_time"),
                    "room_id": r.get("id"), "room_number": r.get("room_number"),
                    "score": waste + bonus,
                    "explanation_en": f"Capacity waste {waste}, {'same day' if bonus else 'different day'}.",
                    "explanation_ar": f"فرق السعة {waste}، {'نفس اليوم' if bonus else 'يوم مختلف'}.",
                })
    out.sort(key=lambda x: x["score"])
    return out[:limit]
