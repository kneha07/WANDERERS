#!/bin/sh
# One-click boot for WANDERERS and the live explorer (macOS: double-click). Needs Node.js and Python 3.11+.
cd "$(dirname "$0")" && node start.js "$@"
