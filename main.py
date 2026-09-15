#!/usr/bin/env python3
"""Command-line entry point for the cad2ai DWG -> DeepSeek pipeline.

Kept as a two-act file on purpose: all logic lives in :mod:`cad2ai.cli`, so the
same behaviour is available as the installed ``cad2ai`` console script::

    python main.py analyze drawings/A-101.dwg --task sheet_review --out out/a101
    cad2ai   analyze drawings/A-101.dwg --task sheet_review --out out/a101
"""

from __future__ import annotations

import sys

from cad2ai.cli import main

if __name__ == "__main__":
    sys.exit(main())
