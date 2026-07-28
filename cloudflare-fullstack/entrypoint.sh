#!/bin/sh
set -eu

# Cloudflare supplies /dev without /dev/shm. dbt-core uses POSIX semaphores even
# for a single-thread DuckDB adapter, so create the standard 01777 semaphore
# directory before permanently dropping to the unprivileged application user.
if [ "$(id -u)" -ne 0 ]; then
  echo "Lineage Detective entrypoint must start as root only to prepare /dev/shm." >&2
  exit 1
fi
mkdir -p /dev/shm
chmod 1777 /dev/shm
exec env HOME=/home/lineage USER=lineage LOGNAME=lineage \
  setpriv --reuid=lineage --regid=lineage --init-groups \
  /app/cloudflare-fullstack/start.sh
