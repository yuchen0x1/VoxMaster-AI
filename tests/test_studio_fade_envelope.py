"""Composed fades must multiply automation, not connect only its old endpoints."""
import copy
import json

import numpy as np
import pytest

from vox.studio_session import Session, envelope


@pytest.mark.parametrize('second_in', [True, False])
def test_overlapping_fades_keep_the_product_and_round_trip(second_in):
    source = np.full((1001, 2), .2, np.float32)
    original = source.copy()
    session = Session({'Vocal': source}, 44100)
    session.fade('Vocal', 0, 1001, True)
    before = session.render().copy()
    session.fade('Vocal', 0, 1001, second_in)
    ramp = np.arange(1001) / 1000
    expected = .2 * ramp * (ramp if second_in else 1 - ramp)
    rendered = session.render()
    np.testing.assert_allclose(rendered[:, 0], expected, atol=2.1e-6, rtol=0)
    assert rendered[500, 0] == pytest.approx(.05, abs=2.1e-6)
    assert len(session.strip('Vocal')['clips'][0]['env']) < 600
    assert session.saved_state()['schema'] == 1
    restored = Session({'Vocal': source}, 44100, json.loads(json.dumps(session.saved_state())))
    np.testing.assert_array_equal(restored.render(), rendered)
    session.undo()
    np.testing.assert_array_equal(session.render(), before)
    session.undo(redo=True)
    np.testing.assert_array_equal(session.render(), rendered)
    np.testing.assert_array_equal(source, original)


def test_partial_fade_multiplies_existing_nodes_and_preserves_outside():
    source = np.full((2001, 2), .1, np.float32)
    session = Session({'Vocal': source}, 44100)
    session.point('Vocal', 400, .2)
    session.point('Vocal', 1100, 2.0)
    session.point('Vocal', 1600, .6)
    before = session.render()
    session.fade('Vocal', 250, 1751, False)
    after = session.render()
    expected = before.copy()
    expected[250:1751] *= np.linspace(1, 0, 1501)[:, None]
    np.testing.assert_allclose(after, expected, atol=1.1e-6, rtol=0)
    np.testing.assert_array_equal(after[:250], before[:250])
    np.testing.assert_array_equal(after[1751:], before[1751:])
    assert all(isinstance(x, int) for c in session.strip('Vocal')['clips'] for x, y in c['env'])


def test_long_clip_uses_bounded_nodes_not_one_per_sample():
    # Synthetic out-of-source span tests node growth, not valid long-PCM rendering.
    session = Session({'Vocal': np.zeros((1, 2), np.float32)}, 44100)
    clip = session.strip('Vocal')['clips'][0]
    clip['end'] = 44100 * 3600
    session.fade('Vocal', 0, clip['end'], True)
    session.fade('Vocal', 0, clip['end'], False)
    edited = session.strip('Vocal')['clips'][0]
    positions = np.linspace(0, clip['end'] - 1, 10001).astype(np.int64)
    ratio = positions / (clip['end'] - 1)
    np.testing.assert_allclose(envelope(edited, positions), ratio * (1 - ratio), atol=1e-5, rtol=0)
    assert len(edited['env']) < 600


def test_complexity_limit_leaves_state_and_undo_history_unchanged(monkeypatch):
    from vox import studio_session

    session = Session({'Vocal': np.full((1001, 2), .2, np.float32)}, 44100)
    session.fade('Vocal', 0, 1001, True)
    before = session.saved_state()
    history_size = len(session.undo_stack)
    monkeypatch.setattr(studio_session, 'FADE_EXTRA_NODES', 0)
    with pytest.raises(ValueError, match='包络过于复杂'):
        session.fade('Vocal', 0, 1001, False)
    assert session.saved_state() == before
    assert len(session.undo_stack) == history_size


def test_later_clip_failure_preserves_all_clips_undo_redo_and_source(monkeypatch):
    from vox import studio_session

    source = np.full((2002, 2), .2, np.float32)
    original = source.copy()
    session = Session({'Vocal': source}, 44100)
    session.split('Vocal', 1001)
    clips = session.strip('Vocal')['clips']
    clips[0]['env'] = [[0, 0.0], [1000, .0002]]
    clips[1]['env'] = [[0, 0.0], [1000, 1.0]]
    session.validate()
    session.set_param('Vocal', 'gain', -3)
    session.undo()
    before = session.saved_state()
    undo = copy.deepcopy(session.undo_stack)
    redo = copy.deepcopy(session.redo_stack)
    assert undo and redo
    monkeypatch.setattr(studio_session, 'FADE_EXTRA_NODES', 1)

    first_only = copy.deepcopy(before)
    first_only['tracks']['Vocal']['clips'] = first_only['tracks']['Vocal']['clips'][:1]
    control = Session({'Vocal': source}, 44100, first_only)
    control.fade('Vocal', 0, 2002, False)
    assert len(control.strip('Vocal')['clips'][0]['env']) == 3

    with pytest.raises(ValueError, match='包络过于复杂'):
        session.fade('Vocal', 0, 2002, False)
    assert session.saved_state() == before
    assert session.undo_stack == undo
    assert session.redo_stack == redo
    np.testing.assert_array_equal(source, original)


def test_one_frame_selection_is_a_noop():
    session = Session({'Vocal': np.full((10, 2), .1, np.float32)}, 44100)
    before = session.saved_state()
    session.fade('Vocal', 5, 6, True)
    assert session.saved_state() == before
    assert not session.undo_stack
