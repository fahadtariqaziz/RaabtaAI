#!/usr/bin/env bash
# Runs every verify script of completed steps, in order. Add new steps as they complete.
set -uo pipefail
DIR="$(dirname "$0")"
rc=0
for s in p0_s1 p0_s2 p0_s3 p0_s4 p0_s5; do
  bash "$DIR/$s.sh" || rc=1
done
exit $rc
