// Deterministic conflict engine — local baseline for SCH-FR-05.
// Same-day + same-slot overlap. No AI here. Backend will replace it later.
// sch-chatbot-starter/conflictEngine.js
import { groupSizes, sch_section_student_group } from "./mockData.js";

function groupsOfSection(section_id) {
  return sch_section_student_group
    .filter((r) => r.section_id === section_id)
    .map((r) => r.student_group_id);
}

export function checkMove(candidate, ctx) {
  // candidate: {section_id, staff_id, room_id, day_id, time_slot_id, exclude_allocation_id?, required_equipment_id?}
  // ctx: {allocations, rooms, closures, availability, roomEquipment}
  const conflicts = [];
  const sameSlot = ctx.allocations.filter(
    (a) =>
      a.day_id === candidate.day_id &&
      a.time_slot_id === candidate.time_slot_id &&
      a.id !== candidate.exclude_allocation_id
  );

  // 1. STAFF_BUSY
  const staffClash = sameSlot.find((a) => a.staff_id === candidate.staff_id);
  if (staffClash)
    conflicts.push({
      conflict_type: "STAFF_BUSY",
      description: `Staff #${candidate.staff_id} already teaches allocation #${staffClash.id} at this day/slot.`,
    });

  // 2. ROOM_BUSY
  const roomClash = sameSlot.find((a) => a.room_id === candidate.room_id);
  if (roomClash)
    conflicts.push({
      conflict_type: "ROOM_BUSY",
      description: `Room #${candidate.room_id} is occupied by allocation #${roomClash.id} at this day/slot.`,
    });

  // 3. GROUP_CLASH
  const candGroups = groupsOfSection(candidate.section_id);
  const groupClash = sameSlot.find((a) => {
    const g = groupsOfSection(a.section_id);
    return g.some((x) => candGroups.includes(x));
  });
  if (groupClash)
    conflicts.push({
      conflict_type: "GROUP_CLASH",
      description: `Student group already has allocation #${groupClash.id} at this day/slot.`,
    });

  // 4. CAPACITY (SCH-FR-05)
  const room = ctx.rooms.find((r) => r.id === candidate.room_id);
  const maxGroup = Math.max(...candGroups.map((g) => groupSizes[g] || 0), 0);
  if (room && maxGroup > room.capacity)
    conflicts.push({
      conflict_type: "CAPACITY",
      description: `Room capacity ${room.capacity} < group size ${maxGroup}.`,
    });

  // 5. CLOSURE
  const closed = (ctx.closures || []).some(
    (c) => c.room_id === candidate.room_id && c.day_id === candidate.day_id && c.time_slot_id === candidate.time_slot_id
  );
  if (closed)
    conflicts.push({ conflict_type: "CLOSURE", description: `Room #${candidate.room_id} is closed at this day/slot.` });

  // 6. AVAILABILITY (staff ban)
  const banned = (ctx.availability || []).some(
    (c) => c.staff_id === candidate.staff_id && c.day_id === candidate.day_id && c.time_slot_id === candidate.time_slot_id
  );
  if (banned)
    conflicts.push({ conflict_type: "AVAILABILITY", description: `Staff #${candidate.staff_id} marked unavailable at this day/slot.` });

  // 7. EQUIPMENT (optional, for labs)
  if (candidate.required_equipment_id) {
    const has = (ctx.roomEquipment || []).some(
      (e) => e.room_id === candidate.room_id && e.equipment_id === candidate.required_equipment_id && e.quantity > 0
    );
    if (!has)
      conflicts.push({ conflict_type: "EQUIPMENT", description: `Room #${candidate.room_id} lacks required equipment.` });
  }

  return { ok: conflicts.length === 0, conflicts };
}
