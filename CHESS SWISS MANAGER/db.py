"""
db.py — Swiss-Manager SQLite Database Layer
Schema:
  tournaments (id, name, date, total_rounds, current_round, status, tb_order)
  players     (id, tournament_id, sno, name, fide_id, rating, country, is_unrated)
  rounds      (id, tournament_id, number, locked)
  pairings    (id, round_id, tournament_id, white_id, black_id, result, is_bye, edit_history)
"""

import sqlite3, json, os, threading
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "swiss.db")
_local = threading.local()


def get_conn():
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA foreign_keys=ON")
    return _local.conn


def init_db():
    conn = get_conn()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS tournaments (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        name         TEXT    NOT NULL DEFAULT 'Open Championship',
        date         TEXT    NOT NULL DEFAULT (date('now')),
        total_rounds INTEGER NOT NULL DEFAULT 7,
        current_round INTEGER NOT NULL DEFAULT 0,
        status       TEXT    NOT NULL DEFAULT 'setup',
        tb_order     TEXT    NOT NULL DEFAULT 'BH,BHC1,MBH,SB,W,P',
        created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS players (
        id              TEXT    PRIMARY KEY,
        tournament_id   INTEGER NOT NULL REFERENCES tournaments(id) ON DELETE CASCADE,
        sno             INTEGER NOT NULL DEFAULT 0,
        name            TEXT    NOT NULL,
        fide_id         TEXT    NOT NULL DEFAULT '',
        rating          INTEGER NOT NULL DEFAULT 0,
        country         TEXT    NOT NULL DEFAULT '',
        is_unrated      INTEGER NOT NULL DEFAULT 0,
        created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS rounds (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        tournament_id   INTEGER NOT NULL REFERENCES tournaments(id) ON DELETE CASCADE,
        number          INTEGER NOT NULL,
        locked          INTEGER NOT NULL DEFAULT 0,
        created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
        UNIQUE(tournament_id, number)
    );

    CREATE TABLE IF NOT EXISTS pairings (
        id              TEXT    PRIMARY KEY,
        round_id        INTEGER NOT NULL REFERENCES rounds(id) ON DELETE CASCADE,
        tournament_id   INTEGER NOT NULL REFERENCES tournaments(id) ON DELETE CASCADE,
        white_id        TEXT    REFERENCES players(id),
        black_id        TEXT    REFERENCES players(id),
        result          TEXT    NOT NULL DEFAULT '',
        is_bye          INTEGER NOT NULL DEFAULT 0,
        edit_history    TEXT    NOT NULL DEFAULT '[]',
        created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
    );

    CREATE INDEX IF NOT EXISTS idx_players_tid  ON players(tournament_id);
    CREATE INDEX IF NOT EXISTS idx_rounds_tid   ON rounds(tournament_id);
    CREATE INDEX IF NOT EXISTS idx_pairings_rid ON pairings(round_id);
    CREATE INDEX IF NOT EXISTS idx_pairings_tid ON pairings(tournament_id);
    """)
    conn.commit()

    # Ensure at least one tournament exists
    row = conn.execute("SELECT id FROM tournaments LIMIT 1").fetchone()
    if not row:
        conn.execute("INSERT INTO tournaments(name) VALUES('Open Championship 2025')")
        conn.commit()


# ── helpers ──────────────────────────────────────────────────────────────────

def row_to_dict(row):
    return dict(row) if row else None

def rows_to_list(rows):
    return [dict(r) for r in rows]


# ── TOURNAMENT ───────────────────────────────────────────────────────────────

def get_tournament(tid=1):
    return row_to_dict(get_conn().execute(
        "SELECT * FROM tournaments WHERE id=?", (tid,)).fetchone())

def update_tournament(tid, **kwargs):
    conn = get_conn()
    allowed = {"name","date","total_rounds","current_round","status","tb_order"}
    fields = {k:v for k,v in kwargs.items() if k in allowed}
    if not fields: return
    sets = ", ".join(f"{k}=?" for k in fields)
    conn.execute(f"UPDATE tournaments SET {sets} WHERE id=?", (*fields.values(), tid))
    conn.commit()
    return get_tournament(tid)

def reset_tournament(tid=1):
    conn = get_conn()
    conn.execute("DELETE FROM pairings WHERE tournament_id=?", (tid,))
    conn.execute("DELETE FROM rounds    WHERE tournament_id=?", (tid,))
    conn.execute("DELETE FROM players   WHERE tournament_id=?", (tid,))
    conn.execute("""UPDATE tournaments SET
        name='Open Championship 2025', current_round=0, status='setup',
        total_rounds=7, tb_order='BH,BHC1,MBH,SB,W,P'
        WHERE id=?""", (tid,))
    conn.commit()


# ── PLAYERS ──────────────────────────────────────────────────────────────────

MAX_PLAYERS = 300

def get_players(tid=1):
    return rows_to_list(get_conn().execute(
        "SELECT * FROM players WHERE tournament_id=? ORDER BY sno", (tid,)).fetchall())

def add_players_bulk(players_list, tid=1):
    """Add multiple players; enforce 300 cap; re-seed after."""
    conn = get_conn()
    current = conn.execute("SELECT COUNT(*) FROM players WHERE tournament_id=?", (tid,)).fetchone()[0]
    added, skipped = 0, 0
    import uuid
    for p in players_list:
        if current + added >= MAX_PLAYERS:
            skipped += len(players_list) - added
            break
        pid = str(uuid.uuid4())
        rating = int(p.get("rating") or 0)
        conn.execute("""INSERT INTO players(id,tournament_id,name,fide_id,rating,country,is_unrated)
            VALUES(?,?,?,?,?,?,?)""",
            (pid, tid, (p.get("name") or "").strip(),
             (p.get("fideId") or "").strip(), rating,
             (p.get("country") or "").strip().upper()[:3], 1 if rating == 0 else 0))
        added += 1
    conn.commit()
    reseed_players(tid)
    return {"added": added, "skipped": skipped}

def add_one_player(p, tid=1):
    import uuid
    conn = get_conn()
    count = conn.execute("SELECT COUNT(*) FROM players WHERE tournament_id=?", (tid,)).fetchone()[0]
    if count >= MAX_PLAYERS:
        raise ValueError(f"Player limit ({MAX_PLAYERS}) reached.")
    t = get_tournament(tid)
    if t and t["status"] != "setup":
        raise ValueError("Cannot add players after tournament has started.")
    pid = str(uuid.uuid4())
    rating = int(p.get("rating") or 0)
    conn.execute("""INSERT INTO players(id,tournament_id,name,fide_id,rating,country,is_unrated)
        VALUES(?,?,?,?,?,?,?)""",
        (pid, tid, (p.get("name") or "").strip(),
         (p.get("fideId") or "").strip(), rating,
         (p.get("country") or "").strip().upper()[:3], 1 if rating == 0 else 0))
    conn.commit()
    reseed_players(tid)
    return get_player(pid)

def get_player(pid):
    return row_to_dict(get_conn().execute("SELECT * FROM players WHERE id=?", (pid,)).fetchone())

def remove_player(pid, tid=1):
    conn = get_conn()
    t = get_tournament(tid)
    if t and t["status"] != "setup":
        raise ValueError("Cannot remove players after tournament has started.")
    conn.execute("DELETE FROM players WHERE id=? AND tournament_id=?", (pid, tid))
    conn.commit()
    reseed_players(tid)

def clear_players(tid=1):
    conn = get_conn()
    t = get_tournament(tid)
    if t and t["status"] != "setup":
        raise ValueError("Cannot clear players after tournament has started.")
    conn.execute("DELETE FROM players WHERE tournament_id=?", (tid,))
    conn.commit()

def reseed_players(tid=1):
    """Rated desc by rating, unrated alpha last — assigns sno."""
    conn = get_conn()
    players = rows_to_list(conn.execute(
        "SELECT * FROM players WHERE tournament_id=?", (tid,)).fetchall())
    rated   = sorted([p for p in players if not p["is_unrated"]], key=lambda p: (-p["rating"], p["name"]))
    unrated = sorted([p for p in players if  p["is_unrated"]],    key=lambda p:  p["name"])
    for i, p in enumerate([*rated, *unrated], start=1):
        conn.execute("UPDATE players SET sno=? WHERE id=?", (i, p["id"]))
    conn.commit()


# ── ROUNDS & PAIRINGS ────────────────────────────────────────────────────────

def get_rounds(tid=1):
    rounds = rows_to_list(get_conn().execute(
        "SELECT * FROM rounds WHERE tournament_id=? ORDER BY number", (tid,)).fetchall())
    for r in rounds:
        r["pairings"] = get_pairings(r["id"])
    return rounds

def get_round(tid, number):
    r = row_to_dict(get_conn().execute(
        "SELECT * FROM rounds WHERE tournament_id=? AND number=?", (tid, number)).fetchone())
    if r:
        r["pairings"] = get_pairings(r["id"])
    return r

def get_pairings(round_id):
    rows = rows_to_list(get_conn().execute(
        "SELECT * FROM pairings WHERE round_id=? ORDER BY rowid", (round_id,)).fetchall())
    for r in rows:
        r["edit_history"] = json.loads(r["edit_history"] or "[]")
        r["is_bye"] = bool(r["is_bye"])
    return rows

def push_round(pairings, tid=1):
    """Insert a new round with pairings. Validates no double-pairing."""
    conn = get_conn()
    import uuid

    # Count existing rounds
    num = conn.execute(
        "SELECT COUNT(*) FROM rounds WHERE tournament_id=?", (tid,)).fetchone()[0] + 1

    t = get_tournament(tid)
    if num > t["total_rounds"]:
        raise ValueError("All rounds already paired.")

    # Double-pairing validation across ALL previous rounds in this tournament
    for pr in pairings:
        if pr.get("bye"): continue
        dup = conn.execute("""
            SELECT 1 FROM pairings p
            JOIN rounds r ON r.id = p.round_id
            WHERE r.tournament_id = ?
              AND p.is_bye = 0
              AND ((p.white_id=? AND p.black_id=?) OR (p.white_id=? AND p.black_id=?))
        """, (tid, pr["white"], pr["black"], pr["black"], pr["white"])).fetchone()
        if dup:
            raise ValueError(f"Double-pairing prevented for round {num}.")

    # Insert round
    rid = conn.execute(
        "INSERT INTO rounds(tournament_id, number) VALUES(?,?)", (tid, num)).lastrowid

    # Insert pairings
    for pr in pairings:
        pid = str(uuid.uuid4())
        is_bye = 1 if pr.get("bye") else 0
        conn.execute("""INSERT INTO pairings(id,round_id,tournament_id,white_id,black_id,result,is_bye)
            VALUES(?,?,?,?,?,?,?)""",
            (pid, rid, tid, pr["white"], pr.get("black"), pr.get("result", ""), is_bye))

    conn.execute("UPDATE tournaments SET current_round=? WHERE id=?", (num, tid))
    conn.commit()
    return get_round(tid, num)

def set_result(pairing_id, result, force=False):
    conn = get_conn()
    pr = row_to_dict(conn.execute("SELECT * FROM pairings WHERE id=?", (pairing_id,)).fetchone())
    if not pr:
        raise ValueError("Pairing not found.")
    r = row_to_dict(conn.execute("SELECT * FROM rounds WHERE id=?", (pr["round_id"],)).fetchone())
    if r["locked"] and not force:
        raise ValueError("Round is locked. Pass force=true to override.")

    history = json.loads(pr["edit_history"] or "[]")
    if pr["result"] != result:
        history.append({"from": pr["result"], "to": result, "at": datetime.utcnow().isoformat()})

    conn.execute("UPDATE pairings SET result=?, edit_history=? WHERE id=?",
                 (result, json.dumps(history), pairing_id))
    conn.commit()
    return row_to_dict(conn.execute("SELECT * FROM pairings WHERE id=?", (pairing_id,)).fetchone())

def lock_round(tid, number, locked=True):
    conn = get_conn()
    conn.execute("UPDATE rounds SET locked=? WHERE tournament_id=? AND number=?",
                 (1 if locked else 0, tid, number))
    conn.commit()

def unlock_round(tid, number):
    lock_round(tid, number, locked=False)

def start_tournament(tid, name, total_rounds, tb_order):
    conn = get_conn()
    count = conn.execute("SELECT COUNT(*) FROM players WHERE tournament_id=?", (tid,)).fetchone()[0]
    if count < 2:
        raise ValueError("Need at least 2 players.")
    conn.execute("""UPDATE tournaments SET name=?,total_rounds=?,tb_order=?,status='open',current_round=0
        WHERE id=?""", (name, total_rounds, tb_order, tid))
    conn.commit()
    return get_tournament(tid)


# ── FULL STATE (for hydrating the frontend) ──────────────────────────────────

def get_full_state(tid=1):
    return {
        "tournament": get_tournament(tid),
        "players":    get_players(tid),
        "rounds":     get_rounds(tid),
    }
