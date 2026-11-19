import subprocess

from scripts import branch_governance


def _git(cwd, *args):
    return subprocess.run(
        ['git', *args], cwd=cwd, check=True, capture_output=True, text=True,
    ).stdout.strip()


def test_paginate_reads_all_full_pages(monkeypatch):
    first = [{'name': str(i)} for i in range(100)]
    second = [{'name': 'last'}]
    calls = []

    def fake_api(route, method='GET'):
        calls.append(route)
        return first if route.endswith('page=1') else second

    monkeypatch.setattr(branch_governance, 'api', fake_api)
    rows = branch_governance.paginate('repos/example/project/branches')

    assert len(rows) == 101
    assert calls == [
        'repos/example/project/branches?per_page=100&page=1',
        'repos/example/project/branches?per_page=100&page=2',
    ]


def test_branch_pr_guard_fails_closed(monkeypatch):
    monkeypatch.setattr(branch_governance, 'api', lambda *args, **kwargs: {'error': 'HTTP 403'})
    assert branch_governance.branch_has_open_pr('feature/audio') is True


def test_branch_pr_guard_accepts_empty_list(monkeypatch):
    monkeypatch.setattr(branch_governance, 'api', lambda *args, **kwargs: [])
    assert branch_governance.branch_has_open_pr('feature/audio') is False


def _make_repo(tmp_path):
    bare = tmp_path / 'remote.git'
    work = tmp_path / 'work'
    _git(tmp_path, 'init', '--bare', str(bare))
    work.mkdir()
    _git(work, 'init')
    _git(work, 'config', 'user.email', 'audit@example.invalid')
    _git(work, 'config', 'user.name', 'audit')
    (work / 'file.txt').write_text('one', encoding='utf-8')
    _git(work, 'add', 'file.txt')
    _git(work, 'commit', '-m', 'initial')
    _git(work, 'branch', '-M', 'main')
    _git(work, 'push', str(bare), 'main')
    _git(work, 'switch', '-c', 'feature/race')
    _git(work, 'push', '-u', str(bare), 'feature/race')
    old_sha = _git(work, 'rev-parse', 'HEAD')
    return bare, work, old_sha


def test_delete_branch_matching_lease_removes_only_expected_tip(tmp_path):
    bare, work, old_sha = _make_repo(tmp_path)

    result = branch_governance.delete_branch(
        'feature/race', old_sha, remote=str(bare), cwd=work,
    )

    assert result == {}
    gone = subprocess.run(
        ['git', 'show-ref', '--verify', '--quiet', 'refs/heads/feature/race'],
        cwd=bare,
    )
    assert gone.returncode != 0


def test_delete_branch_stale_lease_preserves_new_tip(tmp_path):
    bare, work, old_sha = _make_repo(tmp_path)
    (work / 'file.txt').write_text('new', encoding='utf-8')
    _git(work, 'add', 'file.txt')
    _git(work, 'commit', '-m', 'new work')
    _git(work, 'push', str(bare), 'HEAD:refs/heads/feature/race')
    new_sha = _git(work, 'rev-parse', 'HEAD')

    result = branch_governance.delete_branch(
        'feature/race', old_sha, remote=str(bare), cwd=work,
    )

    assert result.get('error') == 'lease-protected git push failed'
    assert _git(bare, 'rev-parse', 'refs/heads/feature/race') == new_sha


def test_cleanup_compares_and_deletes_the_listed_branch_sha(monkeypatch, tmp_path):
    branch_sha = 'a' * 40
    routes = []
    deleted = []
    old = '2020-01-01T00:00:00Z'

    def fake_api(route, method='GET'):
        routes.append((route, method))
        if route.startswith('repos/example/project/branches?'):
            return [{'name': 'feature/old', 'commit': {'sha': branch_sha}}]
        if route.startswith('repos/example/project/pulls?state=open'):
            return []
        if route == f'repos/example/project/commits/{branch_sha}':
            return {'commit': {'committer': {'date': old}}}
        if route == f'repos/example/project/compare/main...{branch_sha}':
            return {'status': 'behind'}
        if route.startswith('repos/example/project/pulls?state=open&head='):
            return []
        raise AssertionError(f'unexpected API route: {route}')

    monkeypatch.setattr(branch_governance, 'OWNER_REPO', 'example/project')
    monkeypatch.setattr(branch_governance, 'api', fake_api)
    monkeypatch.setattr(
        branch_governance,
        'delete_branch',
        lambda name, expected_sha: deleted.append((name, expected_sha)) or {},
    )
    monkeypatch.setattr('sys.argv', [
        'branch_governance.py', '--cleanup', '--min-age-days', '7',
        '--output', str(tmp_path / 'report.md'),
    ])
    monkeypatch.chdir(tmp_path)

    branch_governance.main()

    assert deleted == [('feature/old', branch_sha)]
    assert (f'repos/example/project/compare/main...{branch_sha}', 'GET') in routes
    assert not any('compare/main...feature/old' in route for route, _ in routes)


def test_cleanup_retains_age_pr_and_protected_branch_guards(monkeypatch, tmp_path):
    names = [
        'main', 'master', 'develop', 'dependabot/example', 'fresh',
        'existing-pr', 'new-pr', 'pr-api-failed', 'ahead', 'diverged', 'eligible',
    ]
    tips = {name: f'{index + 1:040x}' for index, name in enumerate(names)}
    by_sha = {sha: name for name, sha in tips.items()}
    deleted, rechecked, compared = [], [], []
    now = branch_governance.dt.datetime.now(branch_governance.dt.timezone.utc)

    def fake_api(route, method='GET'):
        assert method == 'GET'
        if '/commits/' in route:
            name = by_sha[route.rsplit('/', 1)[1]]
            date = now if name == 'fresh' else now - branch_governance.dt.timedelta(days=30)
            return {'commit': {'committer': {'date': date.isoformat()}}}
        if '/compare/' in route:
            name = by_sha[route.rsplit('...', 1)[1]]
            compared.append(name)
            return {'status': name if name in ('ahead', 'diverged') else 'behind'}
        if '/pulls?' in route:
            name = route.split('&head=', 1)[1].split(':', 1)[1].split('&', 1)[0]
            rechecked.append(name)
            if name == 'pr-api-failed':
                return {'error': 'HTTP 403'}
            return [{'number': 1}] if name == 'new-pr' else []
        raise AssertionError(route)

    monkeypatch.setattr(branch_governance, 'paginate', lambda route: (
        [{'name': name, 'commit': {'sha': sha}} for name, sha in tips.items()]
        if route.endswith('/branches') else [{'head': {'ref': 'existing-pr'}}]
    ))
    monkeypatch.setattr(branch_governance, 'api', fake_api)
    monkeypatch.setattr(branch_governance, 'delete_branch',
                        lambda name, sha: deleted.append((name, sha)) or {})
    monkeypatch.setattr('sys.argv', ['branch_governance.py', '--cleanup'])
    monkeypatch.chdir(tmp_path)

    branch_governance.main()

    assert deleted == [('eligible', tips['eligible'])]
    assert not set(compared) & {'main', 'master', 'develop'}
    assert set(rechecked) == {'new-pr', 'pr-api-failed', 'eligible'}


def test_github_delete_uses_scoped_ephemeral_auth_and_explicit_lease(monkeypatch):
    from types import SimpleNamespace

    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0)

    monkeypatch.setenv('GH_TOKEN', 'test-token-not-a-real-credential')
    monkeypatch.setattr(branch_governance, 'OWNER_REPO', 'example/project')
    monkeypatch.setattr(branch_governance.subprocess, 'run', run)
    sha = 'a' * 40

    assert branch_governance.delete_branch('feature/audio', sha) == {}

    command, kwargs = calls[0]
    assert command == [
        'git', 'push', f'--force-with-lease=refs/heads/feature/audio:{sha}',
        'https://github.com/example/project.git', ':refs/heads/feature/audio',
    ]
    env = kwargs['env']
    assert env['GIT_TERMINAL_PROMPT'] == '0'
    assert env['GIT_CONFIG_COUNT'] == '2'
    assert env['GIT_CONFIG_KEY_0'] == env['GIT_CONFIG_KEY_1'] == 'http.https://github.com/.extraheader'
    assert env['GIT_CONFIG_VALUE_0'] == ''
    assert env['GIT_CONFIG_VALUE_1'].startswith('AUTHORIZATION: basic ')
    assert not any('test-token' in arg for arg in command)
