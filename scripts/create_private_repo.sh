#!/usr/bin/env bash
set -euo pipefail
# Run only after checks and review of git diff --cached --stat.
gh repo create LocalOCR --private --source=. --remote=origin --push
gh repo view --json name,url,visibility
