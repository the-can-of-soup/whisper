"""
Common definitions.
"""



# IMPORTS

import traceback
import stat
import os



# CONSTANTS

DESCRIPTION: str = ('Transfer data through a secure one-way stream over WebSocket with'
    + ' one peer hosting an ephemeral server.') # Update __init__.py docstring too!
VERSION: str = 'alpha-1.0'

CERTS_PATH: str = os.path.expanduser('~/.whisper/certs')
KEYS_PATH: str = os.path.expanduser('~/.whisper/keys')

DEFAULT_CERTS_PATTERN: str = os.path.join(CERTS_PATH, '*') # Update `-C` option help too
DEFAULT_KEY_PATH: str = os.path.join(KEYS_PATH, 'primary') # Update `-k` option help too
DEFAULT_KEY_CERT_PATH: str = os.path.join(KEYS_PATH, 'primary-cert') # Update `-K` option help too



# DEFINITIONS


def ensure_dirs() -> None:
    """
    Ensure the program directories exist.
    """

    os.makedirs(CERTS_PATH, exist_ok=True)

    if not os.path.isdir(KEYS_PATH):
        os.makedirs(KEYS_PATH)
        os.chmod(KEYS_PATH, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR) # TODO: Windows support


def format_exc(exc: Exception) -> str:
    """
    Format an exception to be printed on one line.

    :param exc: Exception to format.
    :type exc: Exception
    :return: Formatted exception.
    :rtype: str
    """

    return traceback.format_exception_only(exc)[0].strip()



# EXPORTS

__all__ = [
    'DESCRIPTION',
    'VERSION',

    'CERTS_PATH',
    'KEYS_PATH',

    'DEFAULT_CERTS_PATTERN',
    'DEFAULT_KEY_PATH',
    'DEFAULT_KEY_CERT_PATH',

    'ensure_dirs',
    'format_exc',
]
