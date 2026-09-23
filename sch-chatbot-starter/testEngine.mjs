import { checkMove } from "./conflictEngine.js";
import { recommendAlternatives, occupancy } from "./recommender.js";
import * as mock from "./mockData.js";

const ctx = {
  allocations: mock.sch_allocation,
  rooms: mock.sch_room, days: mock.sch_day, slots: mock.sch_time_slot,
  closures: mock.sch_room_closure, availability: mock.sch_availability_constraint,
  roomEquipment: mock.sch_room_equipment,
};

// Case 1: move DB (staff 1) to Tuesday 11:00 room B203 -> expect STAFF_BUSY / AVAILABILITY / GROUP_CLASH
const r1 = checkMove({ section_id: 1, staff_id: 1, room_id: 4, day_id: 3, time_slot_id: 2 }, ctx);
console.log("CASE1 ok=", r1.ok, "types=", r1.conflicts.map(c => c.conflict_type).join(","));

// Case 2: capacity fail: group 55 into Lab2 (cap 30)
const r2 = checkMove({ section_id: 1, staff_id: 2, room_id: 3, day_id: 4, time_slot_id: 3 }, ctx);
console.log("CASE2 ok=", r2.ok, "types=", r2.conflicts.map(c => c.conflict_type).join(","));

// Case 3: free slot should pass
const r3 = checkMove({ section_id: 1, staff_id: 2, room_id: 4, day_id: 4, time_slot_id: 3 }, ctx);
console.log("CASE3 ok=", r3.ok);

// Alternatives for failed case
console.log("ALTS=", recommendAlternatives({ section_id: 1, staff_id: 1, room_id: 4, day_id: 3, time_slot_id: 2 }, ctx, 3).length);
// Occupancy
console.log("OCC=", JSON.stringify(occupancy(ctx.allocations, ctx.rooms, ctx.days, ctx.slots)));

if (r1.ok) throw new Error("CASE1 should conflict");
if (r2.conflicts.every(c => c.conflict_type !== "CAPACITY")) throw new Error("CASE2 should have CAPACITY");
if (!r3.ok) throw new Error("CASE3 should pass");
console.log("ALL_ENGINE_TESTS_PASSED");
