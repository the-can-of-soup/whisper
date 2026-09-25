"""
Command-line interface.
"""



# IMPORTS

from __future__ import annotations

import math
from collections.abc import Sequence, Callable
from typing import SupportsInt, Never
import argparse
import sys



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
                + f' {value_in_unit!r}')

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
        raise argparse.ArgumentTypeError(f'Expected nonnegative value, got {value!r}')
    return value


def whisper(args: Sequence[str]) -> Never:
    """
    Run the ``whisper`` command-line interface with the given arguments.

    :param args: Command-line arguments.
    :type args: Sequence[str]
    """

    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        prog='whisper',
        description='Transfer data through a secure stream over WebSocket with one peer'
            + ' hosting an ephemeral server.',
        add_help=False,
        exit_on_error=True,
    )


    # TODO: replace deprecated FileType
    io_args_group = parser.add_mutually_exclusive_group(required=False)
    io_args_group.add_argument('SEND_FROM', nargs='?',
        type=argparse.FileType('rb'),
        help='File to stream to the peer. If `-` or omitted, stdin is used. If `-r` is'
            + ' specified, the stream is received instead.')
    io_args_group.add_argument('-r', '--recv-to',
        type=argparse.FileType('wb'),
        help='File to write the received stream to. If `-`, stdout is used and `-q` is'
            + ' implied.')

    role_args_group = parser.add_mutually_exclusive_group(required=True)
    role_args_group.add_argument('-s', '--serve', action='store_true',
        help='Host the ephemeral server (opposite of `-c`). Use `-p` to specify the'
            + ' port number used.')
    role_args_group.add_argument('-c', '--connect-to',
        metavar='SERVER_ADDR',
        help='Connect to the server at `SERVER_ADDR`.')

    parser.add_argument('-p', '--port',
        type=int_within(0, 65535), default=8409,
        help='Port number of the server. Default: `8409`')
    parser.add_argument('-m', '--max-size', type=data_size,
        default=data_size('100M'),
        help='Maximum received bytes; see \'data size arguments\' for format. Default:'
            + ' `100M`')
    parser.add_argument('-q', '--quiet', action='store_true',
        help='Do not print progress information to stdout.')

    # Added to role_args_group to prevent requirement of a role_args_group argument if
    # `-h`/`--help` is used.
    role_args_group.add_argument('-h', '--help', action='store_true',
        help='Print this help and exit.')

    parser.add_argument_group(title='data size arguments',
        description='Data size arguments are case-insensitive and accept either the'
            + ' form `<int>`, `<int>B`, or `<float><unit>`; the first two forms specify'
            + ' the size in bytes, and the last form specifies the size in some other'
            + ' unit. If the conversion from this unit to bytes returns a fractional'
            + ' value, it is rounded to the nearest integer. The units `k`, `M`, `G`,'
            + ' and `T`, or their aliases `kiB`, `MiB`, `GiB`, and `TiB`, refer to the'
            + ' IEC units kibibytes, mebibytes, gibibytes, and tebibytes respectively.'
            + ' `kB`, `MB`, `GB`, and `TB` represent their respective SI units'
            + ' kilobytes, megabytes, gigabytes, and terabytes.')

    parser.add_argument_group(title='exit status',
        description='0: Operation completed successfully; 1: Miscellaneous error; 2:'
            + ' Argument parsing failure; 3: Connection failure; 4: Serving failure; 5:'
            + ' `MAX_SIZE` exceeded.')


    parsed_args: argparse.Namespace = parser.parse_args(args)

    if parsed_args.help:
        parser.print_help()
        parser.exit()


    raise NotImplementedError # TODO



# MAIN

if __name__ == '__main__':
    whisper(sys.argv[1:])



# EXPORTS

__all__ = [
    'int_within',
    'data_size',

    'whisper',
]
