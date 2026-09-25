"""
Command-line interface.
"""



# IMPORTS

from __future__ import annotations

import sys

from .cli import *



# MAIN

whisper(sys.argv[1:])
