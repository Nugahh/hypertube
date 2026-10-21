#!/bin/sh
# One-shot: enable the legal indexer in Jackett so the backend can search it.
# Safe to run again: it only re-applies the same settings.
set -eu
J="${JACKETT_URL:-http://jackett:9117}"

# the dashboard redirects to itself until it has set a session cookie, and the config API needs that
# cookie (no admin password by default): hence the cookie jar, also while waiting for Jackett to boot
until curl -sfL -c /tmp/jar -b /tmp/jar -o /dev/null "$J/UI/Dashboard"; do sleep 2; done

# searchonlyintitle=false lets the backend send archive.org queries such as collection:feature_films;
# torrentonly: the backend downloads the .torrent file itself, it cannot follow a magnet link
curl -sf -b /tmp/jar -X POST -H 'Content-Type: application/json' \
  -d '[{"id":"searchonlyintitle","value":false},{"id":"sortrequestedfromsite","value":"downloads"},{"id":"downloadusing.torrentonly.nomagnets.","value":true}]' \
  "$J/api/v2.0/indexers/internetarchive/config"

echo "jackett: internetarchive enabled"
