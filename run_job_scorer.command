#!/bin/bash
# Double-click runner for the job scorer (macOS).
# Resolves its own directory so this works regardless of where the project is installed.
set -e
cd "$(dirname "$0")"
exec ./.venv/bin/python scripts/run_scorer.py
