#!/usr/bin/env bash
# Runs every verify script of completed steps, in order. Add new steps as they complete.
set -uo pipefail
DIR="$(dirname "$0")"
rc=0
for s in p0_s1 p0_s2 p0_s3 p0_s4 p0_s5 p0_s6 p1_s1 p1_s2 p1_s3 p1_s4 p1_s5 p1_s6 p1_s7 \
  p2_s1 p2_s2 p2_s3 p2_s4 p2_s5 p2_s6 p2_s7 p2_s8 \
  p3_s1 p3_s2 p3_s3 p3_s4 p3_s5 p3_s6 p3_s7 p3_s8 p3_s9 p3_s10; do
  bash "$DIR/$s.sh" || rc=1
done
exit $rc
