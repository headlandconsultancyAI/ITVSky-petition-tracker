"""Petition tracker build.

Pulls the latest petition scrape from Apify, merges it into an accumulating
history in data/history.json, and writes the static site into out/:

    out/index.html    the dashboard (copied from site/index.html)
    out/data.json     every snapshot, in the same shape the scraper produces
    out/events.json   shared event markers (copied from data/events.json)
    out/history.csv   every snapshot as a spreadsheet-friendly table

Pull the most recent successful run of a scheduled Apify task:

    python build_tracker.py --task username~sky-itv-petition

Or have this script start the task and wait for the result:

    python build_tracker.py --task username~sky-itv-petition --mode run

Test locally from an export you already have:

    python build_tracker.py --file dataset_my-actor-1.json

Not sure of the task ID? This lists every task and recent run on the account:

    python build_tracker.py --list-tasks

The Apify token is read from the APIFY_TOKEN environment variable. Standard
library only, so there's nothing to install.
"""

import argparse
import csv
import json
import os
import pathlib
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

API = "https://api.apify.com/v2"
META_KEYS = [
    "url", "actionGuid", "journeyGuid", "actionType", "title", "campaignName",
    "decisionTarget", "senderName", "imageUrl", "imageAltText", "petitionHtml",
]
STALE_HOURS = 3


# ---------- Apify ----------

def apify(path, token, method="GET", params=None, timeout=60):
    query = "?" + urllib.parse.urlencode(params) if params else ""
    req = urllib.request.Request(API + path + query, method=method)
    req.add_header("Authorization", "Bearer " + token)
    if method == "POST":
        req.add_header("Content-Type", "application/json")
        req.data = b"{}"
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:300]
        hint = ""
        if e.code == 401:
            hint = " The token was rejected. Check the APIFY_TOKEN secret."
        elif e.code == 404:
            hint = (" Apify couldn't find that task. Make sure it's a task ID, not an actor"
                    " or run ID. Run with --list-tasks to see the valid ones.")
        sys.exit("Apify returned %s for %s.%s\n%s" % (e.code, path, hint, body))
    except urllib.error.URLError as e:
        sys.exit("Couldn't reach Apify: %s" % e.reason)


def pull(task, token, mode):
    task_path = "/actor-tasks/" + urllib.parse.quote(task, safe="~")
    params = {"clean": "true", "format": "json"}
    if mode == "run":
        print("Starting task %s and waiting for it to finish" % task)
        return apify(task_path + "/run-sync-get-dataset-items", token, "POST", params, timeout=320)
    print("Pulling the last successful run of task %s" % task)
    params["status"] = "SUCCEEDED"
    return apify(task_path + "/runs/last/dataset/items", token, params=params)


def list_tasks(token):
    tasks = apify("/actor-tasks", token, params={"limit": 100}).get("data", {}).get("items", [])
    print("\nTasks (use the ID or username~name as APIFY_TASK_ID):")
    for t in tasks:
        print("  %-20s %s~%s" % (t.get("id"), t.get("username", "?"), t.get("name")))
    if not tasks:
        print("  none. Create a task for the actor in Apify first.")
    runs = apify("/actor-runs", token, params={"limit": 10, "desc": 1}).get("data", {}).get("items", [])
    print("\nRecent runs (these are NOT task IDs):")
    for r in runs:
        print("  %-20s %-10s %s" % (r.get("id"), r.get("status"), r.get("startedAt")))


# ---------- history ----------

def parse_time(value):
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def load_json(path, default):
    p = pathlib.Path(path)
    if p.is_dir():
        sys.exit("%s is a folder, but a file is expected there." % p)
    if not p.exists():
        return default
    text = p.read_text(encoding="utf-8").strip()
    return json.loads(text) if text else default


def ensure_dir(path):
    p = pathlib.Path(path)
    if p.exists() and not p.is_dir():
        sys.exit("A file called '%s' is in the way of the %s folder. Delete or rename it." % (p, p.name))
    p.mkdir(parents=True, exist_ok=True)


def merge(history, items):
    added = held = skipped = 0
    petitions = history.setdefault("petitions", {})
    for r in items:
        if not isinstance(r, dict) or r.get("status", "ok") != "ok":
            skipped += 1
            continue
        key = r.get("actionGuid") or r.get("url")
        count, when = r.get("signatureCount"), r.get("collectedAt")
        try:
            ts = parse_time(when)
            count = int(count)
        except (TypeError, ValueError):
            skipped += 1
            continue
        if not key:
            skipped += 1
            continue
        p = petitions.setdefault(key, {"meta": {}, "snapshots": []})
        if any(abs((parse_time(s["collectedAt"]) - ts).total_seconds()) < 60 for s in p["snapshots"]):
            held += 1
            continue
        p["snapshots"].append({"collectedAt": when, "signatureCount": count})
        p["snapshots"].sort(key=lambda s: parse_time(s["collectedAt"]))
        if not p["meta"] or ts >= parse_time(p["meta"]["collectedAt"]):
            p["meta"] = {k: r.get(k) for k in META_KEYS if r.get(k) is not None}
            p["meta"]["collectedAt"] = when
        added += 1
    return added, held, skipped


# ---------- site ----------

def write_site(history, events_path, site_dir, out_dir):
    ensure_dir(out_dir)
    out = pathlib.Path(out_dir)
    shutil.copyfile(pathlib.Path(site_dir) / "index.html", out / "index.html")

    records = []
    rows = []
    for key, p in history.get("petitions", {}).items():
        meta = {k: v for k, v in p["meta"].items() if k not in ("collectedAt", "petitionHtml")}
        snaps = p["snapshots"]
        for i, s in enumerate(snaps):
            rec = dict(meta, status="ok", collectedAt=s["collectedAt"], signatureCount=s["signatureCount"])
            if i == len(snaps) - 1 and p["meta"].get("petitionHtml"):
                rec["petitionHtml"] = p["meta"]["petitionHtml"]
            records.append(rec)
            prev = snaps[i - 1] if i else None
            change = s["signatureCount"] - prev["signatureCount"] if prev else ""
            rows.append([meta.get("title", key), s["collectedAt"], s["signatureCount"], change])

    (out / "data.json").write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")

    events = load_json(events_path, [])
    if not isinstance(events, list):
        sys.exit("%s should be a list of events, like [{\"time\": ..., \"label\": ...}]" % events_path)
    for i, e in enumerate(events):
        try:
            parse_time(e["time"])
            assert str(e["label"]).strip()
        except Exception:
            sys.exit("Event %s in %s needs a valid \"time\" and a \"label\": %r" % (i + 1, events_path, e))
    (out / "events.json").write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")

    with open(out / "history.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["petition", "scraped_at_utc", "signatures", "change_since_last_scrape"])
        w.writerows(rows)

    return len(records), len(events)


def report(history, added):
    now = datetime.now(timezone.utc)
    lines = []
    for p in history.get("petitions", {}).values():
        snaps = p["snapshots"]
        last = snaps[-1]
        age = (now - parse_time(last["collectedAt"])).total_seconds() / 3600
        title = p["meta"].get("title", "Petition").replace("Sign the petition: ", "")
        line = "%s: %s signatures, scraped %.1f hours ago" % (title, format(last["signatureCount"], ","), age)
        if len(snaps) > 1:
            line += " (%+d since the previous scrape)" % (last["signatureCount"] - snaps[-2]["signatureCount"])
        print(line)
        lines.append("- " + line)
        if age > STALE_HOURS:
            print("::warning::%s hasn't had a new scrape for %.0f hours. Check the Apify schedule." % (title, age))
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("### Petition tracker\n\n%s new snapshot(s) this run.\n\n%s\n" % (added, "\n".join(lines)))


# ---------- main ----------

def main():
    ap = argparse.ArgumentParser(description="Pull petition scrapes from Apify and build the tracker site.")
    ap.add_argument("--task", help="Apify task ID or username~task-name")
    ap.add_argument("--mode", default="latest", choices=["latest", "run"],
                    help="latest: pull the last successful scheduled run. run: start the task and wait.")
    ap.add_argument("--file", help="build from a local export instead of calling Apify")
    ap.add_argument("--list-tasks", action="store_true", help="print the account's tasks and recent runs")
    ap.add_argument("--history", default="data/history.json")
    ap.add_argument("--events", default="data/events.json")
    ap.add_argument("--site", default="site")
    ap.add_argument("--out", default="out")
    a = ap.parse_args()

    token = os.environ.get("APIFY_TOKEN", "").strip()
    if a.list_tasks:
        if not token:
            sys.exit("Set APIFY_TOKEN first.")
        list_tasks(token)
        return

    if a.file:
        items = json.loads(pathlib.Path(a.file).read_text(encoding="utf-8"))
    else:
        if not a.task:
            sys.exit("No task given. Set the APIFY_TASK_ID variable in the repo, or pass --task.")
        if not token:
            sys.exit("No Apify token. Add APIFY_TOKEN as a repository secret.")
        items = pull(a.task, token, a.mode)
    if isinstance(items, dict):
        items = items.get("items", [items])
    print("Pulled %s record(s)" % len(items))

    ensure_dir(pathlib.Path(a.history).parent)
    history = load_json(a.history, {"petitions": {}})
    added, held, skipped = merge(history, items)
    print("History: %s new, %s already held, %s skipped" % (added, held, skipped))
    if not history.get("petitions"):
        sys.exit("No valid petition records yet, so there's nothing to publish. Check the actor's output.")
    if items and added == 0 and held == 0:
        print("::warning::Apify returned records but none were usable. Check the actor's status field.")

    pathlib.Path(a.history).write_text(json.dumps(history, ensure_ascii=False, indent=1), encoding="utf-8")
    n_records, n_events = write_site(history, a.events, a.site, a.out)
    print("Site: %s snapshot(s), %s shared event(s) written to %s/" % (n_records, n_events, a.out))
    report(history, added)


if __name__ == "__main__":
    main()
