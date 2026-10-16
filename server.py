"""Local server for the emotion demo.

Serves the page and mints short-lived keys for the voice bot, so the real
API key stays on this machine instead of in the browser.

Put your key in a file named .env next to this script:
    OPENAI_API_KEY=sk-...
Optionally pick a different voice-bot model with OPENAI_REALTIME_MODEL=...;
the default is below.
Then run:
    python server.py
and open http://localhost:8765
"""
import base64
import binascii
import hmac
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
# A host such as Render sets these so the server is reachable from outside; locally only this machine can reach it
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8765"))
REALTIME_URL = "https://api.openai.com/v1/realtime/client_secrets"
# Without a passcode, only the demo page itself may call the /api/ routes, so other sites can't spend the API key
ALLOWED_ORIGINS = {f"http://localhost:{PORT}", f"http://127.0.0.1:{PORT}"}
WRONG_LIMIT = 10     # wrong passcodes allowed per WRONG_WINDOW seconds, from everyone together,
WRONG_WINDOW = 600   # so guessing a passcode of a few words would take years

BOT_INSTRUCTIONS = """You are a friendly voice assistant in a spoken conversation with someone at a webcam.
Keep replies short: one to three sentences, the way people talk out loud.
When the conversation starts, greet the user in one short sentence.

After each user turn you get a system note with readings from automatic emotion detectors
(face expression from the webcam, emotion in the voice). The detectors are often wrong, so treat
them as weak hints; when they disagree with what the user says, trust the words.
Let the readings change how you talk, not what you claim to know:
- sad, fearful or upset: slow down, be gentle and supportive, no jokes.
- angry or frustrated: stay calm, acknowledge the problem, get to the point.
- happy or excited: match their energy.
- surprised or confused: check they are following and explain more simply.
- neutral or calm: talk normally.
Do not mention the detectors, percentages, or the user's mood or a change in it. Only if the same strong emotion
shows up for several turns may you check in once, gently and as a question ("You sound a bit down, everything okay?").
Do not guess identity, age or other personal attributes."""


def load_dotenv(path):
    """Minimal .env reader: KEY=VALUE lines, # comments; real env vars win."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_dotenv(HERE / ".env")
API_KEY = os.environ.get("OPENAI_API_KEY", "")
REALTIME_MODEL = os.environ.get("OPENAI_REALTIME_MODEL", "gpt-realtime-2.1-mini")
PASSCODE = os.environ.get("DEMO_PASSCODE", "")
wrong_times = []   # time.monotonic() of each recent wrong passcode
wrong_lock = threading.Lock()


def passcode_refusal(given):
    """None if the request may go ahead, else the (status, message) to refuse it with."""
    if not PASSCODE:
        return None
    if not given:
        return 401, "This demo needs a passcode."
    with wrong_lock:
        now = time.monotonic()
        wrong_times[:] = [t for t in wrong_times if now - t < WRONG_WINDOW]
        # While locked, even the right passcode is refused, or guessing could just carry on
        if len(wrong_times) >= WRONG_LIMIT:
            return 429, "Too many wrong passcodes. Try again in a few minutes."
        if hmac.compare_digest(given.encode("utf-8"), PASSCODE.encode("utf-8")):
            return None
        wrong_times.append(now)
        if len(wrong_times) == WRONG_LIMIT:
            print(f"{WRONG_LIMIT} wrong passcodes in {WRONG_WINDOW // 60} minutes; refusing all requests for a while.")
    return 401, "Wrong passcode."


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def call_openai(url, payload):
    """POST JSON to OpenAI and return the parsed reply."""
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + API_KEY},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        try:
            message = json.load(e).get("error", {}).get("message", "")
        except ValueError:
            message = ""
        raise ApiError(e.code, message) from None
    except (urllib.error.URLError, TimeoutError):
        raise ApiError(0, "") from None


def realtime_session():
    """Mint a short-lived key the browser uses to open one voice session with OpenAI directly."""
    session = {
        "type": "realtime",
        "model": REALTIME_MODEL,
        "instructions": BOT_INSTRUCTIONS,
        "audio": {
            "input": {
                "noise_reduction": {"type": "near_field"},
                "transcription": {"model": "gpt-4o-mini-transcribe"},  # only for the on-screen log
                # The page starts each reply itself, right after adding a fresh emotion note
                "turn_detection": {"type": "semantic_vad", "create_response": False, "interrupt_response": True},
            },
            "output": {"voice": "marin"},
        },
    }
    if REALTIME_MODEL.startswith("gpt-realtime-2"):
        session["reasoning"] = {"effort": "low"}  # these models reason; low keeps replies quick
    data = call_openai(REALTIME_URL, {"session": session})
    if not isinstance(data, dict) or not isinstance(data.get("value"), str):
        raise ApiError(-1, "unexpected response format")
    return {"key": data["value"], "model": REALTIME_MODEL}


class Handler(SimpleHTTPRequestHandler):
    def is_hidden(self):
        # Never serve .env, server.py or other dotfiles. Check the decoded, lowercased path,
        # since the base class decodes %2E etc. and Windows paths are case-insensitive.
        path = urllib.parse.unquote(self.path.split("?", 1)[0].split("#", 1)[0]).lower()
        return any(part.startswith(".") for part in path.replace("\\", "/").split("/")) or path.endswith(".py")

    def authorized(self):
        """True if the request may go ahead; otherwise asks the browser for the passcode and returns False.

        The browser shows its own sign-in box, sends what's typed there with every request to this
        site from then on, and the passcode goes in the password field (the user name is ignored).
        """
        given = None
        scheme, _, encoded = self.headers.get("Authorization", "").partition(" ")
        if scheme.lower() == "basic":
            try:
                given = base64.b64decode(encoded, validate=True).decode("utf-8").partition(":")[2]
            except (binascii.Error, UnicodeDecodeError):
                pass
        refusal = passcode_refusal(given)
        if not refusal:
            return True
        status, message = refusal
        headers = {"WWW-Authenticate": 'Basic realm="Emotion demo", charset="UTF-8"'} if status == 401 else {}
        self.reply(status, {"error": message}, headers)
        return False

    def do_GET(self):
        if not self.authorized():
            return
        if self.path == "/api/status":
            # Tells the page that server.py is running, so it shows the AI panels
            self.reply(200, {"ok": True})
            return
        if self.is_hidden():
            self.send_error(404)
            return
        super().do_GET()

    def do_HEAD(self):
        if not self.authorized():
            return
        if self.is_hidden():
            self.send_error(404)
            return
        super().do_HEAD()

    def do_POST(self):
        if not self.authorized():
            return
        if self.path != "/api/realtime-token":
            self.send_error(404)
            return
        # Browsers always send Origin on POST. Requiring JSON also forces a CORS preflight
        # for cross-site requests, which this server never approves.
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            self.reply(403, {"error": "Forbidden"})
            return
        # With a passcode set, the passcode guards the key instead, so the page also works through a tunnel
        if not PASSCODE and self.headers.get("Origin") not in ALLOWED_ORIGINS:
            self.reply(403, {"error": "This server only accepts requests from localhost. Set DEMO_PASSCODE in .env to share it."})
            return
        if not API_KEY:
            self.reply(500, {"error": "No API key. Create a .env file with OPENAI_API_KEY=... and restart server.py."})
            return
        self.reply_from_openai(realtime_session)

    def reply_from_openai(self, fn):
        """Reply with fn()'s result, turning OpenAI failures into messages the page can show."""
        try:
            self.reply(200, fn())
        except ApiError as e:
            if e.status == 0:
                self.reply(502, {"error": "Could not reach OpenAI. Check your internet connection."})
            elif e.status == 401:
                self.reply(401, {"error": "OpenAI rejected the API key. Check OPENAI_API_KEY in .env."})
            elif e.status == -1:
                self.reply(502, {"error": "OpenAI sent a reply this server doesn't understand."})
            elif e.status == 429:
                self.reply(429, {"error": "OpenAI rate limit or quota reached: " + e.args[0]})
            else:
                self.reply(502, {"error": f"OpenAI error {e.status}: {e.args[0]}"})

    def reply(self, status, payload, headers=None):
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)


if __name__ == "__main__":
    # The localhost-only check trusts the Origin header, which only browsers set honestly
    if HOST not in ("127.0.0.1", "localhost") and not PASSCODE:
        raise SystemExit(f"Set DEMO_PASSCODE before serving on {HOST}, or anyone who finds the address could use your OpenAI key.")
    server = ThreadingHTTPServer((HOST, PORT), partial(Handler, directory=str(HERE)))
    print(f"Serving on http://localhost:{PORT}  (model: {REALTIME_MODEL}; API key {'found' if API_KEY else 'MISSING'}; "
          f"passcode {'on, needed to open the page' if PASSCODE else 'off, localhost only'})")
    server.serve_forever()
