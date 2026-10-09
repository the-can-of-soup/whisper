"""
Command-line interface.
"""



# IMPORTS

from __future__ import annotations

from typing import SupportsInt, SupportsFloat, Never, BinaryIO, Any
from collections.abc import Sequence, Callable
import websockets.exceptions
import subprocess
import argparse
import tempfile
import asyncio
import getpass
import math
import glob
import time
import sys
import ssl
import os

from . import common
from . import core



# GLOBALS

_open_files: list[BinaryIO] = []



# DEFINITIONS


def int_within(
        min: int | None,
        max: int | None,
        exc_type: type[Exception] = argparse.ArgumentTypeError,
    ) -> Callable[[str | SupportsInt], int]:
    """
    Return a callable that converts a value into an integer and raises ``exc_type`` if
    it is outside the specified range.

    :param min: Minimum accepted value (inclusive), or ``None`` for unbounded.
    :type min: int | None
    :param max: Maximum accepted value (inclusive), or ``None`` for unbounded.
    :type max: int | None
    :param exc_type: Exception type for the callable to raise for out-of-bounds values.
    :type exc_type: type[Exception]
    :return: Callable that converts a value into a bounded integer or raises the
        appropriate exception.
    :rtype: Callable[[str | SupportsInt], int]
    """

    def bounded_int(value: str | SupportsInt) -> int:
        value: int = int(value)

        if (min is not None and value < min) or (max is not None and value > max):
            interval_min: str = '(∞' if min is None else f'[{min}'
            interval_max: str = '∞)' if max is None else f'{max}]'
            interval: str = f'{interval_min}, {interval_max}'
            raise exc_type(f'Value {value} is outside the accepted range {interval}')

        return value

    return bounded_int


def float_within(
        min: float | None,
        max: float | None,
        exc_type: type[Exception] = argparse.ArgumentTypeError,
    ) -> Callable[[str | SupportsFloat], float]:
    """
    Return a callable that converts a value into a floating-point number and raises
    ``exc_type`` if it is outside the specified range (or if it is infinite or ``nan``).

    :param min: Minimum accepted value (inclusive, must be finite), or ``None`` for
        unbounded.
    :type min: float | None
    :param max: Maximum accepted value (inclusive, must be finite), or ``None`` for
        unbounded.
    :type max: float | None
    :param exc_type: Exception type for the callable to raise for out-of-bounds values.
    :type exc_type: type[Exception]
    :return: Callable that converts a value into a bounded float or raises the
        appropriate exception.
    :rtype: Callable[[str | SupportsFloat], float]
    """

    def bounded_float(value: str | SupportsFloat) -> float:
        value: float = float(value)

        if math.isinf(value):
            raise exc_type(f'Expected finite value, got {value}')
        if math.isnan(value):
            raise exc_type(f'NaN is not allowed here')

        if (min is not None and value < min) or (max is not None and value > max):
            interval_min: str = '(∞' if min is None else f'[{float(min)}'
            interval_max: str = '∞)' if max is None else f'{float(max)}]'
            interval: str = f'{interval_min}, {interval_max}'
            raise exc_type(f'Value {value} is outside the accepted range {interval}')

        return value

    return bounded_float


def data_size(argument: str) -> int:
    """
    Parse ``argument`` as a data size in bytes.

    ``argument`` is case-insensitive, and is either a nonnegative integer of the value
    in bytes with an optional ``B`` suffix, or a nonnegative finite floating-point
    number with one of these suffixes:
        - ``k`` or ``kiB``: Value in kibibytes.
        - ``kB``: Value in kilobytes.
        - ``M`` or ``MiB``: Value in mebibytes.
        - ``MB``: Value in megabytes.
        - ``G`` or ``GiB``: Value in gibibytes.
        - ``GB``: Value in gigabytes.
        - ``T`` or ``TiB``: Value in tebibytes.
        - ``TB``: Value in terabytes.

    Fractional sizes are rounded.

    :param argument: Command-line data size argument value.
    :type argument: str
    :return: Data size in bytes.
    :rtype: int
    :raise argparse.ArgumentTypeError: If ``argument`` could not be parsed or is
        invalid.
    """

    units_lower: dict[str, float] = {
        'k': 1_024,
        'kib': 1_024,
        'kb': 1_000,

        'm': 1_024 ** 2,
        'mib': 1_024 ** 2,
        'mb': 1_000 ** 2,

        'g': 1_024 ** 3,
        'gib': 1_024 ** 3,
        'gb': 1_000 ** 3,

        't': 1_024 ** 4,
        'tib': 1_024 ** 4,
        'tb': 1_000 ** 4,
    }

    argument_lower: str = argument.lower()

    # Handle values in a unit other than bytes
    for unit_suffix, unit_value in units_lower.items():
        if not argument_lower.endswith(unit_suffix):
            continue

        # Parse and validate value in the specified unit
        value_in_unit_unparsed: str = argument_lower.removesuffix(unit_suffix)
        try:
            value_in_unit: float = float(value_in_unit_unparsed)
        except ValueError:
            raise argparse.ArgumentTypeError(f'Invalid float {value_in_unit_unparsed!r}'
                + f' in data size {argument!r}') from None
        if value_in_unit < 0 or math.isinf(value_in_unit) or math.isnan(value_in_unit):
            raise argparse.ArgumentTypeError('Expected finite nonnegative value, got'
                + f' {value_in_unit!r} in data size {argument!r}')

        # Convert to bytes
        value: float = value_in_unit * unit_value
        value: int = round(value)
        return value

    # Handle values in bytes
    value_in_unit_unparsed: str = argument_lower.removesuffix('b')
    try:
        value: int = int(value_in_unit_unparsed)
    except ValueError:
        raise argparse.ArgumentTypeError(f'Invalid int {value_in_unit_unparsed!r} in'
            + f' data size {argument!r}') from None
    if value < 0:
        raise argparse.ArgumentTypeError(f'Expected nonnegative value, got {value!r} in'
            + f' data size {argument!r}')
    return value


def or_special[T, U, V](
        handler: Callable[[T], U],
        *special: V,
    ) -> Callable[[T], U | V]:
    """
    Return a callable that returns its single input unchanged if it is a member of
    ``special``, otherwise passes it to ``handler``.

    :param handler: Handler that the returned callable calls if its input is not a
        member of ``special``.
    :type handler: Callable[T, U]
    :param special: Special values that pass through the returned callable without
        calling ``handler``.
    :type special: V
    :return: Wrapped handler.
    :rtype: Callable[T, U | V]
    """

    def wrapped_handler(input: T) -> U | V:
        if input in special:
            return input
        return handler(input)

    return wrapped_handler


def error(
        parser: argparse.ArgumentParser,
        msg_or_exc: str | Exception,
        status: int = 1,
    ) -> Never:
    """
    Print an error message or exception to stderr and exit.

    :param parser: Command argument parser.
    :type parser: argparse.ArgumentParser
    :param msg_or_exc: Message or exception to print.
    :type msg_or_exc: str | Exception
    :param status: Exit status.
    :type status: int
    :rtype: Never
    """

    message: str
    if isinstance(msg_or_exc, Exception):
        message = common.format_exc(msg_or_exc)
    else:
        message = msg_or_exc

    sys.stderr.write(f'{parser.prog}: error: {message}\n')
    parser.exit(status)


def _open_binary_file_read(filename: str) -> BinaryIO:
    """
    Open a file in binary reading mode from a command-line argument. If ``-``, stdin is
    used.

    :param filename: Command-line argument.
    :type filename: str
    :return: Binary stream.
    :rtype: BinaryIO
    :raise argparse.ArgumentTypeError: If the file cannot be opened.
    """
    global _open_files

    if filename == '-':
        return sys.stdin.buffer

    file: BinaryIO = open(filename, 'rb')
    _open_files.append(file)
    return file


def _open_binary_file_write(filename: str) -> BinaryIO:
    """
    Open a file in binary writing mode from a command-line argument. If ``-``, stdout is
    is used.

    :param filename: Command-line argument.
    :type filename: str
    :return: Binary stream.
    :rtype: BinaryIO
    :raise OSError: If the file cannot be opened.
    """
    global _open_files

    if filename == '-':
        return sys.stdout.buffer

    file: BinaryIO = open(filename, 'wb')
    _open_files.append(file)
    return file


def _clean_up() -> None:
    global _open_files

    for file in _open_files:
        file.close()


def _finally_cleanup[T, U](func: Callable[T, U]) -> Callable[T, U]:
    def func_with_cleanup(*args, **kwargs) -> U:
        try:
            return func(*args, **kwargs)
        finally:
            _clean_up()

    return func_with_cleanup


@_finally_cleanup
def whisper(args: Sequence[str] | None = None) -> Never:
    """
    Run the ``whisper`` command-line with the given arguments.

    :param args: Command-line arguments, or ``None`` to pull from ``sys.argv``.
    :type args: Sequence[str] | None
    """


    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        prog='whisper',
        description=common.DESCRIPTION,
        add_help=False,
    )


    io_args = parser.add_argument_group(title='i/o options')
    io_args_ex = io_args.add_mutually_exclusive_group(required=False)
    io_args_ex.add_argument('send_from', nargs='?',
        type=_open_binary_file_read, default=sys.stdin.buffer,
        help='File to stream to the peer. If `-` or omitted, stdin is used.'
            + ' Incompatible with `-r`.')
    io_args_ex.add_argument('-r', '--recv-to',
        type=_open_binary_file_write,
        help='File to write the received stream to. If `-`, stdout is used and `-q` is'
            + ' implied. Incompatible with `send-from`.')

    mode_options = parser.add_argument_group(title='mode options',
        description='One of these options must be specified.')
    mode_options_ex = mode_options.add_mutually_exclusive_group(required=True)
    mode_options_ex.add_argument('-s', '--serve', action='store_true',
        help='Host the ephemeral server (opposite of `-c`). Use `-p` to specify the'
            + ' port number used.')
    mode_options_ex.add_argument('-c', '--connect-to',
        metavar='REMOTE_URI',
        help='Connect to the server at `REMOTE_URI`.')
    mode_options_ex.add_argument('-h', '--help', action='store_true',
        help='Print this help and exit.')
    # TODO: Add `-v`/`--version` option that prints common.VERSION and exits

    server_options = parser.add_argument_group(title='server options',
        description='These options only have an effect if `-s` is specified.')
    server_options.add_argument('-i', '--interfaces',
        type=lambda arg:
            '*' if arg == '*' else arg.removesuffix(',').split(','),
        default='*',
        help='Interface(s) to host the server on separated by commas. If `*`, all'
            + ' interfaces are used. Trailing comma is permitted. Default: `*`')
    server_options.add_argument('-p', '--port',
        type=int_within(0, 65_535), default=8_409,
        help='Port number to host the server on. Default: `8409`')
    server_options.add_argument('-t', '--timeout',
        type=or_special(float_within(0.0, None), 'none'),
        default=600.0,
        help='Maximum time to wait for a connection in seconds, or `none` for no limit.'
            + ' Default: `600.0`')

    send_options = parser.add_argument_group(title='send options',
        description='These options do not have an effect if `-r` is specified.')
    send_options.add_argument('-S', '--send-frame-size',
        type=lambda arg: int_within(1, None)(data_size(arg)),
        default=data_size('32K'),
        help='Maximum size of individual frames (chunks) sent to the peer. Default:'
            + ' `32K`')

    recv_options = parser.add_argument_group(title='receive options',
        description='These options only have an effect if `-r` is specified.')
    recv_options.add_argument('-m', '--max-size',
        type=or_special(data_size, 'none'), default=data_size('128M'),
        help='Maximum accepted total size of received data, or `none` for no limit.'
            + ' Default: `128M`')
    recv_options.add_argument('-M', '--max-frame-size', type=data_size,
        default=data_size('128K'),
        help='Maximum accepted size of individual received frames (chunks).'
            + ' Default: `128K`')

    tls_options = parser.add_argument_group(title='TLS options')
    tls_options.add_argument('-C', '--certfile',
        type=lambda arg: glob.glob(arg, recursive=True),
        help='Trusted certificate file(s). Globbing is supported (and directories are'
            ' excluded). Default: `~/.whisper/certs/*` (where `~` is user home)')
    tls_options.add_argument('-k', '--keyfile',
        default=common.DEFAULT_KEY_PATH,
        help='Key file for ourselves. If it does not have an embedded certificate'
            + ' chain, `-K` must be specified as well. Default:'
            + ' `~/.whisper/keys/primary.key` (where `~` is user home)')
    tls_options.add_argument('-K', '--key-certfile',
        default=common.DEFAULT_KEY_CERT_PATH,
        help='Corresponding certificate chain for our keyfile. Ignored if the keyfile'
            + ' has an embedded cert chain; may be omitted in that case. Default:'
            + ' `~/.whisper/certs/primary.crt`')
    tls_options.add_argument('--insecure', '--unsecure',
        action='store_true',
        help='Disable TLS. Only use this if you know what you\'re doing.')

    general_options = parser.add_argument_group(title='general options')
    general_options.add_argument('-q', '--quiet', action='store_true',
        help='Do not print progress information to stdout.')

    parser.add_argument_group(title='data size arguments',
        description='Data size arguments are case-insensitive and accept either the'
            + ' form `<int>`, `<int>B`, or `<float><unit>`; the first two forms specify'
            + ' the size in bytes, and the last form specifies the size in some other'
            + ' unit. The units `k`, `M`, `G`, and `T`, or their aliases `kiB`, `MiB`,'
            + ' `GiB`, and `TiB`, refer to the IEC units kibibytes, mebibytes,'
            + ' gibibytes, and tebibytes respectively. `kB`, `MB`, `GB`, and `TB`'
            + ' represent their respective SI units kilobytes, megabytes, gigabytes,'
            + ' and terabytes. If the conversion from this unit to bytes returns a'
            + ' fractional value, it is rounded to the nearest integer.')

    parser.add_argument_group(title='exit status',
        description='0: Operation completed successfully; 1: Unexpected error; 2:'
            + ' Argument parsing failure; 3: File I/O error; 4: Bad URI; 5: Initial'
            + ' connection failure; 6: Serving failure; 7: Timeout while waiting for'
            + ' connection; 8: Connection broken; 9: Failure loading TLS certs/key; 10:'
            + ' Other TLS error.')


    try:
        parsed_args: argparse.Namespace = parser.parse_args(args)
    except OSError as exc:
        error(parser, exc, 3)


    if parsed_args.help:
        parser.print_help()
        parser.exit(0)


    # Configure

    common.ensure_dirs()

    whisperer: core.Whisperer
    is_sender: bool = parsed_args.recv_to is None

    trusted_certfiles: list[str] | None = (
        None
            if parsed_args.unsecure
        else glob.glob(common.DEFAULT_CERTS_PATTERN, recursive=True)
            if parsed_args.certfile is None
        else parsed_args.certfile
    )
    if isinstance(trusted_certfiles, list):
        trusted_certfiles = [
            path for path in trusted_certfiles
                if not os.path.isdir(path)
        ]

    kwargs: dict[str, Any] = {
        'max_recv_size': 0 if is_sender
            else (None if parsed_args.max_size == 'none' else parsed_args.max_size),
        'max_recv_frame_size': 0 if is_sender else parsed_args.max_frame_size,
        'max_send_frame_size': parsed_args.send_frame_size,
        'trusted_certfiles': trusted_certfiles,
        'keyfile': parsed_args.keyfile,
        'key_certfile': parsed_args.key_certfile,
    }

    try:
        if parsed_args.serve:
            whisperer = core.Server(
                parsed_args.interfaces,
                parsed_args.port,
                timeout=None if parsed_args.timeout == 'none' else parsed_args.timeout,
                **kwargs,
            )
        else:
            whisperer = core.Client(
                parsed_args.connect_to,
                **kwargs,
            )
    except (ssl.SSLError, OSError, UnicodeDecodeError) as exc:
        error(parser, exc, 9)


    # Stream data

    async def perform_stream() -> None:
        nonlocal parsed_args
        nonlocal whisperer
        nonlocal is_sender

        # TODO: Print progress to stdout unless `-q` or `-r -` is given
        if is_sender:
            await whisperer.connect_and_send_stream(parsed_args.send_from)
        else:
            async for frame in whisperer.connect_and_recv_stream():
                parsed_args.recv_to.write(frame)

    try:
        asyncio.run(perform_stream())
    except websockets.exceptions.InvalidURI:
        error(parser, 'Invalid WebSocket URI', 4)
    except core.WaitForConnectionTimeout:
        error(parser, 'Client did not connect within timeout period',
            7)
    except (core.TCPHandshakeFailed, websockets.exceptions.InvalidHandshake,
            TimeoutError) as exc:
        error(parser, exc, 5)
    except websockets.exceptions.ConnectionClosed as exc:
        error(parser, exc, 8)
    except ssl.SSLError as exc:
        error(parser, exc, 10)


    parser.exit(0)


def whisper_certs(args: Sequence[str] | None = None) -> Never:
    """
    Run the ``whisper-certs`` command-line with the given arguments.

    :param args: Command-line arguments, or ``None`` to pull from ``sys.argv``.
    :type args: Sequence[str] | None
    """


    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        prog='whisper-certs',
        description='Simple tool for creating and managing `whisper` certificates.',
        add_help=False,
    )
    parser.set_defaults(subcommand=None)
    parsers = parser.add_subparsers(title='subcommands')

    parser.add_argument('-h', '--help', action='store_true',
        help='Print general help or help on the selected subcommand.')


    create_subcmd_description: str = ('Wrapper around openssl to create a self-signed'
        + ' certificate. Requires the `openssl` command.')
    create_parser = parsers.add_parser(
        'create',
        help=create_subcmd_description,
        description=create_subcmd_description,
        prefix_chars='-+',
        add_help=False,
    )
    create_parser.set_defaults(subcommand='create')

    create_out_dest_options = create_parser.add_argument_group(title='output location'
        + ' options',
        description='If none of these options are specified, a default `--name` is'
            + ' used.')
    create_out_dest_options.add_argument('key_out', nargs='?',
        help='Write the private key to this file in PEM format. If `cert-out` is'
            + ' omitted, will also embed the certificate.')
    create_out_dest_options.add_argument('cert_out', nargs='?',
        help='Write the certificate to this file in PEM format.')
    create_out_dest_options.add_argument('-n', '--name',
        help='Create the key and certificate files with this name (plus a file'
            + ' extension) in the default directories. Create only the keyfile if the'
            + ' certfile is embedded. Incompatible with `key-out` and `cert-out`.')

    create_out_options = create_parser.add_argument_group(title='output options')
    create_out_options.add_argument('-e', '--embed', action='store_const',
        dest='force_embed', const=True,
        help='Embed the certificate into the keyfile.')
    create_out_options.add_argument('+e', '--no-embed',
        action='store_const', dest='force_embed', const=False,
        help='Do not embed the certificate into the keyfile.')

    cert_options = create_parser.add_argument_group(title='certificate options')
    cert_options.add_argument('-o', '--owner',
        help='Issuer/issuee name to put on the certificate. Default: current effective'
            + ' username')
    cert_options.add_argument('-E', '--expire-in', metavar='DAYS',
        type=int_within(1, None), default=365,
        help='Days until the certificate expires. Default: `365`')

    general_options = create_parser.add_argument_group(title='general options')
    general_options.add_argument('-h', '--help', action='store_true',
        help='Print this help and exit.')


    list_subcmd_description: str = ('List certificates or keyfiles in the default'
        + ' directories.')
    list_parser = parsers.add_parser(
        'list',
        help=list_subcmd_description,
        description=list_subcmd_description,
        epilog='Calling with no arguments implies `-c`.',
        add_help=False,
    )
    list_parser.set_defaults(subcommand='list')

    list_parser.add_argument('-c', '--certfiles', action='store_true',
        help='List default trusted certificates.')
    list_parser.add_argument('-k', '--keyfiles', action='store_true',
        help='List keyfiles.')
    list_parser.add_argument('-h', '--help', action='store_true',
        help='Print this help and exit.')


    parsed_args = parser.parse_args(args)


    if parsed_args.help:
        match parsed_args.subcommand:
            case 'create':
                create_parser.print_help()
            case 'list':
                list_parser.print_help()

            case _:
                parser.print_help()

        parser.exit(0)


    common.ensure_dirs()

    match parsed_args.subcommand:
        case 'create':
            if parsed_args.name is not None and (parsed_args.key_out is not None
                    or parsed_args.cert_out is not None):
                error(parser, 'argument -n/--name: not allowed with arguments key-out,'
                    + ' cert-out', 2)

            # Determine output paths

            keyfile: str | None = parsed_args.key_out
            certfile: str | None = parsed_args.cert_out

            if parsed_args.name is not None:
                if os.path.dirname(parsed_args.name) != '':
                    error(parser, 'argument -n/--name: Invalid filename'
                        + f' {parsed_args.name!r}', 2)

                name: str = parsed_args.name
                if parsed_args.force_embed is True:
                    keyfile = os.path.join(common.KEYS_PATH, f'{name}.pem')
                else:
                    keyfile = os.path.join(common.KEYS_PATH, f'{name}.key')
                    certfile = os.path.join(common.CERTS_PATH, f'{name}.crt')

            if keyfile is None:
                name: str = time.strftime('%Y-%m-%d_%H-%M-%S')
                if parsed_args.force_embed is True:
                    keyfile = os.path.join(common.KEYS_PATH, f'{name}.pem')
                else:
                    keyfile = os.path.join(common.KEYS_PATH, f'{name}.key')
                    certfile = os.path.join(common.CERTS_PATH, f'{name}.crt')
            keyfile: str

            embed: bool = (certfile is None
                if parsed_args.force_embed is None
                else parsed_args.force_embed)

            # Determine owner name
            owner: str = (getpass.getuser() if parsed_args.owner is None
                else parsed_args.owner)

            # Create private key

            # noinspection SpellCheckingInspection
            exit_status: int = subprocess.call([
                'openssl', 'genpkey',
                '-algorithm', 'RSA',
                '-outform', 'PEM',
                '-out', keyfile,
            ])
            if exit_status != 0:
                parser.exit(exit_status)

            print(f'Keyfile written to: {common.path_rel_to_home_if_inside(keyfile)}')

            # Create certificate

            create_cert_cmd_without_out: list[str] = [
                'openssl', 'x509',
                '-new',
                '-key', keyfile,
                '-days', str(parsed_args.expire_in),
                '-subj', f'/CN={owner
                    .replace('/', '\\/')
                    .replace('=', '\\=')
                    .replace('+', '\\+')}',
                '-outform', 'PEM',
            ]

            if certfile is not None:
                exit_status = subprocess.call(create_cert_cmd_without_out + [
                    '-out', certfile,
                ])
                if exit_status != 0:
                    parser.exit(exit_status)

                print(f'Certificate issued to {owner!r} written to:'
                    + f' {common.path_rel_to_home_if_inside(certfile)}')

            if embed:
                with tempfile.NamedTemporaryFile('r') as temp_certfile_stream:
                    # Write certificate to a temporary file
                    exit_status = subprocess.call(create_cert_cmd_without_out + [
                        '-out', temp_certfile_stream.name,
                    ])
                    if exit_status != 0:
                        parser.exit(exit_status)

                    # Read certificate contents
                    cert: str = temp_certfile_stream.read()

                # Read private key contents
                with open(keyfile, 'r') as keyfile_stream:
                    key: str = keyfile_stream.read()

                # Combine and write to keyfile
                combined: str = key.removesuffix('\n') + '\n' + cert
                with open(keyfile, 'w') as keyfile_stream:
                    keyfile_stream.write(combined)

                print(f'Certificate issued to {owner!r} embedded into keyfile.')

            parser.exit(0)


        case 'list':
            neither: bool = not (parsed_args.certfiles or parsed_args.keyfiles)
            # if neither:
            #     error(parser, '-c/--certfiles and/or -k/--keyfiles must be'
            #         + ' specified', 2)

            if parsed_args.certfiles or neither:
                print('Default trusted certificates:')

                empty: bool = True
                for path in sorted(
                        glob.glob(common.DEFAULT_CERTS_PATTERN, recursive=True)
                    ):
                    if os.path.isdir(path):
                        continue
                    print(f'  {common.path_rel_to_home_if_inside(path)}')
                    empty = False
                if empty:
                    print('  [none]')

                print('')

            if parsed_args.keyfiles:
                print('Private keys:')

                empty: bool = True
                for filename in sorted(os.listdir(common.KEYS_PATH)):
                    path: str = os.path.join(common.KEYS_PATH, filename)
                    if os.path.isdir(path):
                        continue
                    print(f'  {common.path_rel_to_home_if_inside(path)}')
                    empty = False
                if empty:
                    print('  [none]')

                print('')

            parser.exit(0)


        case _:
            parser.print_usage()
            error(parser, 'Missing subcommand; use -h/--help for help',
                2)



# MAIN

if __name__ == '__main__':
    whisper(sys.argv[1:])



# EXPORTS

__all__ = [
    'int_within',
    'float_within',
    'data_size',
    'or_special',
    'error',

    'whisper',
    'whisper_certs',
]
