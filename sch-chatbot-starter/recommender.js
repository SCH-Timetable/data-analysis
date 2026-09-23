// Ranked alternatives + occupancy/insights — SCH-FR-06 / SCH-FR-10 baseline.
// sch-chatbot-starter/recommender.js
import { checkMove } from "./conflictEngine.js";
import { groupSizes, sch_section_student_group } from "./mockData.js";

function groupsOfSection(section_id) {
  return sch_section_student_group.filter((r) => r.section_id === section_id).map((r) => r.student_group_id);
}

// Try every day/slot/room, keep feasible, score them.
export function recommendAlternatives(candidate, ctx, limit = 3) {
  const out = [];
  for (const d of ctx.days) {
    for (const s of ctx.slots) {
      for (const r of ctx.rooms) {
        const trial = { ...candidate, day_id: d.id, time_slot_id: s.id, room_id: r.id };
        const res = checkMove(trial, ctx);
        if (!res.ok) continue;
        // score: smaller waste = better, prefer same day as requested
        const maxGroup = Math.max(...groupsOfSection(candidate.section_id).map((g) => groupSizes[g] || 0), 0);
        const waste = r.capacity - maxGroup;
        const sameDayBonus = d.id === candidate.day_id ? -10 : 0;
        out.push({
          day_id: d.id, day_name: d.day_name,
          time_slot_id: s.id, start_time: s.start_time, end_time: s.end_time,
          room_id: r.id, room_number: r.room_number,
          score: waste + sameDayBonus,
          explanation: `Capacity fit waste ${waste}, ${d.id === candidate.day_id ? "same day" : "different day"}.`,
        });
      }
    }
  }
  return out.sort((a, b) => a.score - b.score).slice(0, limit);
}

export function occupancy(allocations, rooms, days, slots) {
  const total = days.length * slots.length;
  return rooms.map((r) => {
    const used = allocations.filter((a) => a.room_id === r.id).length;
    return { room_id: r.id, room_number: r.room_number, used, total, pct: total ? Math.round((used / total) * 100) : 0 };
  }).sort((a, b) => b.pct - a.pct);
}

export function dayLoad(allocations, groupId, dayId) {
  return allocations.filter((a) => {
    const inGroup = sch_section_student_group.some((x) => x.section_id === a.section_id && x.student_group_id === groupId);
    return inGroup && a.day_id === dayId;
  }).length;
}
