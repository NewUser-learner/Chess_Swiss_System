#!/usr/bin/env python3
"""
server.py — Swiss-Manager REST API
Pure Python stdlib: http.server + sqlite3. Zero external dependencies.

Endpoints:
  GET  /api/state                       Full tournament state (hydrate frontend)
  GET  /api/tournament                  Tournament record
  PUT  /api/tournament                  Update name/rounds/tb_order/status
  POST /api/tournament/start            Start tournament
  POST /api/tournament/reset            Reset all data

  GET  /api/players                     List players
  POST /api/players                     Add one player
  POST /api/players/bulk                Bulk import (array)
  DELETE /api/players/:id               Remove player
  DELETE /api/players                   Clear all

  GET  /api/rounds                      All rounds + pairings
  POST /api/rounds/pair                 Generate + commit next round
  PUT  /api/rounds/:n/lock              Lock round n
  PUT  /api/rounds/:n/unlock            Unlock round n

  PUT  /api/pairings/:id/result         Set result {result, force}

  GET  /                                Serve frontend HTML
  GET  /static/*                        Static assets
"""

import json, re, sys, os, mimetypes
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import db
from pairing_engine import generate_pairings

PORT = int(os.environ.get("PORT", 8765))
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


def _pick_frontend_file():
    """Pick the first available frontend entry file from common locations."""
    base = os.path.dirname(__file__)
    candidates = [
        os.path.join(STATIC_DIR, "index.html"),
        os.path.join(base, "swiss-manager-pro.html"),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    # Default path for clearer logs even if file is missing
    return candidates[0]


FRONTEND_FILE = _pick_frontend_file()


# ── JSON helpers ─────────────────────────────────────────────────────────────

def ok(data=None, status=200):
    return status, {"ok": True, "data": data}

def err(msg, status=400):
    return status, {"ok": False, "error": str(msg)}

def read_body(handler):
    length = int(handler.headers.get("Content-Length", 0))
    if length == 0: return {}
    try:
        return json.loads(handler.rfile.read(length))
    except Exception:
        return {}


# ── Router ───────────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        print(f"[{self.client_address[0]}] {fmt % args}")

    def send_json(self, status, payload):
        body = json.dumps(payload, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,PUT,DELETE,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def serve_file(self, path, content_type="text/html"):
        try:
            with open(path, "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", len(body))
            self.end_headers()
            self.wfile.write(body)
        except FileNotFoundError:
            self.send_response(404)
            self.end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,PUT,DELETE,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        # Frontend
        if path in ("/", "/index.html", "/swiss-manager-pro.html"):
            return self.serve_file(FRONTEND_FILE)

        if path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return

        # Static assets
        if path.startswith("/static/"):
            rel = path[len("/static/"):]
            full = os.path.normpath(os.path.join(STATIC_DIR, rel))
            if full.startswith(os.path.normpath(STATIC_DIR) + os.sep) and os.path.isfile(full):
                ctype, _ = mimetypes.guess_type(full)
                return self.serve_file(full, ctype or "application/octet-stream")
            self.send_response(404)
            self.end_headers()
            return

        # API
        try:
            if path == "/api/state":
                status, body = ok(db.get_full_state())
            elif path == "/api/tournament":
                status, body = ok(db.get_tournament())
            elif path == "/api/players":
                status, body = ok(db.get_players())
            elif path == "/api/rounds":
                status, body = ok(db.get_rounds())
            else:
                status, body = err("Not found", 404)
        except Exception as e:
            status, body = err(str(e), 500)

        self.send_json(status, body)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        body = read_body(self)

        try:
            # ── tournament ──
            if path == "/api/tournament/start":
                result = db.start_tournament(
                    1,
                    body.get("name", "Open Championship"),
                    int(body.get("totalRounds", 7)),
                    body.get("tbOrder", "BH,BHC1,MBH,SB,W,P"),
                )
                status, resp = ok(result)

            elif path == "/api/tournament/reset":
                db.reset_tournament()
                status, resp = ok(db.get_full_state())

            # ── players ──
            elif path == "/api/players":
                result = db.add_one_player(body)
                status, resp = ok(result)

            elif path == "/api/players/bulk":
                players = body if isinstance(body, list) else body.get("players", [])
                result = db.add_players_bulk(players)
                status, resp = ok(result)

            # ── rounds / pairing ──
            elif path == "/api/rounds/pair":
                # Pull full state to run pairing engine
                state = db.get_full_state()
                pairings = generate_pairings(state)   # returns list of {white, black, bye, result}
                round_obj = db.push_round(pairings)
                status, resp = ok(round_obj)

            else:
                status, resp = err("Not found", 404)

        except ValueError as e:
            status, resp = err(str(e), 400)
        except Exception as e:
            import traceback; traceback.print_exc()
            status, resp = err(str(e), 500)

        self.send_json(status, resp)

    def do_PUT(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        body = read_body(self)

        try:
            # PUT /api/tournament
            if path == "/api/tournament":
                result = db.update_tournament(1, **{
                    k: body[k] for k in ("name","total_rounds","tb_order","status") if k in body
                })
                status, resp = ok(result)

            # PUT /api/rounds/:n/lock
            elif m := re.match(r"^/api/rounds/(\d+)/lock$", path):
                db.lock_round(1, int(m.group(1)), True)
                status, resp = ok(db.get_round(1, int(m.group(1))))

            # PUT /api/rounds/:n/unlock
            elif m := re.match(r"^/api/rounds/(\d+)/unlock$", path):
                db.lock_round(1, int(m.group(1)), False)
                status, resp = ok(db.get_round(1, int(m.group(1))))

            # PUT /api/pairings/:id/result
            elif m := re.match(r"^/api/pairings/([^/]+)/result$", path):
                force = bool(body.get("force", False))
                result = db.set_result(m.group(1), body.get("result", ""), force=force)
                status, resp = ok(result)

            else:
                status, resp = err("Not found", 404)

        except ValueError as e:
            status, resp = err(str(e), 400)
        except Exception as e:
            import traceback; traceback.print_exc()
            status, resp = err(str(e), 500)

        self.send_json(status, resp)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        try:
            # DELETE /api/players/:id
            if m := re.match(r"^/api/players/([^/]+)$", path):
                db.remove_player(m.group(1))
                status, resp = ok({"removed": m.group(1)})

            # DELETE /api/players  (clear all)
            elif path == "/api/players":
                db.clear_players()
                status, resp = ok({"cleared": True})

            else:
                status, resp = err("Not found", 404)

        except ValueError as e:
            status, resp = err(str(e), 400)
        except Exception as e:
            status, resp = err(str(e), 500)

        self.send_json(status, resp)


# ── Entry point ──────────────────────────────────────────────────────────────

def run():
    db.init_db()
    print(f"╔══════════════════════════════════════════╗")
    print(f"║  Swiss-Manager API  →  http://localhost:{PORT}  ║")
    print(f"╚══════════════════════════════════════════╝")
    print(f"  Database : {db.DB_PATH}")
    print(f"  Frontend : {FRONTEND_FILE}")
    print(f"  Press Ctrl+C to stop.\n")
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")

if __name__ == "__main__":
    run()
