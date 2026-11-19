# BC Roma opponent scouting

A one-page tool to tag the players of BC Roma's next opponents while watching clips (role, shooting hand,
tags, slide bullets, to-dos, stat picks, close-out colour, markers, notes) and to turn the notes into the
scouting deck: the `{{name}}` slide of `template.pptx` repeated once per player, plus the cover, roster and
stats slides filled for the team.

On a player's card a new tag or to-do can be typed straight on its row (Enter adds it to the shared list and
to the player); the slide bullets are the tags marked with a star, up to three. *Preview slides* builds
the deck and draws every slide in the page, with a *Download PowerPoint* button for that same deck; the
drawing uses the deck's fonts when they are installed on the computer, so line breaks can differ a little
from PowerPoint.

Rosters, season averages and headshots come from the [bc-roma-2627-analysis](../bc-roma-2627-analysis) repo.

## Run it

```bash
python serve.py            # then open http://localhost:8787/
```

`serve.py` is a 100-line static server: every click is written to `data/scouting.json`, so the notes are
versioned with the repo (commit after a scouting session). Uploading a new template or a team logo through
the page writes `template.pptx` / `logos/<team>.png` as well.

The page also works without the server, e.g. on GitHub Pages or `python -m http.server`: then the notes stay
in that browser (localStorage) and travel through the *Download / Import scouting.json* buttons. A team logo can still be uploaded there (up to
300 KB, kept with the notes); a new template cannot. Keep in mind
that a GitHub Pages site of a free account is public.

## Share the notes (Supabase)

For a staff working on the same notes from their own devices, the page (on GitHub Pages or any static host)
can keep them in a [Supabase](https://supabase.com) project: everyone signs in with an email and password,
and an edit shows up in the others' browsers as it is saved. The free plan is enough for a handful of users;
it pauses a project after about a week without activity (restore it from the dashboard).

1. Create a Supabase project and run `supabase/setup.sql` in its SQL editor.
2. Authentication > Sign In / Providers: turn **off** "Allow new users to sign up". The database lets every
   signed-in user read and write, so with sign-ups on anybody could register and get in.
3. Authentication > Users > Add user, with "Auto Confirm User": one per person (email and password).
4. Project Settings > API: copy the project URL and the publishable (anon) key into `SUPABASE` at the top of
   the script in `index.html`. Both are meant to be public. Never put the secret (service role) key there.
5. Open the page, sign in, and bring the existing notes in with *JSON > Import scouting.json*.

*JSON > Download scouting.json* gives a backup of the shared notes. Two people saving the same player (or the
same team's settings) at the same moment: the last save wins. An uploaded template or logo goes to the
project's `scouting` storage bucket, which is readable by link. Behind `serve.py` the page keeps using
`data/scouting.json`, whatever `SUPABASE` says.

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
| `supabase/setup.sql` | table, access rules and storage bucket of the shared (Supabase) mode |
| `build.py` | data refresh from the analysis repo |
| `data/rosters.json` | generated: rosters, stats, games, photo and logo lists |
| `data/scouting.json` | your notes (players, tag lists, team settings, template choice) |
| `template.pptx` | the deck template: one slide carrying `{{name}} {{surname}} {{number}} {{height}} {{role}} {{hand}} {{minutes}} {{points}} {{stat_1}} {{stat_2}} {{bullet_1..3}} {{to_do1..3}} {{iso}} {{photo}}`, a CLOSE OUT table, parked 🔑/🚀 shapes; a cover with `<COMP> - GAME #n`; an `Offensive` / `Defensive` slide with one bulleted text box each and a `Keys to` `WIN` slide with one bulleted box (defence keys, an empty line, offence keys), all rewritten from the team's "Game plan" boxes when filled; a roster table headed PG/SG/SF/PF/C; a stats table headed `FGM-A`; a referees slide with `{{ref1_first}} {{ref1_last}}` (crew chief) to `{{ref3_…}}` and pictures named `Referee 1 photo` to `Referee 3 photo` |
| `logos/<team id>.png` | opponent crests (legabasket.it media CDN, EuroCup API); `lba-<team_id>` / `ec-<club code>` |
| `photos/<player id>.jpg` | generated headshots |
| `referees/<surname>_<first name>.jpg` | referee photos (AIAP profiles, or added by hand) |

Team ids are `lba-<team_id>` (from `data/teams.csv` of the analysis repo) and `ec-<EuroLeague club code>`.

## The same page on claude.ai

The page detects where it runs: on claude.ai (as an artifact) it uses the artifact's own database and
file-save prompt; behind `serve.py` it uses the save API; with `SUPABASE` filled in it uses that project; anywhere else it is
browser-only.
