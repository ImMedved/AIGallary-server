#!/bin/sh
set -e

git config core.hooksPath .githooks
echo "Git hooks path configured: .githooks"
