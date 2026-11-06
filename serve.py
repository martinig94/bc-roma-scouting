"""Serve the scouting page locally and save every edit into data/scouting.json.

    python serve.py              # http://localhost:8787
    python serve.py --port 9000

The page works without this server too (open index.html through any static server or GitHub Pages),
but then the notes stay in the browser and travel only through "Download / Import scouting.json".
With this server every click is written to data/scouting.json, which you commit like any other file.

API used by index.html (all JSON unless noted):
    GET  api/state                      the whole state: {players, tags, todos, teams, template}
    POST api/player/<id>                replace one player's record
    POST api/config/<tags|todos|template>
    POST api/team/<id>                  replace one team's settings (deck name, logo)
    POST api/upload/template            raw .pptx bytes -> template.pptx
    POST api/upload/logo/<team id>      raw image bytes -> logos/<team id>.<ext>
"""
from __future__ import annotations

import argparse
import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent
STATE = ROOT / "data" / "scouting.json"
LOCK = threading.Lock()
CONFIG_KINDS = {"tags", "todos", "template"}


def load_state() -> dict:
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {"players": {}, "tags": None, "todos": None, "teams": {}, "template": None}


def save_state(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(STATE)


def safe_id(s: str) -> str:
    """A team or player id as a file-system safe string."""
    return "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in unquote(s))[:120]


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(ROOT), **kw)

    def log_message(self, fmt, *args):  # quieter than the default: one line per API write only
        if self.path.startswith("/api/"):
            super().log_message(fmt, *args)

    def send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.split("?")[0] == "/api/state":
            with LOCK:
                return self.send_json(load_state())
        return super().do_GET()

    def do_POST(self):
        parts = [p for p in self.path.split("?")[0].split("/") if p]
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        if len(parts) < 2 or parts[0] != "api":
            return self.send_json({"error": "unknown endpoint"}, 404)
        kind = parts[1]
        with LOCK:
            if kind == "upload":
                return self.upload(parts[2:], raw)
            try:
                body = json.loads(raw.decode("utf-8") or "{}")
            except json.JSONDecodeError:
                return self.send_json({"error": "bad json"}, 400)
            state = load_state()
            if kind == "player" and len(parts) == 3:
                state.setdefault("players", {})[unquote(parts[2])] = body
            elif kind == "team" and len(parts) == 3:
                state.setdefault("teams", {})[unquote(parts[2])] = body
            elif kind == "config" and len(parts) == 3 and parts[2] in CONFIG_KINDS:
                state[parts[2]] = body or None
            else:
                return self.send_json({"error": "unknown endpoint"}, 404)
            save_state(state)
            return self.send_json({"ok": True})

    def upload(self, parts: list[str], raw: bytes):
        name = unquote(self.headers.get("X-Filename") or "upload")
        if parts and parts[0] == "template":
            if not raw.startswith(b"PK"):
                return self.send_json({"error": "not a .pptx"}, 400)
            (ROOT / "template.pptx").write_bytes(raw)
            return self.send_json({"url": "template.pptx", "name": name})
        if len(parts) == 2 and parts[0] == "logo":
            ext = "png" if raw.startswith(b"\x89PNG") else "jpg" if raw.startswith(b"\xff\xd8") else None
            if not ext:
                return self.send_json({"error": "PNG or JPEG only"}, 400)
            (ROOT / "logos").mkdir(exist_ok=True)
            fname = f"{safe_id(parts[1])}.{ext}"
            (ROOT / "logos" / fname).write_bytes(raw)
            return self.send_json({"url": f"logos/{fname}?v={len(raw)}", "name": name})
        return self.send_json({"error": "unknown upload"}, 404)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=8787)
    a = ap.parse_args()
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    print(f"Scouting page: http://localhost:{a.port}/   (notes -> {STATE.relative_to(ROOT)}; Ctrl+C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
