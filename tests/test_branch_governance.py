from scripts import branch_governance


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
