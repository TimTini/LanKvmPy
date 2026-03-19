from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SessionMode(str, Enum):
    IDLE = "idle"
    CONTROLLING_PEER = "controlling_peer"
    CONTROLLED_BY_PEER = "controlled_by_peer"


@dataclass
class SessionState:
    mode: SessionMode = SessionMode.IDLE
    peer_machine_id: str | None = None
    last_local_handoff_norm: float = 0.5
    last_remote_exit_norm: float = 0.5

    def can_start_local_capture(self) -> bool:
        return self.mode == SessionMode.IDLE

    def can_accept_remote_capture(self) -> bool:
        return self.mode == SessionMode.IDLE

    def begin_local_capture(self, peer_machine_id: str | None, normalized: float) -> None:
        if self.mode != SessionMode.IDLE:
            raise RuntimeError(f"cannot begin local capture while in mode {self.mode}")
        self.mode = SessionMode.CONTROLLING_PEER
        self.peer_machine_id = peer_machine_id
        self.last_local_handoff_norm = normalized

    def accept_remote_capture(self, peer_machine_id: str | None) -> None:
        if self.mode != SessionMode.IDLE:
            raise RuntimeError(f"cannot accept remote capture while in mode {self.mode}")
        self.mode = SessionMode.CONTROLLED_BY_PEER
        self.peer_machine_id = peer_machine_id

    def release_local_capture(self) -> None:
        if self.mode == SessionMode.CONTROLLING_PEER:
            self.mode = SessionMode.IDLE

    def release_remote_capture(self, normalized: float) -> None:
        if self.mode == SessionMode.CONTROLLED_BY_PEER:
            self.last_remote_exit_norm = normalized
            self.mode = SessionMode.IDLE

    def disconnect(self) -> SessionMode:
        previous = self.mode
        self.mode = SessionMode.IDLE
        return previous
