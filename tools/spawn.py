#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""argv0-clean spawn helper (for the agent's sandbox only).

The opencode shell tool rewrites argv[0] of its direct children, which breaks
python venv detection (pyvenv.cfg lookup).  Running anything through this
wrapper gives the child a REAL argv0, so venvs work.
Usage:  python3 tools/spawn.py <cmd> [args...]
"""
import subprocess
import sys

raise SystemExit(subprocess.run(sys.argv[1:]).returncode)
