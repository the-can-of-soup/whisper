"""
Command-line interface.
"""



# IMPORTS

from __future__ import annotations

from collections.abc import Sequence
import sys



# DEFINITIONS

def cli(args: Sequence[str]) -> None:
    raise NotImplementedError # TODO



# MAIN

if __name__ == '__main__':
    cli(sys.argv[1:])



# EXPORTS

__all__ = [
    'cli',
]
