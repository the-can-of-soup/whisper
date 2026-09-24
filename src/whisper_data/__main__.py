"""
Command-line interface.
"""



# IMPORTS

from __future__ import annotations

import sys

from .cli import *



# MAIN

cli(sys.argv[1:])
