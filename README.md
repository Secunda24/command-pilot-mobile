# CommandPilot Remote
Control your PC from any phone, anywhere in the world — via the internet.

```
  📱 Your Phone  ──── HTTPS/WSS ────►  🌐 Render (relay)  ◄──── WSS ────  💻 Your PC
  (mobile web app)                     (free tier)                          (pc_agent.py)
```

---

## Files

| File | Where it runs | What it does |
|------|---------------|--------------|
| `server/server.js` | **Render** (cloud) | WebSocket relay — bridges phone ↔ PC |
| `public/index.html` | Served by Render | Mobile web UI (works on any phone browser) |
| `pc_agent.py` | **Your PC** | Connects to relay, runs Jarvis skills + Ollama |

---

## Step 1 — Deploy to Render

1. Push this folder to a GitHub repo (can be private).
2. Go to [render.com](https://render.com) → **New → Web Service**.
3. Connect the repo. Render auto-detects the `render.yaml`.
4. In **Environment** tab, note the `AUTH_TOKEN` Render generated  
   (or set your own — any random string works, e.g. `openssl rand -hex 20`).
5. Click **Deploy**. Wait ~2 min. Your URL will be:  
   `https://commandpilot-remote.onrender.com`

---

## Step 2 — Configure the PC agent

Edit `pc_agent.py` (top of file) OR set environment variables:

```
set RELAY_URL=wss://commandpilot-remote.onrender.com
set AUTH_TOKEN=your-token-from-render
set OLLAMA_MODEL=gemma:2b
```

Install dependencies:
```
pip install websockets
pip install ollama      # if you want Ollama fallback
pip install pyttsx3     # optional — PC speaks responses aloud
```

Place `pc_agent.py` in the same folder as `jarvis_skills.py` and `jarvis_core.py`.

---

## Step 3 — Run the PC agent

```
python pc_agent.py
```

Leave this running in the background. It automatically reconnects if the
connection drops. You can also set it up as a Windows startup task.

---

## Step 4 — Open the app on your phone

Open:  `https://commandpilot-remote.onrender.com`

Enter your `AUTH_TOKEN` and tap **CONNECT**.

The animated Jarvis ring will show your PC's live status.  
Type or use the microphone button to send commands.

---

## Security notes

- The `AUTH_TOKEN` is the only thing protecting access to your PC.  
  Use a strong random value (20+ chars). Never share it.
- All traffic is encrypted (WSS / HTTPS).
- The relay server never stores any commands or responses.
- The PC agent only accepts commands from the relay (outbound connection only —
  no inbound ports need to be opened on your router/firewall).

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| "PC Offline" on phone | Make sure `pc_agent.py` is running on your PC |
| Connection refused | Check `RELAY_URL` starts with `wss://` not `ws://` |
| Render free tier sleeps | The server self-pings every 14 min to stay awake |
| Skill not found | Ensure `jarvis_skills.py` is in the same folder as `pc_agent.py` |
| Ollama error | Run `ollama serve` in a separate terminal on your PC |
