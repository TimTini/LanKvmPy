from __future__ import annotations

from collections.abc import Callable
from queue import Empty, SimpleQueue
import logging
import socket
import threading
import time
from typing import Any

from .protocol import FrameCodec, ProtocolError


FrameHandler = Callable[[dict[str, Any]], None]
SessionHandler = Callable[["TransportSession"], None]
DisconnectHandler = Callable[[str], None]
SessionDisconnectHandler = Callable[["TransportSession", str], None]


class TransportSession:
    def __init__(
        self,
        sock: socket.socket,
        codec: FrameCodec,
        logger: logging.Logger,
        *,
        on_frame: FrameHandler,
        on_disconnect: SessionDisconnectHandler,
    ) -> None:
        self._socket = sock
        self._codec = codec
        self._logger = logger
        self._on_frame = on_frame
        self._on_disconnect = on_disconnect
        self._closed = threading.Event()
        self._disconnect_once = threading.Lock()
        self._send_queue: SimpleQueue[dict[str, Any] | None] = SimpleQueue()
        self._reader_thread = threading.Thread(target=self._reader_loop, name="lan-kvm-reader", daemon=True)
        self._writer_thread = threading.Thread(target=self._writer_loop, name="lan-kvm-writer", daemon=True)
        self._last_received = time.monotonic()
        self._peer_name = _safe_peer_name(sock)

    @property
    def connected(self) -> bool:
        return not self._closed.is_set()

    @property
    def last_received(self) -> float:
        return self._last_received

    @property
    def peer_name(self) -> str:
        return self._peer_name

    def start(self) -> None:
        self._reader_thread.start()
        self._writer_thread.start()

    def send(self, payload: dict[str, Any]) -> bool:
        if self._closed.is_set():
            return False
        self._send_queue.put(payload)
        return True

    def close(self, reason: str = "closed") -> None:
        self._finalize_disconnect(reason)

    def _reader_loop(self) -> None:
        try:
            while not self._closed.is_set():
                chunk = self._socket.recv(65536)
                if not chunk:
                    self._finalize_disconnect("peer closed connection")
                    return
                self._last_received = time.monotonic()
                for frame in self._codec.feed(chunk):
                    self._on_frame(frame)
        except (OSError, ProtocolError) as exc:
            self._finalize_disconnect(f"reader error: {exc}")

    def _writer_loop(self) -> None:
        try:
            while not self._closed.is_set():
                try:
                    payload = self._send_queue.get(timeout=0.2)
                except Empty:
                    continue
                if payload is None:
                    return
                self._socket.sendall(self._codec.encode(payload))
        except OSError as exc:
            self._finalize_disconnect(f"writer error: {exc}")

    def _finalize_disconnect(self, reason: str) -> None:
        with self._disconnect_once:
            if self._closed.is_set():
                return
            self._closed.set()
            try:
                self._send_queue.put_nowait(None)
            except Exception:
                pass
            try:
                self._socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                self._socket.close()
            except OSError:
                pass
            self._logger.info("transport disconnected from %s: %s", self._peer_name, reason)
            self._on_disconnect(self, reason)


class PeerConnector:
    def __init__(
        self,
        *,
        role: str,
        listen_host: str,
        listen_port: int,
        peer_host: str,
        reconnect_ms: int,
        codec_factory: Callable[[], FrameCodec],
        logger: logging.Logger,
        on_frame: FrameHandler,
        on_connected: SessionHandler,
        on_disconnected: DisconnectHandler,
    ) -> None:
        self._role = role
        self._listen_host = listen_host
        self._listen_port = listen_port
        self._peer_host = peer_host
        self._reconnect_seconds = reconnect_ms / 1000.0
        self._codec_factory = codec_factory
        self._logger = logger
        self._on_frame = on_frame
        self._on_connected = on_connected
        self._on_disconnected = on_disconnected
        self._session_lock = threading.Lock()
        self._session: TransportSession | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="lan-kvm-connector", daemon=True)

    @property
    def session(self) -> TransportSession | None:
        with self._session_lock:
            return self._session

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        session = self.session
        if session is not None:
            session.close("connector stopped")
        self._thread.join(timeout=2.0)

    def send(self, payload: dict[str, Any]) -> bool:
        session = self.session
        if session is None:
            return False
        return session.send(payload)

    def _run(self) -> None:
        if self._role == "listener":
            self._run_listener()
        else:
            self._run_dialer()

    def _run_listener(self) -> None:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((self._listen_host, self._listen_port))
        server.listen(1)
        server.settimeout(0.5)
        self._logger.info("listening on %s:%s", self._listen_host, self._listen_port)

        try:
            while not self._stop.is_set():
                try:
                    client, address = server.accept()
                except TimeoutError:
                    continue
                except OSError:
                    if self._stop.is_set():
                        break
                    raise

                self._logger.info("accepted connection from %s:%s", address[0], address[1])
                self._activate_session(client)
        finally:
            try:
                server.close()
            except OSError:
                pass

    def _run_dialer(self) -> None:
        self._logger.info("dialer target is %s:%s", self._peer_host, self._listen_port)
        while not self._stop.is_set():
            if self.session is not None:
                time.sleep(0.2)
                continue
            try:
                sock = socket.create_connection((self._peer_host, self._listen_port), timeout=3.0)
            except OSError as exc:
                self._logger.debug("dialer connect failed: %s", exc)
                time.sleep(self._reconnect_seconds)
                continue

            self._logger.info("connected to %s:%s", self._peer_host, self._listen_port)
            self._activate_session(sock)

    def _activate_session(self, sock: socket.socket) -> None:
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        session = TransportSession(
            sock,
            self._codec_factory(),
            self._logger,
            on_frame=self._on_frame,
            on_disconnect=self._handle_disconnect,
        )

        previous = None
        with self._session_lock:
            previous = self._session
            self._session = session

        if previous is not None:
            previous.close("replaced by new session")

        session.start()
        self._on_connected(session)

    def _handle_disconnect(self, session: TransportSession, reason: str) -> None:
        notify = False
        with self._session_lock:
            if self._session is session:
                self._session = None
                notify = True
        if notify:
            self._on_disconnected(reason)


def _safe_peer_name(sock: socket.socket) -> str:
    try:
        host, port = sock.getpeername()
        return f"{host}:{port}"
    except OSError:
        return "<unknown>"
