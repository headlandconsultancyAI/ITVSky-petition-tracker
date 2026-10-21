# Petition tracker

Tracks a 38 Degrees petition's signature count hour by hour and publishes it as a dashboard on GitHub Pages.

Apify scrapes the petition on the hour. Twenty minutes later a GitHub Action pulls that result, adds it to `data/history.json`, commits it back and republishes the site. The dashboard itself also checks for new data every 15 minutes while it's open.

## What's in the repo

```
petition-tracker/
├── .github/workflows/update-tracker.yml   the hourly job
├── build_tracker.py                       pulls from Apify and builds the site
├── site/index.html                        the dashboard
└── data/
    ├── history.json                       every snapshot so far (starts with the 21 Oct scrape)
    └── events.json                        event markers everyone sees on the charts
```

There's nothing to install. The script only uses Python's standard library.

The built site has four files: the dashboard, `data.json` (every snapshot), `events.json` and `history.csv`, which you can open straight in Excel at `your-site-url/history.csv`.

## One-time setup in Apify

1. Open your actor (`my-actor-1`) and click **Create task**. Put the petition URL in the input and save it with a clear name, e.g. `sky-itv-petition`.
2. On the task, go to **Schedules** and add one that runs **every hour, on the hour** (cron `0 * * * *`).
3. Copy the task ID from the task's page. It's in the URL after `/actors/tasks/`. You can also use `yourusername~sky-itv-petition`.

Make sure it's the task ID. A run ID or actor ID gives a 404.

## One-time setup in GitHub

1. Create a new repository and upload everything in this folder, keeping the `.github/workflows/` folders exactly as they are. If the Actions tab shows nothing later, it's almost always because the workflow file ended up somewhere else.
2. **Settings → Secrets and variables → Actions → New repository secret:** `APIFY_TOKEN`.
3. Same page, **Variables** tab: `APIFY_TASK_ID`, set to the task ID from Apify.
4. **Settings → Pages → Source:** GitHub Actions.
5. **Actions → Update petition tracker → Run workflow** to test it. The run log prints the latest count, and the link to the live site appears on the deploy step.

After that it runs by itself every hour.

### Optional: let GitHub start the scrape

If you'd rather not keep a schedule in Apify, add a variable `APIFY_MODE` set to `run`. The Action then starts the task itself and waits for it. It's one fewer moving part, but GitHub's scheduler can run anywhere from a few minutes to half an hour late, so your snapshots won't land as evenly on the hour. Leave it unset to pull Apify's scheduled runs instead.

## Adding events everyone can see

Edit `data/events.json` in the GitHub web editor and commit. The site republishes within a couple of minutes.

```json
[
  { "time": "2026-10-22T08:10:00Z", "label": "Nandy questioned on the deal on the Today programme" },
  { "time": "2026-10-22T18:30:00Z", "label": "38 Degrees email to its full list" }
]
```

Times are in UTC (the `Z` on the end). In winter that's the same as UK time. During British Summer Time, take an hour off. If you track a second petition later, add `"petition": "the-petition-url"` to an event so it only shows on that one.

Events added in the dashboard itself are only saved in that browser. Use them for your own notes and put anything you want a client to see in `events.json`.

## Testing on your own machine

```bash
python build_tracker.py --file dataset_my-actor-1.json
python -m http.server -d out
```

Then open http://localhost:8000. You need the little web server because browsers won't load `data.json` from a file opened directly.

## When something goes wrong

- **404 from Apify:** run `python build_tracker.py --list-tasks` with `APIFY_TOKEN` set. It prints every task ID on the account, and recent run IDs so you can see which is which.
- **Warning that there's been no new scrape for 3 hours:** the Apify schedule has stopped or the actor is failing. Check the task's runs in Apify. The dashboard header turns red at the same point.
- **"A file called 'data' is in the way":** there's a stray file named `data` in the repo. Delete it so the folder can exist.
- **The schedule's stopped altogether:** GitHub can pause scheduled workflows on inactive repos. The hourly commits should keep it active, but if it ever happens, re-enable it from the Actions tab.

## Worth knowing

- **GitHub Pages on a public repo is public.** The petition data is public anyway, but your event notes will be too. Keep anything client-sensitive out of `events.json`, or host it behind a login instead.
- **Actions minutes:** each run takes under a minute. That's free on a public repo and comfortably inside the 2,000 free minutes a month on a private one.
- **The history grows by about 24 snapshots a day.** That's tiny, so there's no pruning.
