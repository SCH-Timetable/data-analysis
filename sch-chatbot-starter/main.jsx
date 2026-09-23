import React from "react";
import { createRoot } from "react-dom/client";
import Chat from "./Chat.jsx";

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <div style={{ padding: 16 }}>
      <h2 style={{ fontFamily: "sans-serif", textAlign: "center" }}>
        SCH Chatbot — Timetable Assistant
      </h2>
      <Chat />
    </div>
  </React.StrictMode>
);
