"""Branch governance: scan, classify and (optionally) clean up remote branches.

Read-only by default. --cleanup deletes remote branches that are provably fully
contained in main (GitHub compare status 'behind' or 'identical'), have no open
pull request and have not been touched for --min-age days. Branches that are
ahead or diverged are always reported, never deleted or merged automatically.
"""
import argparse
import datetime as dt
import json
import os
import requests

OWNER_REPO = os.getenv('GITHUB_REPOSITORY', 'yuchen0x1/VoxMaster-AI')
PROTECTED = {'main', 'master', 'develop'}


def api(route, method='GET'):
    headers = {'Accept': 'application/vnd.github+json'}
    token = os.getenv('GH_TOKEN') or os.getenv('GITHUB_TOKEN')
    if token:
        headers['Authorization'] = 'Bearer ' + token
    try:
        result = requests.request(method, f'https://api.github.com/{route}',
                                  headers=headers, timeout=(8, 30))
        if result.status_code >= 400:
            return {'error': 'HTTP ' + str(result.status_code), 'body': result.text[:200]}
        if result.status_code == 204:
            return {}
        return result.json()
    except requests.RequestException as exc:
        return {'error': type(exc).__name__}


def classify(compare):
    """GitHub compare status -> governance class."""
    status = compare.get('status')
    if status in ('identical', 'behind'):
        return 'D', 'fully contained in main; no unique commits'
    if status == 'ahead':
        return 'B', 'has unmerged commits; review for merge or close'
    return 'C', 'diverged from main; needs conflict resolution by a human'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=str, default='branch-report.md')
    parser.add_argument('--cleanup', action='store_true',
                        help='delete remote branches classified D with no open PR')
    parser.add_argument('--min-age-days', type=int, default=7,
                        help='grace period before an auto-cleanup may touch a branch')
    args = parser.parse_args()
    now = dt.datetime.now(dt.timezone.utc)
    branches = api(f'repos/{OWNER_REPO}/branches?per_page=100')
    if isinstance(branches, dict):
        raise SystemExit('branch list failed: ' + str(branches))
    pulls = api(f'repos/{OWNER_REPO}/pulls?state=open&per_page=100')
    open_heads = {p['head']['ref'] for p in pulls} if isinstance(pulls, list) else set()

    rows, deleted = [], []
    for item in branches:
        name = item['name']
        if name in PROTECTED:
            continue
        commit_date = api(f"repos/{OWNER_REPO}/commits/{item['commit']['sha']}")
        committed = (commit_date.get('commit', {}).get('committer', {}).get('date'))
        age_days = ((now - dt.datetime.fromisoformat(committed.replace('Z', '+00:00'))).days
                    if committed else -1)
        compare = api(f'repos/{OWNER_REPO}/compare/main...{name}')
        if 'error' in compare:
            klass, note, status = '?', 'compare failed: ' + str(compare['error']), 'unknown'
        else:
            klass, note = classify(compare)
            status = compare.get('status')
        has_pr = name in open_heads
        deleted_flag = False
        if (args.cleanup and klass == 'D' and not has_pr and not name.startswith('dependabot/')
                and age_days >= args.min_age_days):
            result = api(f'repos/{OWNER_REPO}/git/refs/heads/{name}', 'DELETE')
            deleted_flag = 'error' not in result
            if deleted_flag:
                deleted.append(name)
        rows.append(dict(branch=name, status=status, klass=klass, age_days=age_days,
                         open_pr=has_pr, deleted=deleted_flag, note=note))

    lines = ['# 分支治理报告', '', f'观察时间：{now.isoformat()}  远程分支数：{len(branches)}（含 main）', '',
             '| 分支 | 与 main 关系 | 分类 | 最后提交天数 | 开放 PR | 处理 |',
             '|---|---|---|---|---|---|']
    for r in rows:
        action = '已自动清理（无独立提交）' if r['deleted'] else ('含 PR，等待人工' if r['open_pr'] else r['note'])
        lines.append(f"| {r['branch']} | {r['status']} | {r['klass']} | {r['age_days']} | "
                     f"{'是' if r['open_pr'] else '否'} | {action} |")
    lines += ['', '规则：D 类（完全包含于 main、无开放 PR、超过宽限期）才自动清理；'
              'ahead/diverged 与含开放 PR 的分支只报告，绝不自动删除或合并。']
    report = '\n'.join(lines)
    with open(args.output, 'w', encoding='utf-8') as f:
        f.write(report)
    with open('branch-report.json', 'w', encoding='utf-8') as f:
        json.dump({'observed_at': now.isoformat(), 'rows': rows}, f, ensure_ascii=False, indent=2)
    print(report)
    if deleted:
        print('DELETED:', ', '.join(deleted))


if __name__ == '__main__':
    main()
