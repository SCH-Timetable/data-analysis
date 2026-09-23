// Mock data mirrors SCH schema table names 1:1.
// Replace with real Backend responses later — same shape.
// sch-chatbot-starter/mockData.js

export const sch_day = [
  { id: 1, day_name: "Sunday" },
  { id: 2, day_name: "Monday" },
  { id: 3, day_name: "Tuesday" },
  { id: 4, day_name: "Wednesday" },
  { id: 5, day_name: "Thursday" },
];

export const sch_time_slot = [
  { id: 1, start_time: "09:00", end_time: "11:00" },
  { id: 2, start_time: "11:00", end_time: "13:00" },
  { id: 3, start_time: "13:00", end_time: "15:00" },
  { id: 4, start_time: "15:00", end_time: "17:00" },
];

export const sch_building = [
  { id: 1, building_name: "A" },
  { id: 2, building_name: "B" },
];

export const sch_room = [
  { id: 1, building_id: 1, room_number: "A101", capacity: 60 },
  { id: 2, building_id: 1, room_number: "A102", capacity: 40 },
  { id: 3, building_id: 2, room_number: "Lab 2", capacity: 30 },
  { id: 4, building_id: 2, room_number: "B203", capacity: 80 },
];

export const sch_staff = [
  { id: 1, department_id: 1, first_name: "Ahmed", last_name: "Hassan" },
  { id: 2, department_id: 1, first_name: "Sara", last_name: "Ali" },
];

export const sch_course = [
  { id: 1, department_id: 1, course_name: "Database", course_code: "CS301" },
  { id: 2, department_id: 1, course_name: "AI", course_code: "CS302" },
  { id: 3, department_id: 1, course_name: "Networks", course_code: "CS303" },
];

export const sch_section = [
  { id: 1, course_id: 1, section_number: "DB-S1" },
  { id: 2, course_id: 2, section_number: "AI-S1" },
  { id: 3, course_id: 3, section_number: "NET-S1" },
];

export const sch_student_group = [
  { id: 1, group_name: "Level 3 - G1" },
];

// section -> groups (sch_section_student_group)
export const sch_section_student_group = [
  { academic_term_id: 1, section_id: 1, student_group_id: 1 },
  { academic_term_id: 1, section_id: 2, student_group_id: 1 },
  { academic_term_id: 1, section_id: 3, student_group_id: 1 },
];

// group sizes (maps to "student-group size" in SCH-FR-01)
export const groupSizes = { 1: 55 };

// staff availability bans (sch_availability_constraint): staff 1 not free Tuesday slot 2
export const sch_availability_constraint = [
  // { staff_id, day_id, time_slot_id, reason }
  { staff_id: 1, student_group_id: null, day_id: 3, time_slot_id: 2, reason: "Staff unavailable" },
];

// one closure: Lab 2 closed Tuesday slot 1
export const sch_room_closure = [
  { id: 1, room_id: 3, closure_reason: "Maintenance", day_id: 3, time_slot_id: 1 },
];

// equipment: Lab 2 has PCs
export const sch_equipment = [{ id: 1, equipment_name: "PCs" }];
export const sch_room_equipment = [{ room_id: 3, equipment_id: 1, quantity: 25 }];

// Active published version
export const sch_schedule_version = [{ id: 1, version_name: "v1-published", is_active: true }];

// Allocations in active version (sch_allocation)
export const sch_allocation = [
  // Dr Ahmed Monday 9-11 Database A101
  { id: 1, schedule_version_id: 1, section_id: 1, staff_id: 1, room_id: 1, day_id: 2, time_slot_id: 1 },
  // Dr Ahmed Monday 11-1 AI Lab2
  { id: 2, schedule_version_id: 1, section_id: 2, staff_id: 1, room_id: 3, day_id: 2, time_slot_id: 2 },
  // Sara Tuesday 11-1 Networks B203 (to force a clash demo)
  { id: 3, schedule_version_id: 1, section_id: 3, staff_id: 2, room_id: 4, day_id: 3, time_slot_id: 2 },
];

// helpers for name -> id resolution (Gemini entities -> IDs)
export const findDay = (name) =>
  sch_day.find((d) => d.day_name.toLowerCase() === String(name).toLowerCase());

export const findSlotByStart = (time) =>
  sch_time_slot.find((s) => s.start_time === time);

export const findStaff = (name) =>
  sch_staff.find((s) =>
    `${s.first_name} ${s.last_name}`.toLowerCase().includes(String(name).toLowerCase())
  );

export const findCourse = (name) =>
  sch_course.find((c) => c.course_name.toLowerCase() === String(name).toLowerCase());

export const findRoom = (number) =>
  sch_room.find((r) => r.room_number.toLowerCase() === String(number).toLowerCase());
