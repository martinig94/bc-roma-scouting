"""Refresh data/rosters.json and photos/ from the bc-roma-2627-analysis repo.

    python build.py                                  # analysis repo expected at ../bc-roma-2627-analysis
    python build.py --analysis C:/path/to/bc-roma-2627-analysis

Reads (all from the analysis repo):
    data/team_rosters.csv, data/eurocup/people.csv       the rosters (BC Roma itself is left out)
    data/box_scores.csv, data/eurocup_2026_raw.txt       season averages per player
    data/games.csv, data/eurocup/results.csv, weekly/schedule.csv   BC Roma's games -> "GAME #n" and the next game per team
    data/photos/<player_id>.jpg, data/eurocup/photos/<photo_name>.jpg   headshots (resized to <= 240 px here)
Writes:
    data/rosters.json   teams, players, stats, games, plus the lists of available photos and logos
    photos/<player id>.jpg

Run it whenever rosters or stats changed in the analysis repo (after its morning collection), then commit.
Logos are not touched: logos/<team id>.png is maintained by hand (see README).
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import io
import json
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ROLE_LBA = {"Playmaker": "PG", "Play/Guardia": "PG/SG", "Guardia": "SG", "Guardia/Ala": "SG/SF", "Ala": "SF", "Ala/Centro": "PF/C", "Centro": "C", "-": ""}
ROLE_EC = {"Guard": "SG", "Forward": "SF", "Center": "C"}
MY_TEAM, MY_CODE = "BC Roma", "BCR"
PHOTO_MAX = (240, 480)


def player_key(name: str) -> str:
    """'Timmy Allen' and 'ALLEN, TIMMY' -> 'allen t' (same rule as the analysis repo's player_names.py)."""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower().strip()
    if "," in s:
        last, first = [x.strip() for x in s.split(",", 1)]
    else:
        parts = s.split()
        first, last = parts[0], " ".join(parts[1:]) if len(parts) > 1 else parts[0]
    return f"{last} {first[:1]}".strip()


def photo_name(player: str) -> str:
    return re.sub(r"\W+", "_", player_key(player)).strip("_")


def read_csv(p: Path) -> list[dict]:
    with p.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def avg(rows: list[dict]) -> dict | None:
    g = len(rows)
    if not g:
        return None
    s = lambda k: sum(r[k] for r in rows)
    pct = lambda m, a: round(100 * s(m) / s(a)) if s(a) else None
    per = lambda k: round(s(k) / g, 1)
    return {"g": g, "min": per("min"), "pts": per("pts"), "reb": per("reb"), "oreb": per("oreb"), "ast": per("ast"), "stl": per("stl"), "blk": per("blk"),
            "to": per("to"), "pf": per("pf"), "fg2m": per("fg2m"), "fg2a": per("fg2a"), "fg3m": per("fg3m"), "fg3a": per("fg3a"), "ftm": per("ftm"), "fta": per("fta"),
            "fg2p": pct("fg2m", "fg2a"), "fg3p": pct("fg3m", "fg3a"), "ftp": pct("ftm", "fta"), "pir": per("pir")}


def lba_stats(box: list[dict]) -> dict[str, list[dict]]:
    out = collections.defaultdict(list)
    for r in box:
        if r["row_type"] != "player" or int(r["sec"] or 0) <= 0:
            continue
        out[r["player_id"]].append({"min": int(r["sec"]) / 60, "pts": int(r["pts"]), "reb": int(r["reb"]), "oreb": int(r["oreb"]), "ast": int(r["ast"]), "stl": int(r["stl"]),
                                    "blk": int(r["blk"]), "to": int(r["tov"]), "pf": int(r["pf"]), "fg2m": int(r["fg2m"]), "fg2a": int(r["fg2a"]), "fg3m": int(r["fg3m"]),
                                    "fg3a": int(r["fg3a"]), "ftm": int(r["ftm"]), "fta": int(r["fta"]), "pir": int(r["val"])})
    return out


def eurocup_stats(raw: Path) -> dict[tuple[str, str], list[dict]]:
    """(TEAM NAME, player key) -> game rows, from the raw box-score lines (format: notebooks/eurocup_fetch.md in the analysis repo)."""
    out = collections.defaultdict(list)
    for line in raw.read_text(encoding="utf-8").splitlines():
        p = line.split("|")
        if len(p) < 22 or not p[0].isdigit() or p[2] in ("TOTAL", "QUARTERS") or ":" not in p[4]:
            continue
        mm, ss = p[4].split(":")
        pts, m2, a2, m3, a3, ftm, fta, orb, drb, ast, stl, to, blk, pf, _pfr, _pm, pir = map(int, p[5:22])
        out[(p[1], player_key(p[2]))].append({"min": int(mm) + int(ss) / 60, "pts": pts, "reb": orb + drb, "oreb": orb, "ast": ast, "stl": stl, "blk": blk, "to": to, "pf": pf,
                                              "fg2m": m2, "fg2a": a2, "fg3m": m3, "fg3a": a3, "ftm": ftm, "fta": fta, "pir": pir})
    return out


def thumbnail(src: Path, dest: Path) -> bool:
    try:
        from PIL import Image
    except ImportError:
        sys.exit("Pillow is needed for the photos: pip install pillow")
    try:
        im = Image.open(src).convert("RGB")
    except Exception:
        return False
    im.thumbnail(PHOTO_MAX)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85, optimize=True)
    dest.write_bytes(buf.getvalue())
    return True


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--analysis", default=str(ROOT.parent / "bc-roma-2627-analysis"), help="path of the bc-roma-2627-analysis repo")
    a = ap.parse_args()
    A = Path(a.analysis)
    if not (A / "data" / "team_rosters.csv").exists():
        sys.exit(f"analysis repo not found at {A} (pass --analysis)")
    today = dt.date.today().isoformat()

    lba = read_csv(A / "data" / "team_rosters.csv")
    ec = read_csv(A / "data" / "eurocup" / "people.csv")
    games = read_csv(A / "data" / "games.csv")
    sched = read_csv(A / "weekly" / "schedule.csv")
    ecres = read_csv(A / "data" / "eurocup" / "results.csv")
    lstats = lba_stats(read_csv(A / "data" / "box_scores.csv"))
    estats = eurocup_stats(A / "data" / "eurocup_2026_raw.txt")
    code2name: dict[str, str] = {}
    for r in ecres:
        code2name[r["home_code"]] = r["home"]
        code2name[r["away_code"]] = r["away"]

    (ROOT / "photos").mkdir(exist_ok=True)
    photos: list[str] = []
    teams: dict[str, dict] = {}

    def team(key, name, comp):
        return teams.setdefault(key, {"id": key, "name": name, "comp": comp, "games": [], "players": []})

    for r in lba:
        if r["team"] == MY_TEAM:
            continue
        pid = "lba-" + r["player_id"]
        t = team("lba-" + r["team_id"], r["team"], "LBA")
        t["players"].append({"id": pid, "first": r["name"], "last": r["surname"], "name": f"{r['name']} {r['surname']}".strip(), "num": r["number"], "height": r["height_cm"],
                             "born": r["birth_date"][:4], "country": r["country"], "role": ROLE_LBA.get(r["role"], ""), "stats": avg(lstats.get(r["player_id"], []))})
        if thumbnail(A / "data" / "photos" / f"{r['player_id']}.jpg", ROOT / "photos" / f"{pid}.jpg"):
            photos.append(pid)
    for r in ec:
        if r["club"] == MY_CODE:
            continue
        name = code2name.get(r["club"], r["club"])
        pid = "ec-" + r["club"] + "-" + r["player"].replace(" ", "_")
        t = team("ec-" + r["club"], name, "EuroCup")
        k = player_key(r["player"])
        rows = estats.get((name.upper(), k))
        if not rows:
            cand = [x for x in estats if x[1] == k]
            rows = estats[cand[0]] if len(cand) == 1 else []
        parts = r["player"].split(" ")
        t["players"].append({"id": pid, "first": parts[0], "last": " ".join(parts[1:]), "name": r["player"], "num": r["number"], "height": r["height_cm"].replace(".0", ""),
                             "born": "", "country": "", "role": ROLE_EC.get(r["position"], ""), "stats": avg(rows)})
        if thumbnail(A / "data" / "eurocup" / "photos" / f"{photo_name(r['player'])}.jpg", ROOT / "photos" / f"{pid}.jpg"):
            photos.append(pid)

    # BC Roma's games: per team the dates, and "GAME #n" counted along BC Roma's schedule in that competition
    name2id = {r["team"]: r["team_id"] for r in lba}
    my_lba = sorted(g["match_datetime"][:10] for g in games if MY_TEAM in (g["home_team"], g["away_team"]))
    my_ec = sorted(set([r["date"] for r in ecres if MY_CODE in (r["home_code"], r["away_code"])] + [s["date"] for s in sched if s["competition"] == "EuroCup"]))
    for g in games:
        if MY_TEAM not in (g["home_team"], g["away_team"]):
            continue
        opp = g["away_team"] if g["home_team"] == MY_TEAM else g["home_team"]
        k = "lba-" + name2id.get(opp, "")
        if k in teams:
            d = g["match_datetime"][:10]
            teams[k]["games"].append({"date": d, "home": g["home_team"] == MY_TEAM, "played": d < today, "round": "R" + g["round"], "n": my_lba.index(d) + 1})
    for s in sched:
        if s["competition"] != "EuroCup":
            continue
        code = [c for c, n in code2name.items() if n == s["opponent"]]
        k = "ec-" + code[0] if code else ""
        if k in teams:
            teams[k]["games"].append({"date": s["date"], "home": s["home"] == "1", "played": s["date"] < today, "round": "", "n": my_ec.index(s["date"]) + 1 if s["date"] in my_ec else None})
    for t in teams.values():
        t["games"].sort(key=lambda g: g["date"])
    out = sorted(teams.values(), key=lambda t: (min([g["date"] for g in t["games"] if not g["played"]] or ["9999"]), t["name"]))

    logos = sorted(p.stem for p in (ROOT / "logos").glob("*.png")) if (ROOT / "logos").exists() else []
    (ROOT / "data").mkdir(exist_ok=True)
    (ROOT / "data" / "rosters.json").write_text(json.dumps({"asof": today, "teams": out, "photos": sorted(photos), "logos": logos}, ensure_ascii=False), encoding="utf-8")
    n_players = sum(len(t["players"]) for t in out)
    n_stats = sum(1 for t in out for p in t["players"] if p["stats"])
    print(f"{len(out)} teams, {n_players} players ({n_stats} with stats), {len(photos)} photos, {len(logos)} logos -> data/rosters.json")


if __name__ == "__main__":
    main()
