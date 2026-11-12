# BC Roma opponent scouting

A one-page tool to tag the players of BC Roma's next opponents while watching clips (role, shooting hand,
tags, slide bullets, to-dos, stat picks, close-out colour, markers, notes) and to turn the notes into the
scouting deck: the `{{name}}` slide of `template.pptx` repeated once per player, plus the cover, roster and
stats slides filled for the team.

Rosters, season averages and headshots come from the [bc-roma-2627-analysis](../bc-roma-2627-analysis) repo.

## Run it

```bash
python serve.py            # then open http://localhost:8787/
```

`serve.py` is a 100-line static server: every click is written to `data/scouting.json`, so the notes are
versioned with the repo (commit after a scouting session). Uploading a new template or a team logo through
the page writes `template.pptx` / `logos/<team>.png` as well.

The page also works without the server, e.g. on GitHub Pages or `python -m http.server`: then the notes stay
in that browser (localStorage) and travel through the *Download / Import scouting.json* buttons. Keep in mind
that a GitHub Pages site of a free account is public.

## Refresh rosters and stats

```bash
python build.py                                  # analysis repo at ../bc-roma-2627-analysis
python build.py --analysis /path/to/bc-roma-2627-analysis
git add data/rosters.json photos && git commit -m "rosters as of $(date +%F)"
```

`build.py` rewrites `data/rosters.json` (teams ordered by BC Roma's next game, players, season averages,
game numbers) and the `photos/` headshots: each player's original picture (legabasket.it media, EuroCup
API) is downloaded once and kept at 640 px wide, so the slides' head-shot crop stays sharp; the analysis
repo's 240 px thumbnail is the fallback. Needs Pillow.

It also looks up the referee crew of BC Roma's games in the next 10 days: the LBA match header on
legabasket.it and the EuroCup game on api-live.euroleague.net, crew chief first. LBA designates during the
week (the crew for a Saturday game is usually out by Thursday); EuroCup can be as late as game day. The
GitHub workflow runs at 07:20 and 15:00 UTC, so the page and the referees slide pick a crew up the same day.
Each designated referee's photo comes from their profile on the referees' association site
(`aiaponline.it/associati/<first name>-<surname>`) and is saved once as `referees/<surname>_<first name>.jpg`
(lowercase, ASCII, `_` for spaces and punctuation, e.g. `capotorto_gianluca.jpg`). Foreign EuroCup referees
have no profile there: drop a photo under that name by hand (a file already in `referees/` is never
replaced); a referee without one gets a name-only column.

## Files

| path | what |
|---|---|
| `index.html` | the page (vanilla JS; jsPDF and JSZip from cdnjs) |
| `serve.py` | local server + save API |
| `build.py` | data refresh from the analysis repo |
| `data/rosters.json` | generated: rosters, stats, games, photo and logo lists |
| `data/scouting.json` | your notes (players, tag lists, team settings, template choice) |
| `template.pptx` | the deck template: one slide carrying `{{name}} {{surname}} {{number}} {{height}} {{role}} {{hand}} {{minutes}} {{points}} {{stat_1}} {{stat_2}} {{bullet_1..3}} {{to_do1..3}} {{iso}} {{photo}}`, a CLOSE OUT table, parked 🔑/🚀 shapes; a cover with `<COMP> - GAME #n`; a roster table headed PG/SG/SF/PF/C; a stats table headed `FGM-A`; a referees slide with `{{ref1_first}} {{ref1_last}}` (crew chief) to `{{ref3_…}}` and pictures named `Referee 1 photo` to `Referee 3 photo` |
| `logos/<team id>.png` | opponent crests (legabasket.it media CDN, EuroCup API); `lba-<team_id>` / `ec-<club code>` |
| `photos/<player id>.jpg` | generated headshots |
| `referees/<surname>_<first name>.jpg` | referee photos (AIAP profiles, or added by hand) |

Team ids are `lba-<team_id>` (from `data/teams.csv` of the analysis repo) and `ec-<EuroLeague club code>`.

## The same page on claude.ai

The page detects where it runs: on claude.ai (as an artifact) it uses the artifact's own database and
file-save prompt; behind `serve.py` it uses the save API; anywhere else it is browser-only.
