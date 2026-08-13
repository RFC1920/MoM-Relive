#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
uid="$(id -u)"
gid="$(id -g)"

# Debian 11 deliberately provides an older glibc baseline than current build
# machines. A release made here remains usable on both older and newer hosts.
docker run --rm \
  -v "$project_dir:/src" \
  -w /src \
  python:3.11-bullseye \
  bash -lc 'python -m pip install --disable-pip-version-check pyinstaller && SKIP_TESTS=1 ./build_release_linux.sh'

docker run --rm \
  -v "$project_dir:/src" \
  alpine:3.20 \
  chown -R "$uid:$gid" /src/build /src/dist
