#!/usr/bin/env bash
set -euo pipefail

FAIL=0

echo "=== Checking Hermes skills ==="

for dir in hermes-skills/*/; do
  skill_file="${dir}SKILL.md"
  skill_ok=1

  if [[ ! -f "$skill_file" ]]; then
    echo "FAIL: $dir missing SKILL.md" >&2
    FAIL=1
    continue
  fi

  dirname=$(basename "$dir")
  name_in_frontmatter=$(sed -n '/^---$/,/^---$/p' "$skill_file" | grep '^name:' | head -1 | sed 's/^name:\s*//')

  if [[ "$name_in_frontmatter" != "$dirname" ]]; then
    echo "FAIL: $skill_file name '$name_in_frontmatter' does not match folder '$dirname'" >&2
    FAIL=1
    skill_ok=0
  fi

  description=$(sed -n '/^---$/,/^---$/p' "$skill_file" | grep '^description:' | head -1 | sed 's/^description:\s*//')
  if [[ -z "$description" ]]; then
    echo "FAIL: $skill_file missing description" >&2
    FAIL=1
    skill_ok=0
  fi

  if grep -nE '\<(python3|python|bash|sh)\>[[:space:]]+-c\b' "$skill_file"; then
    echo "FAIL: $skill_file contains an inline interpreter (-c); use plain kubectl instead" >&2
    FAIL=1
    skill_ok=0
  fi

  if (( skill_ok )); then
    echo "OK: $skill_file"
  fi
done

if (( FAIL )); then
  echo ""
  echo "Skills check FAILED." >&2
  exit 1
fi

echo "Skills check passed."