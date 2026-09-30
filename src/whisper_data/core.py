"""
Backend definitions.
"""

# TODO: Prevent likely hang or undefined behavior when both peers attempt to
#   send/receive



# IMPORTS

from __future__ import annotations

from collections.abc import Sequence, Iterator, AsyncIterator
import websockets.asyncio.server
import websockets.asyncio.client
from typing import Literal, Any
from abc import abstractmethod
from io import BufferedReader
import websockets
import asyncio
import abc
import ssl

from . import common



# DEFINITIONS


type WebsocketConnection = (websockets.asyncio.server.ServerConnection
    | websockets.asyncio.client.ClientConnection)


class WaitForConnectionTimeout(TimeoutError):
    """
    Timeout expired while waiting for a connection.
    """

class TCPHandshakeFailed(OSError):
    """
    TCP handshake failed.
    """


class Whisperer(abc.ABC):
    """
    Abstract base class for a peer.
    """


    def __init__(self,
            *,
            max_recv_size: int | None = 128 * 1024 ** 2,
            max_recv_frame_size: int = 128 * 1024,
            max_send_frame_size: int = 32 * 1024,
            trusted_certfiles: Sequence[str] | None = None,
            keyfile: str = common.DEFAULT_KEY_PATH,
            key_certfile: str | None = None,
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
        :param trusted_certfiles: Sequence of paths to trusted certificate files, or
            ``None`` to disable TLS.
        :type trusted_certfiles: Sequence[str] | None
        :param keyfile: Path to our keyfile for TLS.
        :type keyfile: str
        :param key_certfile: Path to our certificate file for TLS. Ignored if
            ``keyfile`` contains an embedded certificate, and may be ``None`` in that
            case.
        :type key_certfile: str | None
        :raise ssl.SSLError: If the provided key or certificates are invalid.
        :raise OSError: If a file could not be read.
        :raise UnicodeDecodeError: If a file could not be decoded to Unicode.
        """

        # Options
        self._max_recv_size: int | None = max_recv_size
        self._max_recv_frame_size: int = max_recv_frame_size
        self._max_send_frame_size: int = max_send_frame_size
        self._trusted_certfiles: Sequence[str] | None = trusted_certfiles
        self._keyfile: str = keyfile
        self._key_certfile: str | None = key_certfile

        self._tls: ssl.SSLContext | None = None

        # State
        self._conn: WebsocketConnection | None = None

        # Configure TLS if enabled
        self._configure_tls()


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


    @property
    def tls(self) -> ssl.SSLContext | None:
        """
        TLS context, or ``None`` if TLS is disabled.

        :rtype: ssl.SSLContext | None
        """
        return self._tls


    @staticmethod
    @abstractmethod
    def _create_bare_tls_context() -> ssl.SSLContext:
        """
        Return a new unconfigured TLS context with the correct protocol for our role.

        :rtype: ssl.SSLContext
        """


    def _configure_tls(self) -> None:
        """
        :raise ssl.SSLError: If the provided key or certificates are invalid.
        :raise OSError: If a file could not be read.
        :raise UnicodeDecodeError: If a file could not be decoded to Unicode.
        """

        # Do nothing if TLS is disabled
        if self._trusted_certfiles is None:
            return

        # Create context
        self._tls = self._create_bare_tls_context()
        assert self._tls is not None

        # Set TLS options
        self._tls.check_hostname = False # TODO: Decide about this
        self._tls.verify_mode = ssl.CERT_REQUIRED

        # Load trusted certificates

        trusted_certs: str = ''
        for path in self._trusted_certfiles:
            with open(path, 'r') as f:
                cert: str = f.read()

            trusted_certs += cert.removesuffix('\n') + '\n'

        self._tls.load_verify_locations(cadata=trusted_certs)

        # Load own key and certificate chain
        try:
            self._tls.load_cert_chain(self._keyfile)
        except ssl.SSLError:
            if self._key_certfile is None:
                raise
            try:
                self._tls.load_cert_chain(self._key_certfile, self._keyfile)
            except ssl.SSLError as exc:
                raise exc from None


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
        :raise websockets.exceptions.InvalidURI: If the provided URI is invalid.
        :raise WaitForConnectionTimeout: If the timeout set by ``self.timeout`` expires.
            Note that this exception type is also a subclass of ``TimeoutError``.
        :raise TCPHandshakeFailed: If the TCP handshake fails.
        :raise websockets.exceptions.InvalidHandshake: If the WebSocket handshake fails.
        :raise TimeoutError: If the WebSocket handshake times out.
        :raise ssl.SSLError: If the TLS connection fails.
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
        raised by ``self.connect`` or ``self.prepare_for_connecion`` for the same
        reasons.

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
        raised by ``self.connect`` or ``self.prepare_for_connecion`` for the same
        reasons.

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
            **kwargs: Any,
        ) -> None:
        """
        Initialize ``self``. See ``Whisperer.__init__`` for exceptions.

        :param interfaces: Network interfaces to host the server on, or ``'*'`` to host
            on all interfaces.
        :type interfaces: Sequence[str] | Literal['*']
        :param port: Port number to host the server on.
        :type port: int
        :param timeout: Maximum time to wait for a connection in seconds, or ``None``
            for no limit.
        :type timeout: float | None
        :param kwargs: Additional arguments passed to ``Whisperer.__init__``.
        :type kwargs: Any
        """
        super().__init__(**kwargs)

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


    @staticmethod
    def _create_bare_tls_context() -> ssl.SSLContext:
        return ssl.SSLContext(protocol=ssl.PROTOCOL_TLS_SERVER)


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
            host=None if self.interfaces == '*' else self.interfaces,
            port=self.port,
            max_size=(self.max_recv_size, self.max_recv_frame_size),
            compression='deflate', # TODO: Maybe set `compression` to `None`
            ssl=self.tls,
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
            **kwargs: Any,
        ) -> None:
        """
        Initialize ``self``. See ``Whisperer.__init__`` for exceptions.

        :param remote_uri: URI of the remote server.
        :type remote_uri: str
        :param kwargs: Additional arguments passed to ``Whisperer.__init__``.
        :type kwargs: Any
        """
        super().__init__(**kwargs)

        # Options
        self._remote_uri: str = remote_uri


    @property
    def remote_uri(self) -> str:
        """
        URI of the remote server.

        :rtype: str
        """
        return self._remote_uri


    @staticmethod
    def _create_bare_tls_context() -> ssl.SSLContext:
        return ssl.SSLContext(protocol=ssl.PROTOCOL_TLS_CLIENT)


    async def prepare_for_connection(self) -> None:
        pass


    async def connect(self) -> WebsocketConnection:
        try:
            self._conn = await websockets.asyncio.client.connect(
                self.remote_uri,
                compression='deflate', # TODO: Maybe set `compression` to `None`
                max_size=(self._max_recv_size, self._max_recv_frame_size),
            )

        except OSError as exc:
            if isinstance(exc, ssl.SSLError):
                raise

            raise TCPHandshakeFailed(common.format_exc(exc)) from None

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
    'TCPHandshakeFailed',

    'Whisperer',
    'Server',
    'Client',
]
