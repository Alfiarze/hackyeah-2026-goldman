#!/bin/sh
# Seed policy and attack feed into their (possibly empty) volumes, then run the given command.
# Existing files are never overwritten: edits made from the console survive restarts and redeploys.
set -e
for kind in policy feeds; do
  for f in /app/defaults/$kind/*; do
    [ -e "/app/$kind/$(basename "$f")" ] || cp "$f" "/app/$kind/"
  done
done
exec "$@"
