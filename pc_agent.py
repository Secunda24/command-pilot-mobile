"""
pc_agent.py  —  CommandPilot Remote · PC Agent
===============================================
Run this on your PC.  It connects OUT to the Render relay server over the
internet (no port forwarding / firewall changes needed on your side).

The agent:
  1. Authenticates with the relay using your AUTH_TOKEN
  2. Receives text commands sent from your phone
  3. Routes them through Jarvis skills (detect_and_run)
  4. Falls back to Ollama for conversational replies
  5. Streams status updates and responses back to your phone in real time

Usage:
    python pc_agent.py

Configuration (edit the section below OR set environment variables):
    RELAY_URL    — wss://your-app-name.onrender.com
    AUTH_TOKEN   — must match the AUTH_TOKEN set in Render env vars
    OLLAMA_MODEL — any model you have pulled in Ollama (default: gemma:2b)
"""

import os, json, time, threading, asyncio, sys
import websockets

# ── CONFIG ────────────────────────────────────────────────────────────────────
RELAY_URL    = os.getenv("RELAY_URL",    "wss://your-app-name.onrender.com")
AUTH_TOKEN   = os.getenv("AUTH_TOKEN",   "change-me-in-render-env")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma:2b")
RECONNECT_DELAY = 5   # seconds between reconnect attempts

# ── optional: Jarvis skills (must be in the same folder) ──────────────────────
try:
    from jarvis_skills import detect_and_run, process_action_queue
    HAS_JARVIS = True
    print("[AGENT] Jarvis skills loaded ✓")
except ImportError:
    HAS_JARVIS = False
    print("[AGENT] jarvis_skills.py not found — running in chat-only mode")

# ── optional: Ollama ──────────────────────────────────────────────────────────
try:
    import ollama as _ollama
    HAS_OLLAMA = True
    print(f"[AGENT] Ollama loaded ✓  (model: {OLLAMA_MODEL})")
except ImportError:
    HAS_OLLAMA = False
    print("[AGENT] ollama package not installed — pip install ollama")

# ── optional: pyttsx3 (speak responses aloud on PC) ──────────────────────────
try:
    import pyttsx3 as _pyttsx3
    _tts = _pyttsx3.init()
    _tts.setProperty("rate",   185)
    _tts.setProperty("volume", 1.0)
    HAS_TTS = True
    print("[AGENT] pyttsx3 TTS loaded ✓")
except Exception:
    HAS_TTS = False
    print("[AGENT] pyttsx3 not available — PC will not speak aloud")

# ── shared websocket reference ─────────────────────────────────────────────────
_ws_ref: list = [None]   # mutable container so worker threads can access it


# ── helpers ───────────────────────────────────────────────────────────────────
def send_to_phone(ws, msg: dict):
    """Thread-safe send from a worker thread."""
    loop = asyncio.get_event_loop()
    asyncio.run_coroutine_threadsafe(ws.send(json.dumps(msg)), loop)


def speak_local(text: str):
    if HAS_TTS:
        try:
            cap = text[:220].rsplit(" ", 1)[0] + "…" if len(text) > 220 else text
            _tts.say(cap)
            _tts.runAndWait()
        except Exception as e:
            print(f"[TTS ERROR] {e}")


def ask_ollama(question: str) -> str:
    if not HAS_OLLAMA:
        return "Ollama is not installed on this PC. pip install ollama"
    try:
        r = _ollama.chat(
            model=OLLAMA_MODEL,
            messages=[
                {"role": "system",
                 "content": "You are JARVIS. Reply in 1–2 sentences, witty and helpful."},
                {"role": "user", "content": question},
            ],
            options={"temperature": 0.6, "num_predict": 80, "num_ctx": 512},
        )
        return r["message"]["content"].strip()
    except Exception as e:
        return f"Ollama error: {e}"


def run_command(ws, raw: str):
    """Execute a command from the phone. Runs in a daemon thread."""
    print(f"\n[CMD] Received: '{raw}'")

    # broadcast THINKING
    send_to_phone(ws, {"type": "status", "status": "THINKING", "text": ""})

    response = None
    intent   = "chat"

    # ── try Jarvis skills first ───────────────────────────────────────────────
    if HAS_JARVIS:
        try:
            intent, response = detect_and_run(raw)
            # drain OS action queue (safe here — non-GUI actions only)
            process_action_queue()
        except Exception as e:
            print(f"[SKILL ERROR] {e}")
            intent, response = "error", f"Skill error: {e}"

    # ── fallback to Ollama ────────────────────────────────────────────────────
    if intent in ("chat", None) or response is None:
        send_to_phone(ws, {"type": "status", "status": "THINKING", "text": "Asking Ollama…"})
        response = ask_ollama(raw)
        intent   = "chat"

    print(f"[CMD] intent={intent}  response='{response}'")

    # ── speak locally on the PC ───────────────────────────────────────────────
    if intent != "error":
        threading.Thread(target=speak_local, args=(response,), daemon=True).start()

    # ── send response to phone ────────────────────────────────────────────────
    send_to_phone(ws, {
        "type":   "response",
        "intent": intent,
        "text":   response,
        "status": "STANDBY",
    })


# ── main async loop ───────────────────────────────────────────────────────────
async def agent_loop():
    while True:
        print(f"[AGENT] Connecting to {RELAY_URL} …")
        try:
            async with websockets.connect(
                RELAY_URL,
                ping_interval=20,
                ping_timeout=30,
                open_timeout=15,
            ) as ws:
                _ws_ref[0] = ws
                print("[AGENT] Connected ✓")

                # authenticate as PC
                await ws.send(json.dumps({
                    "type":  "auth",
                    "token": AUTH_TOKEN,
                    "role":  "pc",
                }))

                async for raw in ws:
                    try:
                        data = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    t = data.get("type")
                    print(f"[MSG] type={t}")

                    if t == "auth_ok":
                        print(f"[AGENT] Auth OK — {data.get('message','')}")
                        # announce status
                        await ws.send(json.dumps({
                            "type":   "status",
                            "status": "STANDBY",
                            "text":   "",
                        }))

                    elif t == "command":
                        cmd = data.get("text", "").strip()
                        if cmd:
                            threading.Thread(
                                target=run_command,
                                args=(ws, cmd),
                                daemon=True,
                            ).start()

                    elif t == "error":
                        print(f"[SERVER ERROR] {data.get('message','')}")

        except (websockets.exceptions.ConnectionClosed,
                websockets.exceptions.WebSocketException,
                OSError) as e:
            print(f"[AGENT] Disconnected: {e}")
        except Exception as e:
            print(f"[AGENT] Unexpected error: {e}")

        _ws_ref[0] = None
        print(f"[AGENT] Reconnecting in {RECONNECT_DELAY}s …")
        await asyncio.sleep(RECONNECT_DELAY)


# ── entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("  CommandPilot Remote — PC Agent")
    print(f"  Relay : {RELAY_URL}")
    print(f"  Ollama: {OLLAMA_MODEL}")
    print(f"  Jarvis: {'enabled' if HAS_JARVIS else 'disabled (skills not found)'}")
    print("=" * 60)

    if RELAY_URL == "wss://your-app-name.onrender.com":
        print("\n⚠  RELAY_URL is still the placeholder.")
        print("   Edit pc_agent.py or set:  set RELAY_URL=wss://YOUR-APP.onrender.com\n")

    try:
        asyncio.run(agent_loop())
    except KeyboardInterrupt:
        print("\n[AGENT] Stopped.")
