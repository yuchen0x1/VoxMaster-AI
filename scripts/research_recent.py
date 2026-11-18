"""Summarise recent upstream activity; read-only GitHub API queries via requests."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import requests

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from research import PROJECTS


def api(route):
    headers = {'Accept': 'application/vnd.github+json'}
    token = os.getenv('GH_TOKEN') or os.getenv('GITHUB_TOKEN')
    if token:
        headers['Authorization'] = 'Bearer ' + token
    try:
        result = requests.get('https://api.github.com/' + route, headers=headers, timeout=(8, 20))
        if result.status_code >= 400:
            return {'error': 'HTTP ' + str(result.status_code)}
        return result.json()
    except requests.RequestException as exc:
        return {'error': type(exc).__name__}


def windows(commit_date, now):
    if not commit_date:
        return {}
    try:
        days = (now - dt.datetime.fromisoformat(commit_date.replace('Z', '+00:00')).astimezone(dt.timezone.utc)).days
    except ValueError:
        return {}
    return {'in_30d': days <= 30, 'in_90d': days <= 90, 'in_180d': days <= 180, 'days_since': days}


def recent_commits(repo, since):
    data = api(f'repos/{repo}/commits?per_page=30&since={since}')
    if isinstance(data, dict):
        return {'error': data.get('error'), 'commits': []}
    return {'commits': [{'sha': c['sha'][:12], 'date': c['commit']['committer']['date'],
                         'subject': c['commit']['message'].splitlines()[0][:120]}
                        for c in data]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--window-days', type=int, default=90)
    args = parser.parse_args()
    now = dt.datetime.now(dt.timezone.utc)
    since = (now - dt.timedelta(days=args.window_days)).isoformat()
    report = {}
    for repo in PROJECTS:
        entry = recent_commits(repo, since)
        last = entry['commits'][0]['date'] if entry['commits'] else None
        entry['last_commit'] = last
        entry['windows'] = windows(last, now)
        report[repo] = entry
    args.output.write_text(json.dumps({'observed_at': now.isoformat(), 'window_days': args.window_days,
                                       'projects': report}, ensure_ascii=False, indent=2), 'utf-8')
    active30 = sum(1 for v in report.values() if v['windows'].get('in_30d'))
    active90 = sum(1 for v in report.values() if v['windows'].get('in_90d'))
    print(f'{len(report)} repos scanned; commits in last {args.window_days}d: '
          f'{sum(len(v["commits"]) for v in report.values())}; active30={active30} active90={active90}')


if __name__ == '__main__':
    main()
