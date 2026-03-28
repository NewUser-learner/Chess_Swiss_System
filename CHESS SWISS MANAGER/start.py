#!/usr/bin/env python3
"""
start.py — Swiss-Manager Pro launcher
Starts the server, opens the browser automatically.
Usage: python3 start.py [--port 8765]
"""
import sys, os, subprocess, time, webbrowser

PORT = 8765
for i, arg in enumerate(sys.argv):
    if arg == '--port' and i + 1 < len(sys.argv):
        PORT = int(sys.argv[i + 1])

os.environ['PORT'] = str(PORT)

print("╔══════════════════════════════════════════════════════╗")
print("║          Swiss-Manager Pro · FIDE Tournament          ║")
print("╠══════════════════════════════════════════════════════╣")
print(f"║  Starting server on http://localhost:{PORT}             ║")
print("║  Press Ctrl+C to stop.                               ║")
print("╚══════════════════════════════════════════════════════╝\n")

# Import and run inline (no subprocess needed)
import db, server

db.init_db()

# Try to open browser after 0.5s
def open_browser():
    time.sleep(0.5)
    webbrowser.open(f"http://localhost:{PORT}")

import threading
threading.Thread(target=open_browser, daemon=True).start()

server.run()
