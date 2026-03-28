# Swiss-Manager Pro — Full-Stack FIDE Tournament System

## Quick Start

```bash
# 1. Make sure Python 3.8+ is installed (no extra packages needed)
python3 --version

# 2. Run the launcher (opens browser automatically)
python3 start.py

# 3. Visit http://localhost:8765
```

## File Structure

```
swiss-manager-backend/
├── start.py           ← Launcher (run this)
├── server.py          ← HTTP REST API server (stdlib only)
├── db.py              ← SQLite database layer
├── pairing_engine.py  ← FIDE Dutch Swiss pairing logic (Python)
├── swiss.db           ← SQLite database (auto-created on first run)
└── static/
    └── index.html     ← Frontend (served by the backend)
```

## REST API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /api/state | Full tournament state (hydrates frontend) |
| GET | /api/tournament | Tournament record |
| PUT | /api/tournament | Update name/rounds/tb_order |
| POST | /api/tournament/start | Start tournament |
| POST | /api/tournament/reset | Reset all data |
| GET | /api/players | List players |
| POST | /api/players | Add one player |
| POST | /api/players/bulk | Bulk import (JSON array) |
| DELETE | /api/players/:id | Remove player |
| DELETE | /api/players | Clear all players |
| GET | /api/rounds | All rounds + pairings |
| POST | /api/rounds/pair | Generate + commit next round |
| PUT | /api/rounds/:n/lock | Lock round n |
| PUT | /api/rounds/:n/unlock | Unlock round n |
| PUT | /api/pairings/:id/result | Set result `{result, force}` |

## Database Schema

```sql
tournaments (id, name, date, total_rounds, current_round, status, tb_order)
players     (id, tournament_id, sno, name, fide_id, rating, country, is_unrated)
rounds      (id, tournament_id, number, locked)
pairings    (id, round_id, tournament_id, white_id, black_id, result, is_bye, edit_history)
```

## Pairing System

- **Round 1**: Slaughter (top-half vs bottom-half by seed)
- **Round 2+**: FIDE Dutch Swiss (BBP) — score groups, S1/S2 split, floaters
- **Colors**: FIDE C.04.3 — CD rule, no 3-in-a-row
- **Tiebreaks**: BH, BH-C1, Median-BH, Sonneborn-Berger, Wins, Progressive
- **Constraints enforced at DB level**: no double-pairing, 300-player cap

## Custom Port

```bash
python3 start.py --port 9000
```
