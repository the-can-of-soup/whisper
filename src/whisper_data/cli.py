"""
Command-line interface.
"""



# IMPORTS

from __future__ import annotations

from collections.abc import Sequence
import sys



# DEFINITIONS

def whisper(args: Sequence[str]) -> None:
    raise NotImplementedError # TODO



# MAIN

if __name__ == '__main__':
    whisper(sys.argv[1:])



# EXPORTS

__all__ = [
    'whisper',
]
