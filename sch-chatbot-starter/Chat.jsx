// Minimal chat UI: Ask -> Analyze -> Check -> Suggest -> Confirm.
// Backend-first: tries POST /api/chatbot/message (NLU + facts + Arabic answer
// in one call). Falls back to local mock flow if backend is down.
// Features: image upload (photo -> extracted info + live verification),
// ICS download button, confirm flow.
// sch-chatbot-starter/Chat.jsx
import { useRef, useState } from "react";
import { parseMessage, explainCheck } from "./gemini";
import { BACKEND_URL, getTimetable, validateMove, getOccupancy, searchRooms, sendChat } from "./api";
import { findCourse, findDay, findSlotByStart, findStaff } from "./mockData";

const DAY_AR2EN = {
  "الأحد": "Sunday", "الاحد": "Sunday",
  "الاثنين": "Monday",
  "الثلاثاء": "Tuesday",
  "الاربعاء": "Wednesday", "الأربعاء": "Wednesday",
  "الخميس": "Thursday",
};

function toDayId(dayName) {
  if (dayName == null) return null;
  if (typeof dayName === "number") return dayName;
  const en = DAY_AR2EN[String(dayName)] || String(dayName);
  const d = findDay(en);
  return d ? d.id : null;
}

export default function Chat() {
  const [msgs, setMsgs] = useState([
    { from: "bot", text: "Ask me: 'Show Dr Ahmed Monday' / 'انقل Database للثلاثاء 11:00' / 'عايزة قاعة 60 طالب الأحد' / 'إشغال القاعات' / 'ابعتلي الجدول ICS' — أو ابعت 📷 صورة جدول وأطلعلك اللي فيها 📷" },
  ]);
  const [input, setInput] = useState("");
  const [pendingAlts, setPendingAlts] = useState([]);
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef(null);
  const push = (from, text, url = null, img = null) =>
    setMsgs((m) => [...m, { from, text, url, img }]);

  // ── Image upload: photo -> extracted entries + verification vs live data ───
  async function handleImage(e) {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (!f) return;
    const preview = URL.createObjectURL(f);
    push("user", `📷 صورة: ${f.name}`, null, preview);
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append("file", f);
      const r = await fetch(`${BACKEND_URL}/api/chatbot/analyze-image`, {
        method: "POST", body: fd,
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const res = await r.json();
      push("bot", res.answer_ar || "خلصت تحليل الصورة.");
    } catch {
      push("bot", "مقدرتش أحلل الصورة. اتأكد إن الباك شغال على 8000 وإن الملف صورة PNG/JPG أقل من 5MB.");
    } finally {
      setUploading(false);
    }
  }

  async function send() {
    const text = input.trim();
    if (!text) return;
    push("user", text);
    setInput("");

    // 0) Confirm flow: "نفذ رقم 1" / "1" / "ايوه"
    if (pendingAlts.length && /^(نفذ|ايوه|تمام|yes|نعم|ok|1|2|3|الأول|الاول|رقم)/i.test(text.trim())) {
      const n = text.match(/[123]/);
      const pick = pendingAlts[n ? parseInt(n[0], 10) - 1 : 0];
      if (pick) {
        setPendingAlts([]);
        const room = pick.room_number || pick.room;
        return push("bot",
          `📅 Updated Timetable (preview — confirm in scheduler grid):\n` +
          `${pick.day_name} ${pick.start_time || ""}-${pick.end_time || ""} — ${room} ← Updated\n\n` +
          `ملحوظة: التنفيذ النهائي من زرار Apply في شاشة الـ conflicts (الباك بيمنع الكتابة من غير أدمن).`);
      }
    }

    // 1) Backend chat first (real data, no hallucination)
    try {
      const res = await sendChat(text);
      if (res && res.answer_ar) {
        if (res.facts?.recommendations?.length) setPendingAlts(res.facts.recommendations);
        else if (res.intent === "check_move") setPendingAlts([]);
        const url = res.facts?.export_url ? `${BACKEND_URL}${res.facts.export_url}` : null;
        return push("bot", res.answer_ar, url);
      }
    } catch {
      // backend down -> local fallback below
    }

    // 2) Local fallback (mock data + local Gemini/fallback NLU)
    const p = await parseMessage(text);

    if (p.intent === "show_schedule") {
      const staff = p.staff ? findStaff(p.staff) : null;
      const day = p.day ? findDay(DAY_AR2EN[p.day] || p.day) : null;
      const rows = await getTimetable({ staff_id: staff?.id, day_id: day?.id });
      if (!rows.length) return push("bot", "No rows found. (Backend down — showing mock data only)");
      const out = rows.map((r) => {
        const dn = r.day?.day_name ?? "";
        const st = r.slot?.start_time ?? "";
        const et = r.slot?.end_time ?? "";
        const cn = r.course?.course_name ?? r.name ?? "";
        const rn = r.room?.room_number ?? r.room ?? "";
        return `${dn} ${st}-${et} — ${cn} — ${rn}`;
      }).join("\n");
      return push("bot", `📅 ${staff ? staff.first_name : "All"} — ${day ? day.day_name : "All"}\n${out}`);
    }

    if (p.intent === "check_move") {
      const course = findCourse(p.course || "");
      const day = findDay(DAY_AR2EN[p.day] || p.day || "");
      const slot = findSlotByStart(p.time || "");
      if (!course || !day || !slot) return push("bot", "Specify course + day + time. Example: Move Database to Tuesday 11:00");
      const cand = { section_id: course.id, staff_id: 1, room_id: 4, day_id: day.id, time_slot_id: slot.id };
      const res = await validateMove(cand);
      if (res.recommendations?.length) setPendingAlts(res.recommendations);
      return push("bot", explainCheck(res));
    }

    if (p.intent === "find_room") {
      const rooms = await searchRooms({ minCapacity: p.capacity || 60, day_id: toDayId(p.day) });
      if (!rooms.length) return push("bot", "مفيش قاعة متاحة بالمواصفات دي.");
      return push("bot", rooms.slice(0, 5).map((o) =>
        `${o.room_number || o.name}: سعة ${o.capacity} (${o.pct != null ? o.pct + "%" : "متاحة"})`).join("\n"));
    }

    if (p.intent === "export") {
      // Export needs the backend (file download) — no honest mock for it.
      const q = p.staff ? `?staff=${encodeURIComponent(p.staff)}` : "";
      return push("bot",
        "التصدير محتاج الباك شغال. شغل السيرفر على 8000 من هنا:",
        `${BACKEND_URL}/api/chatbot/export-ics${q}`);
    }

    if (p.intent === "occupancy" || p.intent === "insights") {
      const occ = await getOccupancy();
      return push("bot", occ.map((o) => `${o.room_number}: ${o.used}/${o.total} (${o.pct}%)`).join("\n"));
    }
    push("bot", "Try: show schedule / move check / قاعة فاضية / إشغال القاعات / ابعتلي الجدول ICS — أو ابعت صورة جدول 📷.");
  }

  return (
    <div style={{ maxWidth: 600, margin: "auto", fontFamily: "sans-serif" }}>
      <div style={{ border: "1px solid #ccc", padding: 12, minHeight: 300, whiteSpace: "pre-wrap" }}>
        {msgs.map((m, i) => (
          <div key={i}>
            <b>{m.from}:</b> {m.text}
            {m.img && (
              <div style={{ marginTop: 6 }}>
                <img src={m.img} alt="uploaded" style={{ maxWidth: 220, borderRadius: 6, border: "1px solid #ccc" }} />
              </div>
            )}
            {m.url && (
              <div style={{ marginTop: 6 }}>
                <a href={m.url} download="timetable.ics"
                   style={{ display: "inline-block", padding: "6px 12px", border: "1px solid #2563eb",
                            borderRadius: 6, color: "#2563eb", textDecoration: "none" }}>
                  ⬇ تحميل ملف التقويم (ICS)
                </a>
              </div>
            )}
          </div>
        ))}
      </div>
      <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
        <input ref={fileRef} type="file" accept="image/*" style={{ display: "none" }} onChange={handleImage} />
        <button onClick={() => fileRef.current?.click()} disabled={uploading} title="Upload timetable photo"
                style={{ padding: 8, border: "1px solid #ccc", borderRadius: 6 }}>
          {uploading ? "⏳" : "📷"}
        </button>
        <input value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={(e) => e.key === "Enter" && send()}
          placeholder="Type here... أو ابعت 📷 صورة جدول" style={{ flex: 1, padding: 8 }} />
        <button onClick={send} style={{ padding: 8 }}>Send</button>
      </div>
    </div>
  );
}
