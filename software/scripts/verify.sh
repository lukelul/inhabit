#!/usr/bin/env bash
# scripts/verify.sh — CI/Linux mirror. Robust tool detection. Fails only on real test failures.
set -u; fail=0
PY=""; for c in python3 python py; do command -v "$c" >/dev/null 2>&1 && { PY=$c; break; }; done
CCB=""; for c in cc gcc clang; do command -v "$c" >/dev/null 2>&1 && { CCB=$c; break; }; done

bin="${TMPDIR:-/tmp}/inhabit_verify_$$"
mkdir -p "$bin"

echo "== firmware C tests (can_frame + calib + mcp2515 loopback + can_health + enum) =="
if [ -n "$CCB" ]; then
  ( cd firmware/test &&
    "$CCB" -Wall -Wextra -std=c11 -I../inc test_can_frame.c  ../src/can_frame.c                      -o "$bin/t_frame"  && "$bin/t_frame"  &&
    "$CCB" -Wall -Wextra -std=c11 -I../inc test_calib.c      ../src/calib.c                          -o "$bin/t_calib"  && "$bin/t_calib"  &&
    "$CCB" -Wall -Wextra -std=c11 -I../inc test_mcp2515.c    ../drivers/mcp2515.c ../src/can_frame.c -o "$bin/t_mcp"    && "$bin/t_mcp"    &&
    "$CCB" -Wall -Wextra -std=c11 -I../inc test_can_health.c ../src/can_health.c  ../src/can_frame.c -o "$bin/t_health" && "$bin/t_health" &&
    "$CCB" -Wall -Wextra -std=c11 -I../inc test_enum.c       ../src/enum.c        ../src/can_frame.c -o "$bin/t_enum"   && "$bin/t_enum"   &&
    "$CCB" -Wall -Wextra -std=c11 -I../inc test_enum_integrate.c ../src/enum.c    ../src/can_frame.c -o "$bin/t_enumint" && "$bin/t_enumint" &&
    "$CCB" -Wall -Wextra -std=c11 -I../inc test_bench_3pod.c    ../src/enum.c    ../src/can_frame.c -o "$bin/t_bench3"  && "$bin/t_bench3"  &&
    "$CCB" -Wall -Wextra -std=c11 -I../inc -c ../src/main.c -o "$bin/main.o"
  ) || fail=1
else echo "WARN: no C compiler (cc/gcc/clang) — skipping firmware tests"; fi

echo "== host pytest + coverage gate (>=90%, threshold in host/pyproject.toml) =="
# Run from host/ so coverage.py finds [tool.coverage] in host/pyproject.toml (source/omit/
# branch/fail_under). From repo root that config is invisible: coverage would measure the whole
# tree (tests included, ~97%) and the fail_under gate would silently no-op. cf. the mypy step.
if [ -n "$PY" ]; then ( cd host && "$PY" -m pytest -q ) || fail=1; else echo "WARN: no python"; fi

command -v ruff >/dev/null 2>&1 && { echo "== ruff (blocking) =="; ruff check host || fail=1; } || echo "WARN: no ruff — skipping lint (CI still enforces it)"
command -v mypy >/dev/null 2>&1 && { echo "== mypy strict (blocking, full host tree) =="; ( cd host && mypy . ) || fail=1; } || echo "WARN: no mypy — skipping types (CI still enforces it)"

[ "$fail" = 0 ] && { echo "ALL VERIFIABLE CHECKS PASSED"; exit 0; } || { echo "VERIFY FAILED"; exit 1; }
