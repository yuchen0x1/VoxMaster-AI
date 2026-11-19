from copy import deepcopy
import unittest

import numpy as np

from vox.studio_session import Session
from vox.studio_timeline import clock_text


class MoveTransactionTests(unittest.TestCase):
    rate = 8000

    def make_session(self, frames=4000):
        left = np.arange(frames, dtype=np.float32) * (0.1 / max(1, frames))
        source = np.column_stack((left, -left))
        return Session({"Vocal": source}, self.rate)

    def clips(self, session):
        return session.strip("Vocal")["clips"]

    def test_move_onto_identical_copy_records_one_undo_step(self):
        session = self.make_session()
        session.copy_region("Vocal", 0, 500)
        session.paste("Vocal", 1000)
        after_first_paste = deepcopy(session.state)
        session.paste("Vocal", 2000)
        before_move = deepcopy(session.state)
        history_before_move = len(session.undo_stack)

        session.move("Vocal", 2000, 2500, 1000)
        after_move = deepcopy(session.state)

        self.assertEqual(len(session.undo_stack), history_before_move + 1)
        self.assertEqual(session.undo_stack[-1], before_move)
        session.undo()
        self.assertEqual(session.state, before_move)
        session.undo()
        self.assertEqual(session.state, after_first_paste)
        session.undo(redo=True)
        self.assertEqual(session.state, before_move)
        session.undo(redo=True)
        self.assertEqual(session.state, after_move)

    def test_overlapping_move_is_one_checkpoint_and_has_expected_audio(self):
        session = self.make_session()
        before = deepcopy(session.state)
        history_before = len(session.undo_stack)

        session.move("Vocal", 150, 250, 200)

        self.assertEqual(len(session.undo_stack), history_before + 1)
        rendered = session.render(track="Vocal")
        np.testing.assert_array_equal(rendered[150:200], 0)
        np.testing.assert_array_equal(rendered[200:300], session.sources["Vocal"][150:250])
        np.testing.assert_array_equal(rendered[300:4000], session.sources["Vocal"][300:4000])
        session.undo()
        self.assertEqual(session.state, before)

    def test_move_at_history_limit_drops_only_the_oldest_checkpoint(self):
        session = self.make_session()
        for index in range(80):
            session.set_param("Vocal", "gain", float(index % 12 + 1))
        self.assertEqual(len(session.undo_stack), 80)
        prior_history = deepcopy(session.undo_stack)
        before_move = deepcopy(session.state)

        session.move("Vocal", 0, 100, 1500)

        self.assertEqual(len(session.undo_stack), 80)
        self.assertEqual(session.undo_stack, (prior_history + [before_move])[-80:])
        session.undo()
        self.assertEqual(session.state, before_move)

    def test_no_op_move_does_not_create_history_or_clear_redo(self):
        session = self.make_session()
        session.set_param("Vocal", "gain", 2.0)
        session.undo()
        before = deepcopy(session.state)
        undo_before = deepcopy(session.undo_stack)
        redo_before = deepcopy(session.redo_stack)

        session.move("Vocal", 0, 0, 100)
        session.move("Vocal", 5000, 5100, 6000)  # No clip in this source interval.

        self.assertEqual(session.state, before)
        self.assertEqual(session.undo_stack, undo_before)
        self.assertEqual(session.redo_stack, redo_before)

    def test_invalid_move_preserves_state_and_both_history_stacks(self):
        session = self.make_session()
        session.set_param("Vocal", "gain", 2.0)
        session.undo()
        before = deepcopy(session.state)
        undo_before = deepcopy(session.undo_stack)
        redo_before = deepcopy(session.redo_stack)
        limit = session.sr * 86400

        for args in (("Vocal", 0, 100, -1), ("Vocal", 0, 100, limit),
                     ("Vocal", 100, 0, 200), ("Vocal", True, 100, 200)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                session.move(*args)
            self.assertEqual(session.state, before)
            self.assertEqual(session.undo_stack, undo_before)
            self.assertEqual(session.redo_stack, redo_before)


class ClockTextTests(unittest.TestCase):
    def test_rounds_before_splitting_minutes_and_seconds(self):
        rate = 1000
        self.assertEqual(clock_text(59_994, rate), "00:59.99")
        self.assertEqual(clock_text(59_995, rate), "01:00.00")
        self.assertEqual(clock_text(59_999, rate), "01:00.00")
        self.assertEqual(clock_text(119_996, rate), "02:00.00")

    def test_negative_position_clamps_to_zero(self):
        self.assertEqual(clock_text(-44_100, 44_100), "00:00.00")


if __name__ == "__main__":
    unittest.main()
