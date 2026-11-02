# Fantasy Football League History Dashboard

A self-updating dashboard for your ESPN fantasy football league: all-time
standings, championships, points for/against, draft boards, and trades,
across every season you've played. A GitHub Action refreshes the data once a
day and redeploys the site automatically — nobody has to run anything by
hand after the initial setup.

## What's in this folder

- `index.html`, `style.css`, `app.js` — the dashboard itself (static, no build step).
- `data/league_history.json` — the data file the dashboard reads. Starts empty; the workflow fills it in.
- `fetch/fetch_data.py` — pulls your league's history from ESPN's API and writes `data/league_history.json`.
- `fetch/requirements.txt` — the one Python dependency (`espn_api`).
- `.github/workflows/update-dashboard.yml` — runs the fetch script daily, commits the refreshed data, and deploys the site to GitHub Pages.

## One-time setup

1. **Create a repo and upload this folder.** Create a new **public** GitHub repository, then upload everything in this folder to it (preserving the folder structure, including the hidden `.github` folder — most drag-and-drop uploaders keep subfolders, but if yours doesn't, use `git` from the command line instead).

2. **Add four repository secrets.** In your repo: **Settings → Secrets and variables → Actions → New repository secret**. Add:
   - `LEAGUE_ID` — your ESPN league ID (`1485136557`)
   - `ESPN_S2` — the `espn_s2` cookie value from your browser
   - `ESPN_SWID` — the `SWID` cookie value from your browser
   - `START_YEAR` — the first season to include (e.g. `2021`)

3. **Enable GitHub Pages via Actions.** **Settings → Pages → Build and deployment → Source → GitHub Actions.**

4. **Run the workflow once manually.** Go to the **Actions** tab, click **"Update Fantasy Football Dashboard"**, then **"Run workflow"**. This does the first data pull and first deploy — after that, it runs on its own every day.

5. **Find your URL.** Once the run finishes, your dashboard is live at:
   `https://<your-github-username>.github.io/<repo-name>/`

## Notes & limitations

- **ESPN cookies can expire** (ESPN doesn't document a fixed lifetime; typically they last a long time but a password change or long inactivity can invalidate them). If the daily run starts failing to fetch new data, re-grab fresh `espn_s2`/`SWID` values from your browser and update the two repo secrets.
- **Champion/runner-up** are read from ESPN's final-standing field once a season is complete; for the in-progress season, these will show "Season in progress" until ESPN finalizes it.
- **Trades** come from ESPN's activity feed for each season (`recent_activity`, filtered to trades). Very old seasons may have thinner data if ESPN's own records for that year are incomplete.
- **Manager identity** is tracked by ESPN owner name so the same person's history stays together even if they rename their team season to season. If ESPN shows a blank name for an owner, that manager will appear as "Unknown" — not a bug in this script.
- The fetch script never crashes the whole run over a single bad season/pick/trade — it logs a warning (visible in the Action's run log) and continues, so one quirky old season won't block the rest.
- Change the schedule by editing the `cron` line in `.github/workflows/update-dashboard.yml` (it's in UTC).

## Updating later

Any time you want to change the start year or re-pull everything from scratch, just update the `START_YEAR` secret and re-run the workflow manually from the Actions tab.
