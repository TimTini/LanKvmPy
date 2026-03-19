from __future__ import annotations

from lankvm.state import SessionMode, SessionState


def test_session_state_transitions_round_trip() -> None:
    state = SessionState()

    state.begin_local_capture("peer-a", 0.4)
    assert state.mode == SessionMode.CONTROLLING_PEER

    state.release_local_capture()
    assert state.mode == SessionMode.IDLE

    state.accept_remote_capture("peer-a")
    assert state.mode == SessionMode.CONTROLLED_BY_PEER

    state.release_remote_capture(0.6)
    assert state.mode == SessionMode.IDLE
    assert state.last_remote_exit_norm == 0.6
