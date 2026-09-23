// Gemini: NLU (text -> JSON) + NLG (facts -> Arabic explanation).
// Rule: Gemini never invents timetable rows. Facts come from api.js /
// POST /api/chatbot/message only. If Gemini key is missing or the call fails,
// rule-based fallback answers (deterministic baseline, project Rule 5).
// sch-chatbot-starter/gemini.js
import { GoogleGenerativeAI } from "@google/generative-ai";

function resolveKey() {
  try {
    if (typeof import.meta !== "undefined" && import.meta.env?.VITE_GEMINI_KEY)
      return import.meta.env.VITE_GEMINI_KEY;
  } catch { /* non-Vite runtime */ }
  try {
    if (typeof process !== "undefined" && process.env?.GEMINI_API_KEY)
      return process.env.GEMINI_API_KEY;
  } catch { /* browser without process */ }
  return "";
}

const genAI = new GoogleGenerativeAI(resolveKey() || "MISSING_KEY");

const SYSTEM = `You are SCH scheduling assistant. Return ONLY JSON.
Intents: show_schedule, check_move, find_room, occupancy, insights, export.
Entities: course, staff, day, time (HH:MM), room, capacity.
Examples:
"انقل Database للثلاثاء 11:00" -> {"intent":"check_move","course":"Database","day":"Tuesday","time":"11:00"}
"Show Dr Ahmed Monday" -> {"intent":"show_schedule","staff":"Ahmed","day":"Monday"}
"عايزة قاعة ل 60 طالب يوم الأحد" -> {"intent":"find_room","capacity":60,"day":"Sunday"}
"ما أكثر القاعات استخداما؟" -> {"intent":"occupancy"}
"في ضغط على المجموعات؟" -> {"intent":"insights"}
"ابعتلي الجدول ICS" -> {"intent":"export"}`;

export async function parseMessage(text) {
  if (!resolveKey()) return fallbackParse(text);
  try {
    const model = genAI.getGenerativeModel({ model: "gemini-1.5-flash" });
    const r = await model.generateContent(`${SYSTEM}\nUser: ${text}`);
    const raw = r.response.text().replace(/```json?|```/g, "").trim();
    const parsed = JSON.parse(raw);
    if (parsed && parsed.intent) return parsed;
    return fallbackParse(text);
  } catch {
    return fallbackParse(text); // deterministic fallback, Rule 5
  }
}

export function fallbackParse(text) {
  const t = (text || "").toLowerCase();
  if (t.includes("occupancy") || t.includes("استخدام") || t.includes("إشغال") ||
      t.includes("اشغال") || t.includes("احصائيات") || t.includes("أكثر القاعات") ||
      t.includes("اكثر القاعات") || t.includes("أقل") || t.includes("اقل"))
    return { intent: "occupancy" };
  if (t.includes("insight") || t.includes("تحليل") || t.includes("ضغط") ||
      t.includes("متتالية") || t.includes("مضغوط") || t.includes("توزيع") || t.includes("ورا بعض"))
    return { intent: "insights" };
  if (t.includes("ics") || t.includes("ical") || t.includes("تقويم") || t.includes("calendar") ||
      t.includes("export") || t.includes("تحميل") || t.includes("احمل") || t.includes("تنزيل") ||
      t.includes("نزل") || t.includes("تصدير") || t.includes("موبايل"))
    return { intent: "export", staff: guessStaff(t), day: guessDay(text) };
  if (t.includes("room") || t.includes("lab") || t.includes("قاعة") ||
      t.includes("معمل") || t.includes("فاضية") || t.includes("فاضي") ||
      t.includes("سعة") || t.includes("طالب"))
    return { intent: "find_room", capacity: guessCapacity(t), day: guessDay(text), room: guessRoom(t) };
  if (t.includes("move") || t.includes("انقل") || t.includes("ينفع") ||
      t.includes("ماذا لو") || t.includes("احطه") || t.includes("احط") ||
      t.includes("what if") || t.includes("check"))
    return { intent: "check_move", course: guessCourse(t), day: guessDay(text), time: guessTime(t), staff: guessStaff(t) };
  return { intent: "show_schedule", staff: guessStaff(t), day: guessDay(text) };
}

const guessCourse = (t) =>
  ["database", "ai", "networks", "algorithms", "داتابيز", "ذكاء"].find((c) => t.includes(c)) || null;

const guessStaff = (t) => {
  if (t.includes("ahmed") || t.includes("أحمد")) return "Ahmed";
  if (t.includes("sara") || t.includes("سارة")) return "Sara";
  if (t.includes("chen")) return "Chen Wei";
  return null;
};

const AR_DAYS = ["الأحد", "الاحد", "الاثنين", "الثلاثاء", "الاربعاء", "الأربعاء", "الخميس"];
const EN_DAYS = ["sunday", "monday", "tuesday", "wednesday", "thursday"];

export const guessDay = (text) => {
  const t = (text || "").toLowerCase();
  for (const d of AR_DAYS) if ((text || "").includes(d)) return d;
  return EN_DAYS.find((d) => t.includes(d)) || null;
};

export const guessTime = (t) => (t.match(/(\d{1,2}):(\d{2})/) || [])[0] || null;

export const guessCapacity = (t) => {
  const m = t.match(/(\d{2,3})\s*(طالب|student|capacity|سعة)?/);
  return m ? parseInt(m[1], 10) : null;
};

export const guessRoom = (t) => {
  const m = t.match(/(a101|a102|b203|lab\s?2|sem-[a-e]|lt-10[12]|lt-20[12])/i);
  return m ? m[0] : null;
};

// Build Smart Explanation from engine result (no hallucination).
export function explainCheck(result) {
  if (result.ok) return "✅ Change is possible. No hard conflicts found.";
  const lines = ["❌ Cannot make this change because:"];
  for (const c of result.conflicts || [])
    lines.push(`- [${c.conflict_type}] ${c.description}`);
  if (result.explanation_ar) lines.push(`\n${result.explanation_ar}`);
  if (result.recommendations?.length) {
    lines.push("\nSuggested alternatives:");
    result.recommendations.forEach((a, i) => {
      const room = a.room_number || a.room || "?";
      const time = [a.start_time, a.end_time].filter(Boolean).join("-") || "";
      const expl = a.explanation || (a.reasons || []).join("، ");
      lines.push(`${i + 1}. ${a.day_name || ""} ${time} in ${room} (${expl})`);
    });
    lines.push("\nاكتبي رقم البديل (1-3) أو 'نفذ رقم 1' للمعاينة.");
  }
  return lines.join("\n");
}
