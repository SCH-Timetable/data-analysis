# Test matrix for SCH-FR-05 — run: python test_conflict_engine.py
# Path: sch-chatbot-starter/backend-contract/test_conflict_engine.py
import sys, io
# Windows console fix for Arabic output
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
from conflict_engine import check_move, recommend_alternatives

days = [{"id": 1, "day_name": "Sunday"}, {"id": 2, "day_name": "Monday"},
        {"id": 3, "day_name": "Tuesday"}, {"id": 4, "day_name": "Wednesday"}]
slots = [{"id": 1, "start_time": "09:00", "end_time": "11:00"},
         {"id": 2, "start_time": "11:00", "end_time": "13:00"},
         {"id": 3, "start_time": "13:00", "end_time": "15:00"}]
rooms = [{"id": 1, "room_number": "A101", "capacity": 60, "room_type": "classroom"},
         {"id": 3, "room_number": "Lab 2", "capacity": 30, "room_type": "lab"},
         {"id": 4, "room_number": "B203", "capacity": 80, "room_type": "classroom"}]
staff = [{"id": 1, "first_name": "Ahmed", "last_name": "Hassan"}]
ctx_base = {
    "allocations": [
        {"id": 1, "section_id": 1, "staff_id": 1, "room_id": 1, "day_id": 2, "time_slot_id": 1},
        {"id": 3, "section_id": 3, "staff_id": 2, "room_id": 4, "day_id": 3, "time_slot_id": 2},
    ],
    "rooms": rooms, "days": days, "slots": slots, "staff": staff,
    "closures": [{"room_id": 3, "day_id": 3, "time_slot_id": 1}],
    "availability": [{"staff_id": 1, "day_id": 3, "time_slot_id": 2}],
    "roomEquipment": [{"room_id": 3, "equipment_id": 1, "quantity": 25}],
    "section_groups": [{"section_id": 1, "student_group_id": 1}, {"section_id": 3, "student_group_id": 1}],
    "groupSizes": {1: 55},
    "holidays": [],
}

tests = [
    ("ROOM taken -> ROOM_BUSY/GROUP_CLASH", {"section_id": 1, "staff_id": 1, "room_id": 4, "day_id": 3, "time_slot_id": 2}, ["ROOM_BUSY", "GROUP_CLASH", "AVAILABILITY"]),
    ("Too many students -> CAPACITY", {"section_id": 1, "staff_id": 2, "room_id": 3, "day_id": 4, "time_slot_id": 3}, ["CAPACITY"]),
    ("Free slot -> ok", {"section_id": 1, "staff_id": 2, "room_id": 4, "day_id": 4, "time_slot_id": 3}, []),
    ("Closed room -> CLOSURE", {"section_id": 1, "staff_id": 2, "room_id": 3, "day_id": 3, "time_slot_id": 1}, ["CLOSURE"]),
    ("Lab needs PCs in A101 -> EQUIPMENT", {"section_id": 1, "staff_id": 2, "room_id": 1, "day_id": 4, "time_slot_id": 3, "required_equipment_id": 1}, ["EQUIPMENT"]),
    ("Practical in classroom -> ROOM_TYPE_MISMATCH", {"section_id": 1, "staff_id": 2, "room_id": 4, "day_id": 4, "time_slot_id": 3, "room_type_required": "lab"}, ["ROOM_TYPE_MISMATCH"]),
]

failed = 0
for name, cand, must_contain in tests:
    r = check_move(cand, ctx_base)
    types = [c["conflict_type"] for c in r["conflicts"]]
    ok = all(t in types for t in must_contain) and (r["ok"] == (len(must_contain) == 0))
    # print bilingual message like admin will see
    print(f"{'PASS' if ok else 'FAIL'}: {name} -> ok={r['ok']} types={types}")
    for c in r["conflicts"]:
        print(f"   - [{c['conflict_type']}] {c['message_ar']}")
    if not ok:
        failed += 1

alts = recommend_alternatives({"section_id": 1, "staff_id": 1, "room_id": 4, "day_id": 3, "time_slot_id": 2}, ctx_base, 3)
print(f"ALTS={len(alts)}")
for a in alts:
    print(f"   - {a['day_name']} {a['start_time']}-{a['end_time']} in {a['room_number']} ({a['explanation_ar']})")

if failed:
    raise SystemExit(f"{failed} TESTS FAILED")
print("ALL_ENGINE_TESTS_PASSED")
