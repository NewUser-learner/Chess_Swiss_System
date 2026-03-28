"""
pairing_engine.py — FIDE Dutch Swiss Pairing Engine (Python)
Mirrors the JavaScript logic from the frontend exactly for reproducibility.

Input:  full state dict {tournament, players, rounds}
Output: list of pairing dicts [{white, black, result, bye}]
"""

import json


# ── Color helpers ─────────────────────────────────────────────────────────────

def color_cd(hist):
    return hist.count('w') - hist.count('b')

def color_obligation(hist):
    diff = color_cd(hist)
    if diff >= 2:  return 'b'
    if diff <= -2: return 'w'
    real = [c for c in hist if c != 'bye']
    if len(real) >= 2 and real[-1] == real[-2]:
        return 'b' if real[-1] == 'w' else 'w'
    return None

def color_wants(hist):
    ob = color_obligation(hist)
    if ob: return ob
    real = [c for c in hist if c != 'bye']
    if not real: return None
    return 'b' if real[-1] == 'w' else 'w'

def assign_colors(idA, idB, histA, histB, players_by_id):
    obA = color_obligation(histA)
    obB = color_obligation(histB)

    if obA and obB:
        if obA != obB:
            return (idA, idB) if obA == 'w' else (idB, idA)
        absA, absB = abs(color_cd(histA)), abs(color_cd(histB))
        if absA >= absB:
            return (idA, idB) if obA == 'w' else (idB, idA)
        return (idB, idA) if obB == 'w' else (idA, idB)

    if obA: return (idA, idB) if obA == 'w' else (idB, idA)
    if obB: return (idB, idA) if obB == 'w' else (idA, idB)

    wa = color_wants(histA)
    if wa == 'w': return (idA, idB)
    if wa == 'b': return (idB, idA)

    # Equal — lower sno (higher seed) gets white
    sno_a = players_by_id.get(idA, {}).get('sno', 999)
    sno_b = players_by_id.get(idB, {}).get('sno', 999)
    return (idA, idB) if sno_a < sno_b else (idB, idA)


# ── History from rounds ───────────────────────────────────────────────────────

def build_record(players, rounds):
    """
    Returns:
      pts[pid]          float
      color_hist[pid]   list of 'w'|'b'|'bye'
      opp_list[pid]     list of opponent pid or None
      game_res[pid]     list of {opp, score}
    """
    pts        = {p['id']: 0.0 for p in players}
    color_hist = {p['id']: []  for p in players}
    opp_list   = {p['id']: []  for p in players}
    game_res   = {p['id']: []  for p in players}

    for rnd in rounds:
        for pair in rnd['pairings']:
            wid = pair.get('white_id')
            bid = pair.get('black_id')
            res = pair.get('result', '')
            is_bye = pair.get('is_bye', False)

            if is_bye:
                if wid and wid in pts:
                    pts[wid] += 1
                    color_hist[wid].append('bye')
                    opp_list[wid].append(None)
                    game_res[wid].append({'opp': None, 'score': 1})
                continue

            # Record color history regardless of result
            if wid and wid in color_hist:
                color_hist[wid].append('w')
                opp_list[wid].append(bid)
            if bid and bid in color_hist:
                color_hist[bid].append('b')
                opp_list[bid].append(wid)

            ws = bs = None
            if   res == '1-0':  ws, bs = 1.0, 0.0
            elif res == '0-1':  ws, bs = 0.0, 1.0
            elif res == '½-½':  ws, bs = 0.5, 0.5

            if ws is not None:
                if wid and wid in pts: pts[wid] += ws
                if bid and bid in pts: pts[bid] += bs

            if wid and wid in game_res:
                game_res[wid].append({'opp': bid, 'score': ws})
            if bid and bid in game_res:
                game_res[bid].append({'opp': wid, 'score': bs})

    return pts, color_hist, opp_list, game_res


def has_played(pid1, pid2, rounds):
    for rnd in rounds:
        for pair in rnd['pairings']:
            if pair.get('is_bye'): continue
            w, b = pair.get('white_id'), pair.get('black_id')
            if (w == pid1 and b == pid2) or (w == pid2 and b == pid1):
                return True
    return False

def has_bye_already(pid, rounds):
    for rnd in rounds:
        for pair in rnd['pairings']:
            if pair.get('is_bye') and pair.get('white_id') == pid:
                return True
    return False


# ── Tiebreaks for sorting ─────────────────────────────────────────────────────

def compute_standings(players, pts, opp_list, game_res, tb_order='BH,BHC1,MBH,SB,W,P'):
    def bh(pid):
        return sum(pts.get(o, 0) for o in opp_list.get(pid, []) if o)

    def bh_c1(pid):
        sc = sorted(pts.get(o, 0) for o in opp_list.get(pid, []) if o)
        return sum(sc[1:]) if len(sc) > 1 else bh(pid)

    def mbh(pid):
        sc = sorted(pts.get(o, 0) for o in opp_list.get(pid, []) if o)
        return sum(sc[1:-1]) if len(sc) > 2 else bh(pid)

    def sb(pid):
        return sum(g['score'] * pts.get(g['opp'], 0)
                   for g in game_res.get(pid, [])
                   if g['opp'] and g['score'] is not None)

    def wins(pid):
        return sum(1 for g in game_res.get(pid, []) if g['score'] == 1.0)

    def prog(pid):
        cum = total = 0
        for g in game_res.get(pid, []):
            cum += (g['score'] or 0)
            total += cum
        return total

    def sort_key(p):
        pid = p['id']
        key = [-pts.get(pid, 0)]
        for k in tb_order.split(','):
            if k == 'DE': continue
            fn = {'BH': bh, 'BHC1': bh_c1, 'MBH': mbh, 'SB': sb, 'W': wins, 'P': prog}.get(k)
            key.append(-(fn(pid) if fn else 0))
        key.append(p.get('sno', 999))
        return key

    return sorted(players, key=sort_key)


# ── S1/S2 group pairing ───────────────────────────────────────────────────────

def pair_group(group, color_hist, rounds, players_by_id):
    if len(group) < 2:
        return [], list(group)

    n    = len(group)
    half = n // 2
    S1   = group[:half]
    S2   = group[half: half * 2]
    floaters = [group[-1]] if n % 2 == 1 else []

    used_s2 = set()
    pairs   = []

    for i, p in enumerate(S1):
        hP = color_hist.get(p['id'], [])
        best_j, best_score = -1, float('-inf')

        for j, q in enumerate(S2):
            if j in used_s2: continue
            hQ = color_hist.get(q['id'], [])
            score = 100

            if has_played(p['id'], q['id'], rounds): score -= 60

            obP = color_obligation(hP)
            obQ = color_obligation(hQ)
            if obP and obQ:
                score += 25 if obP != obQ else -25
            elif obP or obQ:
                score += 10

            score -= abs(i - j) * 3

            if score > best_score:
                best_score, best_j = score, j

        if best_j != -1:
            used_s2.add(best_j)
            q = S2[best_j]
            w, b = assign_colors(p['id'], q['id'],
                                  color_hist.get(p['id'], []),
                                  color_hist.get(q['id'], []),
                                  players_by_id)
            pairs.append({'white': w, 'black': b})
        else:
            floaters.append(p)

    for j, q in enumerate(S2):
        if j not in used_s2:
            floaters.append(q)

    return pairs, floaters


# ── Main entry point ──────────────────────────────────────────────────────────

def generate_pairings(state):
    """
    state: {tournament, players, rounds}
    Returns list of dicts:
      {white: pid, black: pid|None, result: '', bye: bool}
    """
    tournament = state['tournament']
    players    = state['players']
    rounds     = state['rounds']
    round_num  = len(rounds) + 1

    players_by_id = {p['id']: p for p in players}

    pts, color_hist, opp_list, game_res = build_record(players, rounds)

    # BYE assignment (odd player count)
    bye_id = None
    if len(players) % 2 == 1:
        ranked = compute_standings(players, pts, opp_list, game_res, tournament.get('tb_order', 'BH,BHC1,MBH,SB,W,P'))
        for p in reversed(ranked):
            if not has_bye_already(p['id'], rounds):
                bye_id = p['id']
                break
        if not bye_id:
            bye_id = ranked[-1]['id']

    final_pairs = []

    if round_num == 1:
        # ROUND 1: Slaughter — top-half vs bottom-half
        pool = [p for p in players if p['id'] != bye_id]  # already sorted by sno
        n    = len(pool)
        half = n // 2
        top  = pool[:half]
        bot  = pool[half:]
        for i, (p, q) in enumerate(zip(top, bot)):
            w, b = (p['id'], q['id']) if i % 2 == 0 else (q['id'], p['id'])
            final_pairs.append({'white': w, 'black': b})

    else:
        # ROUND 2+: Score groups
        ranked = compute_standings(players, pts, opp_list, game_res, tournament.get('tb_order', 'BH,BHC1,MBH,SB,W,P'))
        pool   = [p for p in ranked if p['id'] != bye_id]

        # Build score groups (preserve ranked order within group)
        from collections import OrderedDict
        gmap = OrderedDict()
        for p in pool:
            key = pts.get(p['id'], 0)
            gmap.setdefault(key, []).append(p)

        group_keys = sorted(gmap.keys(), reverse=True)
        floaters   = []

        for gi, key in enumerate(group_keys):
            group = floaters + gmap[key]
            floaters = []

            pairs, new_floaters = pair_group(group, color_hist, rounds, players_by_id)
            final_pairs.extend(pairs)

            if new_floaters:
                if gi < len(group_keys) - 1:
                    floaters = new_floaters
                else:
                    # Last group — pair remaining among themselves
                    for i in range(0, len(new_floaters) - 1, 2):
                        p, q = new_floaters[i], new_floaters[i + 1]
                        w, b = assign_colors(p['id'], q['id'],
                                             color_hist.get(p['id'], []),
                                             color_hist.get(q['id'], []),
                                             players_by_id)
                        final_pairs.append({'white': w, 'black': b})

    # Build output list
    result = [{'white': pr['white'], 'black': pr['black'], 'result': '', 'bye': False}
              for pr in final_pairs]

    if bye_id:
        result.append({'white': bye_id, 'black': None, 'result': 'bye', 'bye': True})

    return result
