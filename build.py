"""Refresh data/rosters.json and photos/ from the bc-roma-2627-analysis repo.

    python build.py                                  # analysis repo expected at ../bc-roma-2627-analysis
    python build.py --analysis C:/path/to/bc-roma-2627-analysis

Reads (all from the analysis repo):
    data/team_rosters.csv, data/eurocup/people.csv       the rosters (BC Roma itself is left out)
    data/box_scores.csv, data/eurocup_2026_raw.txt       season averages per player
    data/games.csv, data/eurocup/results.csv, weekly/schedule.csv   BC Roma's games -> "GAME #n" and the next game per team
    data/photos/<player_id>.jpg, data/eurocup/photos/<photo_name>.jpg   240 px headshots, the fallback when the
                                                                         league's original cannot be fetched
Fetches (network):
    lba-media S3 (picture_key), EuroCup photo_url    original headshots, once per player (kept at <= 640 px)
    legabasket.it match header, api-live.euroleague.net games   referee crews of games in the next REF_DAYS days
    aiaponline.it/associati/<first-last>             those referees' profile photos, once per referee, with
                                                     the logo-wall backdrop removed (needs rembg[cpu])
Writes:
    data/rosters.json   teams, players, stats, games (with "refs" once a crew is designated), plus the lists of
                        available photos, logos and referee photos
    photos/<player id>.jpg, referees/<ref key>.jpg

Run it whenever rosters or stats changed in the analysis repo (after its morning collection), then commit.
Logos are not touched: logos/<team id>.png is maintained by hand (see README). A referee photo added by hand
to referees/ is kept as it is.
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import functools
import io
import json
import re
import sys
import unicodedata
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
LBA_MATCH = "https://www.legabasket.it/api/championships/get-championships-matches-by-id?id={}"
EC_GAMES = "https://api-live.euroleague.net/v2/competitions/U/seasons/U{season}/games?teamCode={club}&limit=100"
HTTP_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; bc-roma-scouting)", "Accept": "application/json"}
HTTP_TIMEOUT_S = 30
REF_DAYS = 10   # crews are looked up only for games this close: they are designated a few days before
AIAP = "https://www.aiaponline.it"   # the Italian referees' association: /associati/<first-last> has a profile photo
REF_PHOTO_MAX = (480, 600)
REF_MATTING_MODEL = "isnet-general-use"   # rembg model that cuts the referee out of the logo wall cleanly
ROLE_LBA = {"Playmaker": "PG", "Play/Guardia": "PG/SG", "Guardia": "SG", "Guardia/Ala": "SG/SF", "Ala": "SF", "Ala/Centro": "PF/C", "Centro": "C", "-": ""}
ROLE_EC = {"Guard": "SG", "Forward": "SF", "Center": "C"}
MY_TEAM, MY_CODE = "BC Roma", "BCR"
PHOTO_MAX = (640, 1280)   # headshots are cropped further for the slides, so they are kept well above screen size
LBA_PHOTO = "https://lba-media.s3.eu-south-1.amazonaws.com/{}"
THUMB_W = 240   # width of the analysis repo's thumbnails: a photo this narrow still waits for its original


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


def get_json(url: str) -> dict | None:
    """Return the parsed JSON at url, or None (logged) when the request fails.

    Args:
        url: The address to fetch.

    Returns:
        The decoded JSON object, or None on a network or decoding error.
    """
    try:
        with urlopen(Request(url, headers=HTTP_HEADERS), timeout=HTTP_TIMEOUT_S) as resp:
            return json.loads(resp.read())
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"referees: {url} failed ({exc})")
        return None


def ref(first: str, last: str) -> dict:
    """A crew member as stored in rosters.json: first name, SURNAME and the referees/<key>.jpg photo key.

    Args:
        first: Given name, any case.
        last: Surname, any case.

    Returns:
        {"first": "Andrea", "last": "VALZANI", "key": "valzani_andrea"}.
    """
    first, last = first.strip().title(), last.strip().upper()
    key = unicodedata.normalize("NFKD", f"{last} {first}").encode("ascii", "ignore").decode().lower()
    return {"first": first, "last": last, "key": re.sub(r"\W+", "_", key).strip("_")}


def lba_crew(game_id: str) -> list[dict]:
    """The designated LBA crew of a game, crew chief first; empty until designated.

    Args:
        game_id: legabasket.it game id.

    Returns:
        Up to three ref() entries.
    """
    data = get_json(LBA_MATCH.format(game_id)) or {}
    return [ref(r.get("name", ""), r.get("surname", "")) for r in data.get("referees") or [] if r.get("surname")]


def eurocup_crews(season: str, club: str) -> dict[str, list[dict]]:
    """Game date -> designated EuroCup crew (crew chief first) for every game of a club with one.

    Args:
        season: Season year, e.g. "2026".
        club: EuroLeague club code, e.g. "BCR".

    Returns:
        A mapping from ISO date to up to three ref() entries.
    """
    data = get_json(EC_GAMES.format(season=season, club=club)) or {}
    out = {}
    for g in data.get("data", []):
        crew = []
        for i in (1, 2, 3):
            name = (g.get(f"referee{i}") or {}).get("name", "")
            if name:
                last, _, first = name.partition(",")
                crew.append(ref(first, last))
        if crew:
            out[g["date"][:10]] = crew
    return out


def referee_photo(r: dict, dest: Path) -> bool:
    """Save the referee's AIAP profile photo as dest, unless dest already exists (a hand-added file wins).

    Args:
        r: A ref() entry; its first name and surname make the profile address.
        dest: Output JPEG path.

    Returns:
        True when dest exists afterwards (foreign referees have no AIAP profile).
    """
    if dest.exists():
        return True
    slug = re.sub(r"\W+", "-", unicodedata.normalize("NFKD", f"{r['first']} {r['last']}").encode("ascii", "ignore").decode().lower()).strip("-")
    try:
        with urlopen(Request(f"{AIAP}/associati/{slug}", headers=HTTP_HEADERS), timeout=HTTP_TIMEOUT_S) as resp:
            page = resp.read().decode("utf-8", "ignore")
        src = re.search(r'alt="Foto di [^"]*"[^>]*?src="([^"]+)"', page)
        if not src:
            print(f"referee photo: no picture on the AIAP page of {r['first']} {r['last']}")
            return False
        with urlopen(Request(AIAP + src.group(1).replace("&amp;", "&"), headers=HTTP_HEADERS), timeout=HTTP_TIMEOUT_S) as resp:
            data = io.BytesIO(resp.read())
    except (HTTPError, URLError, TimeoutError) as exc:
        print(f"referee photo: {r['first']} {r['last']} not found on AIAP ({exc})")
        return False
    from PIL import Image
    with Image.open(data) as raw:
        im = cut_out(raw.convert("RGB"))
    im.thumbnail(REF_PHOTO_MAX)
    dest.parent.mkdir(exist_ok=True)
    im.save(dest, "JPEG", quality=88, optimize=True)
    return True


@functools.cache
def _matting_session():
    """The background-removal model, loaded on first use (rembg downloads it once, about 180 MB)."""
    from rembg import new_session
    return new_session(REF_MATTING_MODEL)


def cut_out(im):
    """Return the RGB image with its backdrop (the AIAP logo wall) replaced by white.

    Without rembg installed the image comes back unchanged, with a note.

    Args:
        im: An RGB PIL image of one person.

    Returns:
        An RGB PIL image of the same size.
    """
    from PIL import Image
    try:
        from rembg import remove
    except ImportError:
        print("referee photo: rembg not installed (pip install 'rembg[cpu]'), backdrop kept")
        return im
    cut = remove(im, session=_matting_session())
    flat = Image.new("RGB", cut.size, "white")
    flat.paste(cut, mask=cut.getchannel("A"))
    return flat


def headshot(url: str, fallback: Path, dest: Path) -> bool:
    """Write dest as a JPEG of at most PHOTO_MAX, from the league's original picture.

    A dest wider than a thumbnail is kept (so each original is downloaded once); when the original cannot be
    fetched, the analysis repo's small thumbnail is used instead. Transparent backgrounds become white.

    Args:
        url: The original picture's address ("" when the league has none).
        fallback: The analysis repo's thumbnail of the same player.
        dest: Output path.

    Returns:
        True when dest exists afterwards.
    """
    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError:
        sys.exit("Pillow is needed for the photos: pip install pillow")
    if dest.exists():
        with Image.open(dest) as cur:
            if cur.width > THUMB_W:
                return True
    src: io.BytesIO | Path = fallback
    if url:
        try:
            with urlopen(Request(url, headers=HTTP_HEADERS), timeout=HTTP_TIMEOUT_S) as resp:
                src = io.BytesIO(resp.read())
        except (HTTPError, URLError, TimeoutError) as exc:
            print(f"photo {url} failed ({exc}), using the thumbnail")
    try:
        with Image.open(src) as raw:
            im = raw.convert("RGBA")
    except (FileNotFoundError, UnidentifiedImageError):
        return dest.exists()
    flat = Image.new("RGB", im.size, "white")
    flat.paste(im, mask=im.getchannel("A"))
    flat.thumbnail(PHOTO_MAX)
    buf = io.BytesIO()
    flat.save(buf, "JPEG", quality=85, optimize=True)
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
    soon = (dt.date.today() + dt.timedelta(days=REF_DAYS)).isoformat()

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
        url = LBA_PHOTO.format(r["picture_key"]) if r.get("picture_key") else ""
        if headshot(url, A / "data" / "photos" / f"{r['player_id']}.jpg", ROOT / "photos" / f"{pid}.jpg"):
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
        if headshot(r.get("photo_url") or "", A / "data" / "eurocup" / "photos" / f"{photo_name(r['player'])}.jpg", ROOT / "photos" / f"{pid}.jpg"):
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
            teams[k]["games"].append({"date": d, "home": g["home_team"] == MY_TEAM, "played": d < today, "round": "R" + g["round"], "n": my_lba.index(d) + 1,
                                      "refs": lba_crew(g["game_id"]) if today <= d <= soon else []})
    # a EuroCup season is named after the year it starts in (U2026 = 2026-27, July on)
    season = dt.date.today().year - (dt.date.today().month < 7)
    ec_soon = any(s["competition"] == "EuroCup" and today <= s["date"] <= soon for s in sched)
    ec_crews = eurocup_crews(str(season), MY_CODE) if ec_soon else {}
    for s in sched:
        if s["competition"] != "EuroCup":
            continue
        code = [c for c, n in code2name.items() if n == s["opponent"]]
        k = "ec-" + code[0] if code else ""
        if k in teams:
            teams[k]["games"].append({"date": s["date"], "home": s["home"] == "1", "played": s["date"] < today, "round": "", "n": my_ec.index(s["date"]) + 1 if s["date"] in my_ec else None,
                                      "refs": ec_crews.get(s["date"], []) if today <= s["date"] <= soon else []})
    for t in teams.values():
        t["games"].sort(key=lambda g: g["date"])
    out = sorted(teams.values(), key=lambda t: (min([g["date"] for g in t["games"] if not g["played"]] or ["9999"]), t["name"]))

    for r in {r["key"]: r for t in out for g in t["games"] for r in g["refs"]}.values():
        referee_photo(r, ROOT / "referees" / f"{r['key']}.jpg")
    logos = sorted(p.stem for p in (ROOT / "logos").glob("*.png"))
    ref_photos = sorted(p.stem for p in (ROOT / "referees").glob("*.jpg"))
    (ROOT / "data").mkdir(exist_ok=True)
    (ROOT / "data" / "rosters.json").write_text(json.dumps({"asof": today, "teams": out, "photos": sorted(photos), "logos": logos, "refphotos": ref_photos},
                                                           ensure_ascii=False), encoding="utf-8")
    n_players = sum(len(t["players"]) for t in out)
    n_stats = sum(1 for t in out for p in t["players"] if p["stats"])
    crews = [f"{t['name']} {g['date']}: {', '.join(r['last'] for r in g['refs'])}" for t in out for g in t["games"] if g["refs"]]
    print(f"{len(out)} teams, {n_players} players ({n_stats} with stats), {len(photos)} photos, {len(logos)} logos -> data/rosters.json")
    print("crews: " + ("; ".join(crews) if crews else f"none designated yet for the next {REF_DAYS} days"))


if __name__ == "__main__":
    main()
