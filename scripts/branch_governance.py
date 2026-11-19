"""Branch governance: scan, classify and (optionally) clean up remote branches.

Read-only by default. --cleanup deletes only the exact branch tip that was
classified as fully contained in main (GitHub compare status 'behind' or
'identical'), has no open pull request and has not been touched for --min-age
days. The remote ref deletion uses an expected-SHA lease, so a branch that moves
after classification is preserved. Branches that are ahead or diverged are
always reported, never deleted or merged automatically.
"""
import argparse
import base64
import datetime as dt
import json
import os
import re
import subprocess
import requests

OWNER_REPO = os.getenv('GITHUB_REPOSITORY', 'yuchen0x1/VoxMaster-AI')
PROTECTED = {'main', 'master', 'develop'}
_SHA_RE = re.compile(r'(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})')


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


def paginate(route):
    """Return every page from a GitHub list endpoint.

    GitHub defaults to 30 entries and caps a page at 100.  Governance must not
    silently miss a branch or an open PR before making a destructive decision.
    """
    page = 1
    rows = []
    while True:
        separator = '&' if '?' in route else '?'
        payload = api(f'{route}{separator}per_page=100&page={page}')
        if isinstance(payload, dict):
            raise SystemExit(f'list failed ({route}): {payload}')
        if not isinstance(payload, list):
            raise SystemExit(f'list failed ({route}): unexpected response')
        rows.extend(payload)
        if len(payload) < 100:
            return rows
        page += 1


def branch_has_open_pr(name):
    """Re-check a candidate immediately before deletion to avoid a race."""
    owner = OWNER_REPO.split('/', 1)[0]
    result = api(f'repos/{OWNER_REPO}/pulls?state=open&head={owner}:{name}&per_page=100')
    return bool(result) if isinstance(result, list) else True


def delete_branch(name, expected_sha, *, remote=None, cwd=None):
    """Delete only the branch tip that was classified and approved for cleanup.

    GitHub's REST delete-ref endpoint has no expected-old-SHA precondition. A
    Git push with an explicit force-with-lease does: if the branch moves after
    classification (or the PR check), the server rejects the stale deletion.
    """
    if not isinstance(expected_sha, str) or not _SHA_RE.fullmatch(expected_sha):
        return {'error': 'invalid expected branch SHA'}

    token = os.getenv('GH_TOKEN') or os.getenv('GITHUB_TOKEN')
    destination = remote or f'https://github.com/{OWNER_REPO}.git'
    env = os.environ.copy()
    env['GIT_TERMINAL_PROMPT'] = '0'
    if remote is None:
        if not token:
            return {'error': 'missing GitHub token; lease-protected deletion skipped'}
        # Pass credentials through the child environment instead of argv or
        # persistent git configuration. Actions/checkout and local callers use
        # the same short-lived token exposed to the governance step.
        credential = base64.b64encode(f'x-access-token:{token}'.encode()).decode('ascii')
        header_key = 'http.https://github.com/.extraheader'
        env.update(
            GIT_CONFIG_COUNT='2',
            GIT_CONFIG_KEY_0=header_key,
            GIT_CONFIG_VALUE_0='',  # Reset checkout's inherited auth header.
            GIT_CONFIG_KEY_1=header_key,
            GIT_CONFIG_VALUE_1='AUTHORIZATION: basic ' + credential,
        )

    ref = 'refs/heads/' + name
    command = [
        'git', 'push', f'--force-with-lease={ref}:{expected_sha}',
        destination, ':' + ref,
    ]
    try:
        result = subprocess.run(
            command, cwd=cwd, env=env, text=True, capture_output=True, timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {'error': type(exc).__name__}
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        return {'error': 'lease-protected git push failed', 'body': detail[-300:]}
    return {}


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
    branches = paginate(f'repos/{OWNER_REPO}/branches')
    pulls = paginate(f'repos/{OWNER_REPO}/pulls?state=open')
    open_heads = {p['head']['ref'] for p in pulls}

    rows, deleted = [], []
    for item in branches:
        name = item['name']
        branch_sha = item.get('commit', {}).get('sha')
        if name in PROTECTED:
            continue
        if not isinstance(branch_sha, str) or not _SHA_RE.fullmatch(branch_sha):
            branch_sha = None
        commit_date = api(f"repos/{OWNER_REPO}/commits/{branch_sha}") if branch_sha else {}
        committed = (commit_date.get('commit', {}).get('committer', {}).get('date')
                     if isinstance(commit_date, dict) else None)
        age_days = ((now - dt.datetime.fromisoformat(committed.replace('Z', '+00:00'))).days
                    if committed else -1)
        # Classify the exact tip observed in the branch listing, not a branch
        # name that may already have moved by the time compare is requested.
        if branch_sha:
            compare = api(f'repos/{OWNER_REPO}/compare/main...{branch_sha}')
        else:
            compare = {'error': 'missing branch tip SHA'}
        if not isinstance(compare, dict) or 'error' in compare:
            error = (
                compare.get('error', 'unexpected response')
                if isinstance(compare, dict)
                else 'unexpected response'
            )
            klass, note, status = '?', 'compare failed: ' + str(error), 'unknown'
        else:
            klass, note = classify(compare)
            status = compare.get('status')
        has_pr = name in open_heads
        deleted_flag = False
        cleanup_note = None
        if (args.cleanup and klass == 'D' and branch_sha and not has_pr
                and not name.startswith('dependabot/') and age_days >= args.min_age_days):
            # Keep the PR recheck and make deletion conditional on the precise
            # SHA already measured above. A newly pushed tip loses the lease.
            has_pr = branch_has_open_pr(name)
        if (args.cleanup and klass == 'D' and branch_sha and not has_pr
                and not name.startswith('dependabot/') and age_days >= args.min_age_days):
            result = delete_branch(name, branch_sha)
            deleted_flag = 'error' not in result
            if deleted_flag:
                deleted.append(name)
            else:
                cleanup_note = '清理未执行（SHA 租约不匹配或远程推送失败）'
        if cleanup_note:
            note = cleanup_note
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
