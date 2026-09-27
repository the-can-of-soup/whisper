"""
Backend definitions.
"""



# IMPORTS

from __future__ import annotations

from collections.abc import Sequence, Iterator, AsyncIterator
import websockets.asyncio.server
import websockets.asyncio.client
from abc import abstractmethod
from io import BufferedReader
import websockets.exceptions
from typing import Literal
import websockets
import asyncio
import abc



# DEFINITIONS


type WebsocketConnection = (websockets.asyncio.server.ServerConnection
    | websockets.asyncio.client.ClientConnection)


class WaitForConnectionTimeout(RuntimeError):
    """
    Timeout expired while waiting for a connection.
    """


class Whisperer(abc.ABC):
    """
    Abstract base class for one peer.
    """


    def __init__(self,
            *,
            max_recv_size: int | None = 128 * 1024 ** 2,
            max_recv_frame_size: int = 128 * 1024,
            max_send_frame_size: int = 32 * 1024,
        ) -> None:
        """
        :param max_recv_size: Maximum accepted size of received data, or ``None`` for no
            limit. Should be zero if we are sending a stream rather than receiving one.
        :type max_recv_size: int | None
        :param max_recv_frame_size: Maximum accepted size of individual received frames.
            Should be zero if we are sending a stream rather than receiving one.
        :type max_recv_frame_size: int
        :param max_send_frame_size: Maximum size of the individual frames sent to the
            peer. Has no effect if we are receiving a stream rather than sending one.
        :type max_send_frame_size: int
        """

        # Options
        self._max_recv_size: int | None = max_recv_size
        self._max_recv_frame_size: int = max_recv_frame_size
        self._max_send_frame_size: int = max_send_frame_size

        # State
        self._conn: WebsocketConnection | None = None


    @property
    def max_recv_size(self) -> int | None:
        """
        Maximum accepted size of received data, or ``None`` for no limit. Should be zero
        if we are sending a stream rather than receiving one.

        :rtype: int | None
        """
        return self._max_recv_size


    @property
    def max_recv_frame_size(self) -> int:
        """
        Maximum accepted size of individual received frames. Should be zero if we are
        sending a stream rather than receiving one.

        :rtype: int
        """
        return self._max_recv_frame_size


    @property
    def max_send_frame_size(self) -> int:
        """
        Maximum size of the individual frames sent to the peer. Has no effect if we are
        receiving a stream rather than sending one.

        :rtype: int
        """
        return self._max_send_frame_size


    @property
    def conn(self) -> WebsocketConnection | None:
        """
        Current connection, or ``None`` if disconnected.

        :rtype: WebsocketConnection | None
        """
        return self._conn


    @abstractmethod
    async def prepare_for_connection(self) -> None:
        """
        Perform all necessary setup before attempting to connect.
        """


    @abstractmethod
    async def connect(self) -> WebsocketConnection:
        """
        Wait for a connection, update ``self.conn``, and return it.

        :return: The new WebSocket connection.
        :rtype: WebsocketConnection
        :raise WaitForConnectionTimeout: If the timeout set by ``self.timeout`` expires.
        :raise websockets.exceptions.InvalidURI: If the provided URI is invalid.
        :raise OSError: If the TCP handshake fails.
        :raise websockets.exceptions.InvalidHandshake: If the WebSocket handshake fails.
        :raise TimeoutError: If the WebSocket handshake times out.
        """


    @abstractmethod
    async def close(self) -> None:
        """
        Idempotently close the existing connection if there is one, and undo setup. Also
        set ``self.conn`` to ``None``.
        """


    async def send_stream(
            self,
            stream: BufferedReader,
        ) -> None:
        """
        Send a stream to the peer.

        :param stream: Binary stream, e.g. a file opened in ``rb`` mode.
        :type stream: BufferedReader
        :raise websockets.exceptions.ConnectionClosed: If the connection is closed.
        """

        def frame_iter() -> Iterator[bytes]:
            while True:
                frame: bytes = stream.read(self._max_send_frame_size)
                if len(frame) == 0:
                    return # EOF
                yield frame

        assert self._conn is not None
        await self._conn.send(frame_iter(), text=False)


    def recv_stream(self) -> AsyncIterator[bytes]:
        """
        Receive a stream from the peer.

        :return: Async iterator yielding chunks of bytes.
        :rtype: AsyncIterator[bytes]
        :raise websockets.exceptions.ConnectionClosed: If the connection is closed.
        """

        assert self._conn is not None
        return self._conn.recv_streaming(decode=False)


    async def connect_and_send_stream(
            self,
            stream: BufferedReader,
        ) -> None:
        """
        Perform all necessary setup, wait for a connection, and send a stream to the
        peer before closing the connection.

        In addition to the exceptions listed below, this method may raise any exceptions
        raised by ``self.connect`` for the same reasons.

        :param stream: Binary stream, e.g. a file opened in ``rb`` mode.
        :type stream: BufferedReader
        :raise websockets.exceptions.ConnectionClosed: If the connection is closed.
        """

        await self.prepare_for_connection()
        await self.connect()

        await self.send_stream(stream)
        await self.close()


    async def connect_and_recv_stream(self) -> AsyncIterator[bytes]:
        """
        Perform all necessary setup, wait for a connection, and receive a stream from
        the peer before closing the connection.

        In addition to the exceptions listed below, this method may raise any exceptions
        raised by ``self.connect`` for the same reasons.

        :return: Async iterator yielding chunks of bytes.
        :rtype: AsyncIterator[bytes]
        :raise websockets.exceptions.ConnectionClosed: If the connection is closed.
        """

        await self.prepare_for_connection()
        await self.connect()

        async for frame in self.recv_stream():
            yield frame
        await self.close()


class Server(Whisperer):
    """
    Whisper ephemeral server.
    """


    def __init__(
            self,
            interfaces: Sequence[str] | Literal['*'] = '*',
            port: int = 8409,
            *,
            timeout: float | None = 600.0,
            max_recv_size: int | None = 128 * 1024 ** 2,
            max_recv_frame_size: int = 128 * 1024,
            max_send_frame_size: int = 32 * 1024,
        ) -> None:
        """
        :param interfaces: Network interfaces to host the server on, or ``'*'`` to host
            on all interfaces.
        :type interfaces: Sequence[str] | Literal['*']
        :param port: Port number to host the server on.
        :type port: int
        :param timeout: Maximum time to wait for a connection in seconds, or ``None``
            for no limit.
        :type timeout: float | None
        :param max_recv_size: See ``Whisperer.max_recv_size``.
        :type max_recv_size: int | None
        :param max_recv_frame_size: See ``Whisperer.max_recv_frame_size``.
        :type max_recv_frame_size: int
        :param max_send_frame_size: See ``Whisperer.max_send_frame_size``.
        :type max_send_frame_size: int
        """
        super().__init__(
            max_recv_size=max_recv_size,
            max_recv_frame_size=max_recv_frame_size,
            max_send_frame_size=max_send_frame_size,
        )

        # Options
        self._interfaces: Sequence[str] | Literal['*'] = interfaces
        self._port: int = port
        self._timeout: float | None = timeout

        # State
        self._server: websockets.asyncio.server.Server | None = None
        self._conn_created: asyncio.Event = asyncio.Event()


    @property
    def interfaces(self) -> Sequence[str] | Literal['*']:
        """
        Network interfaces to host the server on, or ``'*'`` to host on all interfaces.

        :rtype: Sequence[str] | Literal['*']
        """
        return self._interfaces


    @property
    def port(self) -> int:
        """
        Port number to host the server on.

        :rtype: int
        """
        return self._port


    @property
    def timeout(self) -> float | None:
        """
        Maximum time to wait for a connection in seconds, or ``None`` for no limit.

        :rtype: float | None
        """
        return self._timeout


    @property
    def server(self) -> websockets.asyncio.server.Server | None:
        """
        Current WebSocket server, or ``None`` if not currently hosting.

        :rtype: websockets.asyncio.server.Server | None
        """
        return self._server


    async def prepare_for_connection(self) -> None:
        # Create and start server

        async def server_handler(conn: websockets.asyncio.server.ServerConnection) -> None:
            if self._conn is not None:
                # A connection already exists; reject this one
                await conn.close(websockets.CloseCode.TRY_AGAIN_LATER)
                return

            self._conn = conn
            self._conn_created.set()

            assert self._conn is not None
            await self._conn.wait_closed()

        # noinspection bad-argument-type
        self._server = await websockets.asyncio.server.serve(
            handler=server_handler,
            host=None if self._interfaces == '*' else self._interfaces,
            port=self._port,
            max_size=(self._max_recv_size, self._max_recv_frame_size),
            compression='deflate', # TODO: Maybe set `compression` to `None`
            start_serving=True,
        )


    async def connect(self) -> WebsocketConnection:
        # Wait for a connection

        try:
            async with asyncio.timeout(self._timeout):
                await self._conn_created.wait()
                assert self._conn is not None
                return self._conn

        except TimeoutError:
            raise WaitForConnectionTimeout from None


    async def close(self) -> None:
        # Close connection
        if self._conn is not None:
            await self._conn.close(websockets.CloseCode.GOING_AWAY)
        self._conn = None
        self._conn_created.clear()

        # Close server
        if self._server is not None:
            self._server.close()
        self._server = None


class Client(Whisperer):
    """
    Whisper client.
    """


    def __init__(self,
            remote_uri: str,
            *,
            max_recv_size: int | None = 128 * 1024 ** 2,
            max_recv_frame_size: int = 128 * 1024,
            max_send_frame_size: int = 32 * 1024,
        ) -> None:
        """
        :param remote_uri: URI of the remote server.
        :type remote_uri: str
        :param max_recv_size: See ``Whisperer.max_recv_size``.
        :type max_recv_size: int | None
        :param max_recv_frame_size: See ``Whisperer.max_recv_frame_size``.
        :type max_recv_frame_size: int
        :param max_send_frame_size: See ``Whisperer.max_send_frame_size``.
        :type max_send_frame_size: int
        """
        super().__init__(
            max_recv_size=max_recv_size,
            max_recv_frame_size=max_recv_frame_size,
            max_send_frame_size=max_send_frame_size,
        )

        # Options
        self._remote_uri: str = remote_uri


    @property
    def remote_uri(self) -> str:
        """
        URI of the remote server.

        :rtype: str
        """
        return self._remote_uri


    async def prepare_for_connection(self) -> None:
        pass


    async def connect(self) -> WebsocketConnection:
        self._conn = await websockets.asyncio.client.connect(
            self._remote_uri,
            compression='deflate', # TODO: Maybe set `compression` to `None`
            max_size=(self._max_recv_size, self._max_recv_frame_size),
        )

        assert self._conn is not None
        return self._conn


    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close(websockets.CloseCode.NORMAL_CLOSURE)
        self._conn = None



# EXPORTS

__all__ = [
    'WebsocketConnection',

    'WaitForConnectionTimeout',

    'Whisperer',
    'Server',
    'Client',
]
