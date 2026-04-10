/**
 * CommandPilot Remote — Relay Server
 * Runs on Render (free tier).
 *
 * Architecture:
 *   Phone browser  ──WebSocket──►  THIS SERVER  ◄──WebSocket──  PC Agent (Python)
 *
 * The server is a pure relay — it never stores commands or responses.
 * Auth: every connection must send {"type":"auth","token":"YOUR_SECRET"}
 *       within 5 seconds or the socket is dropped.
 *
 * Env vars (set in Render dashboard):
 *   AUTH_TOKEN   — shared secret between server, PC agent, and phone
 *   PORT         — set automatically by Render
 */

const express   = require("express");
const http      = require("http");
const WebSocket = require("ws");
const path      = require("path");
const crypto    = require("crypto");

const app    = express();
const server = http.createServer(app);
const wss    = new WebSocket.Server({ server });

const AUTH_TOKEN = process.env.AUTH_TOKEN || "change-me-in-render-env";
const PORT       = process.env.PORT       || 3000;

// ── client registry ───────────────────────────────────────────────────────────
// One PC agent at a time; many phone clients
let pcSocket    = null;   // the registered PC agent
const phones    = new Set(); // authenticated phone clients

// ── serve mobile web app ──────────────────────────────────────────────────────
app.use(express.static(path.join(__dirname, "public")));

// health check endpoint (Render pings this to keep the service alive)
app.get("/health", (_req, res) => res.json({
  status: "ok",
  pcOnline: pcSocket !== null && pcSocket.readyState === WebSocket.OPEN,
  phones:   phones.size,
}));

// ── helpers ───────────────────────────────────────────────────────────────────
function safeJson(raw) {
  try { return JSON.parse(raw); } catch { return null; }
}

function send(ws, obj) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(obj));
  }
}

function broadcastPhones(obj) {
  const msg = JSON.stringify(obj);
  for (const ws of phones) {
    if (ws.readyState === WebSocket.OPEN) ws.send(msg);
  }
}

// ── WebSocket handler ─────────────────────────────────────────────────────────
wss.on("connection", (ws, req) => {
  const ip = req.headers["x-forwarded-for"] || req.socket.remoteAddress;
  console.log(`[WS] New connection from ${ip}`);

  ws._authenticated = false;
  ws._role          = null;   // "pc" | "phone"
  ws._id            = crypto.randomBytes(4).toString("hex");

  // drop unauthenticated sockets after 5 s
  const authTimer = setTimeout(() => {
    if (!ws._authenticated) {
      console.log(`[WS] ${ws._id} — auth timeout, dropping`);
      ws.terminate();
    }
  }, 5000);

  ws.on("message", (raw) => {
    const data = safeJson(raw);
    if (!data) return;

    // ── AUTH ─────────────────────────────────────────────────────────────────
    if (!ws._authenticated) {
      if (data.type === "auth" && data.token === AUTH_TOKEN) {
        clearTimeout(authTimer);
        ws._authenticated = true;
        ws._role          = data.role === "pc" ? "pc" : "phone";
        console.log(`[AUTH] ${ws._id} authenticated as "${ws._role}"`);

        if (ws._role === "pc") {
          // replace old PC socket
          if (pcSocket && pcSocket !== ws) pcSocket.terminate();
          pcSocket = ws;
          send(ws, { type: "auth_ok", message: "PC agent registered." });
          // tell phones PC just came online
          broadcastPhones({ type: "pc_status", online: true });
        } else {
          phones.add(ws);
          send(ws, { type: "auth_ok", message: "Phone connected.",
                     pcOnline: pcSocket !== null && pcSocket.readyState === WebSocket.OPEN });
        }
      } else {
        send(ws, { type: "error", message: "Invalid token." });
        ws.terminate();
      }
      return;
    }

    // ── PHONE → PC ───────────────────────────────────────────────────────────
    if (ws._role === "phone") {
      if (data.type === "command") {
        if (!pcSocket || pcSocket.readyState !== WebSocket.OPEN) {
          send(ws, { type: "response", text: "⚠️  PC is offline.", intent: "error" });
          return;
        }
        console.log(`[RELAY] Phone → PC: "${data.text}"`);
        send(pcSocket, { type: "command", text: data.text, fromPhone: ws._id });
      }
      if (data.type === "ping") send(ws, { type: "pong" });
    }

    // ── PC → PHONES ──────────────────────────────────────────────────────────
    if (ws._role === "pc") {
      // Forward status updates and responses to all phones
      if (["response", "status", "error"].includes(data.type)) {
        console.log(`[RELAY] PC → phones: type=${data.type}`);
        broadcastPhones(data);
      }
    }
  });

  ws.on("close", () => {
    if (ws._role === "pc" && pcSocket === ws) {
      pcSocket = null;
      console.log("[WS] PC agent disconnected.");
      broadcastPhones({ type: "pc_status", online: false });
    }
    if (ws._role === "phone") {
      phones.delete(ws);
      console.log(`[WS] Phone ${ws._id} disconnected. (${phones.size} remaining)`);
    }
  });

  ws.on("error", (err) => console.error(`[WS ERROR] ${ws._id}:`, err.message));
});

// ── keep Render free tier alive (ping own health endpoint every 14 min) ───────
setInterval(() => {
  const http = require("http");
  http.get(`http://localhost:${PORT}/health`, () => {}).on("error", () => {});
}, 14 * 60 * 1000);

server.listen(PORT, () => console.log(`[SERVER] CommandPilot Remote listening on :${PORT}`));
