#!/usr/bin/env bash
# Regenerates the PDF parser fixtures from prospectus.html with headless Chrome (macOS paths).
# prospectus_nastaliq.pdf = Noto Nastaliq Urdu (hard case: must be flagged for OCR)
# prospectus_naskh.pdf    = Geeza Pro (Naskh, like most Word exports: must extract cleanly)
set -euo pipefail
cd "$(dirname "$0")"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
"$CHROME" --headless=new --disable-gpu --no-pdf-header-footer \
  --print-to-pdf=prospectus_nastaliq.pdf "file://$PWD/prospectus.html"
sed 's/font-family: "Noto Nastaliq Urdu", "Geeza Pro", serif/font-family: "Geeza Pro", serif/; s/Prospectus 2027</Prospectus 2027 (Naskh)</' \
  prospectus.html > /tmp/raabta_naskh.html
"$CHROME" --headless=new --disable-gpu --no-pdf-header-footer \
  --print-to-pdf=prospectus_naskh.pdf "file:///tmp/raabta_naskh.html"
