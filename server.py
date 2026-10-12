"""Local server for the emotion demo.

Serves the page and forwards "explain" requests to OpenAI, so the API key
stays on this machine instead of in the browser.

Put your key in a file named .env next to this script:
    OPENAI_API_KEY=sk-...
Optionally pick a different model with OPENAI_MODEL=... (default below).
Then run:
    python server.py
and open http://localhost:8765
"""
import base64
import binascii
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
PORT = 8765
API_URL = "https://api.openai.com/v1/chat/completions"
MAX_BODY = 5 * 1024 * 1024  # a 640x480 JPEG snapshot is ~50 KB; reject anything absurd
# Only the demo page itself may call /api/explain, so other sites can't spend the API key
ALLOWED_ORIGINS = {f"http://localhost:{PORT}", f"http://127.0.0.1:{PORT}"}

SYSTEM_PROMPT = """You interpret body language from a webcam demo.
Each request has one webcam snapshot plus readings from automatic detectors running in the browser:
hand gestures (MediaPipe), hand motion such as waving, face expression and voice emotion.
The detectors are often wrong; when they disagree with the image, trust the image.

Reply in 1-3 short, plain sentences: what the person seems to be doing with their hands,
and what it most likely means (greeting, agreement, counting, pointing at something, etc.).
Mention the face or voice only if it changes the meaning. If no hands are visible, say so briefly.
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
MODEL = os.environ.get("OPENAI_MODEL", "gpt-4.1")


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def explain(image_b64, readings):
    payload = {
        "model": MODEL,
        "max_completion_tokens": 300,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": [
                {"type": "text", "text": "Detector readings:\n" + readings},
                {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + image_b64}},
            ]},
        ],
    }
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + API_KEY},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as e:
        try:
            message = json.load(e).get("error", {}).get("message", "")
        except ValueError:
            message = ""
        raise ApiError(e.code, message) from None
    except (urllib.error.URLError, TimeoutError):
        raise ApiError(0, "") from None

    try:
        message = data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        raise ApiError(-1, "unexpected response format") from None
    if message.get("refusal"):
        return "The model declined to describe this frame."
    return (message.get("content") or "").strip() or "(no answer)"


class Handler(SimpleHTTPRequestHandler):
    def is_hidden(self):
        # Never serve .env, server.py or other dotfiles. Check the decoded, lowercased path,
        # since the base class decodes %2E etc. and Windows paths are case-insensitive.
        path = urllib.parse.unquote(self.path.split("?", 1)[0].split("#", 1)[0]).lower()
        return any(part.startswith(".") for part in path.replace("\\", "/").split("/")) or path.endswith(".py")

    def do_GET(self):
        if self.is_hidden():
            self.send_error(404)
            return
        super().do_GET()

    def do_HEAD(self):
        if self.is_hidden():
            self.send_error(404)
            return
        super().do_HEAD()

    def do_POST(self):
        if self.path != "/api/explain":
            self.send_error(404)
            return
        # Browsers always send Origin on POST. Requiring JSON also forces a CORS preflight
        # for cross-site requests, which this server never approves.
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if self.headers.get("Origin") not in ALLOWED_ORIGINS or content_type != "application/json":
            self.reply(403, {"error": "Forbidden"})
            return
        if not API_KEY:
            self.reply(500, {"error": "No API key. Create a .env file with OPENAI_API_KEY=... and restart server.py."})
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            if not 0 < length <= MAX_BODY:
                raise ValueError("bad request size")
            body = json.loads(self.rfile.read(length))
            image_b64 = body["image"]
            base64.b64decode(image_b64, validate=True)
            readings = str(body.get("readings", ""))[:4000]
        except (ValueError, KeyError, TypeError, binascii.Error):
            self.reply(400, {"error": "Bad request"})
            return

        try:
            self.reply(200, {"text": explain(image_b64, readings)})
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

    def reply(self, status, payload):
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", PORT), partial(Handler, directory=str(HERE)))
    print(f"Serving on http://localhost:{PORT}  (model: {MODEL}, API key {'found' if API_KEY else 'MISSING'})")
    server.serve_forever()
