# scripts/verify.ps1 — single source of "is it working". Robust tool detection (Windows + *nix).
# Fails on a real test failure, a ruff lint error, or a mypy type error — matching CI
# (which runs `ruff check host` and `cd host && mypy .` as BLOCKING gates over the whole
# host tree, tests included). Keeping these blocking + full-tree here stops the
# "green locally, red in CI" gap (e.g. a type error in a file outside host/inhabit_can).
$fail = $false
function Find-Cmd($names){ foreach($n in $names){ if(Get-Command $n -ErrorAction SilentlyContinue){ return $n } } return $null }
$cc = Find-Cmd @('gcc','clang','cc')
$py = Find-Cmd @('python','python3','py')

$bin = Join-Path $env:TEMP ("inhabit_verify_" + [System.Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $bin | Out-Null

Write-Host "== firmware C tests (can_frame + calib + mcp2515 loopback + can_health + enum) =="
if ($cc) {
  Push-Location firmware/test
  try {
    & $cc -Wall -Wextra -std=c11 -I../inc test_can_frame.c ../src/can_frame.c -o "$bin/t_frame.exe";  if($LASTEXITCODE){throw "build can_frame"};  & "$bin/t_frame.exe";  if($LASTEXITCODE){throw "run can_frame"}
    & $cc -Wall -Wextra -std=c11 -I../inc test_calib.c ../src/calib.c -o "$bin/t_calib.exe"; if($LASTEXITCODE){throw "build calib"}; & "$bin/t_calib.exe"; if($LASTEXITCODE){throw "run calib"}
    & $cc -Wall -Wextra -std=c11 -I../inc test_mcp2515.c ../drivers/mcp2515.c ../src/can_frame.c -o "$bin/t_mcp.exe"; if($LASTEXITCODE){throw "build mcp2515"}; & "$bin/t_mcp.exe"; if($LASTEXITCODE){throw "run mcp2515"}
    & $cc -Wall -Wextra -std=c11 -I../inc test_can_health.c ../src/can_health.c ../src/can_frame.c -o "$bin/t_health.exe"; if($LASTEXITCODE){throw "build can_health"}; & "$bin/t_health.exe"; if($LASTEXITCODE){throw "run can_health"}
    & $cc -Wall -Wextra -std=c11 -I../inc test_enum.c ../src/enum.c ../src/can_frame.c -o "$bin/t_enum.exe"; if($LASTEXITCODE){throw "build enum"}; & "$bin/t_enum.exe"; if($LASTEXITCODE){throw "run enum"}
    & $cc -Wall -Wextra -std=c11 -I../inc test_enum_integrate.c ../src/enum.c ../src/can_frame.c -o "$bin/t_enumint.exe"; if($LASTEXITCODE){throw "build enum_integrate"}; & "$bin/t_enumint.exe"; if($LASTEXITCODE){throw "run enum_integrate"}
    & $cc -Wall -Wextra -std=c11 -I../inc test_bench_3pod.c ../src/enum.c ../src/can_frame.c -o "$bin/t_bench3.exe"; if($LASTEXITCODE){throw "build bench_3pod"}; & "$bin/t_bench3.exe"; if($LASTEXITCODE){throw "run bench_3pod"}
    & $cc -Wall -Wextra -std=c11 -I../inc -c ../src/main.c -o "$bin/main.o"; if($LASTEXITCODE){throw "build main.c"}
  } catch { Write-Warning "firmware test failed: $_"; $fail = $true }
  Pop-Location
} else { Write-Warning "no C compiler (gcc/clang/cc) - skipping firmware tests" }

Write-Host "== host pytest + coverage gate (>=90%, threshold in host/pyproject.toml) =="
# Run from host/ so coverage.py reads [tool.coverage] in host/pyproject.toml (source/omit/
# branch/fail_under). From repo root that config is invisible: coverage would measure the whole
# tree (tests included, ~97%) and the fail_under gate would silently no-op. cf. the mypy step.
if ($py) {
  Push-Location host
  & $py -m pytest -q
  if ($LASTEXITCODE -ne 0) { $fail = $true }
  Pop-Location
} else { Write-Warning "no python - skipping pytest" }

$ruff = Find-Cmd @('ruff')
if ($ruff) { Write-Host "== ruff (blocking) =="; & $ruff check host; if ($LASTEXITCODE -ne 0) { $fail = $true } }
else { Write-Warning "no ruff - skipping lint (CI still enforces it)" }
# Match CI exactly: `cd host && mypy .` (strict via host/pyproject.toml) over the full
# host tree, tests included — not just host/inhabit_can.
$mypy = Find-Cmd @('mypy')
if ($mypy) {
  Write-Host "== mypy strict (blocking, full host tree) =="
  Push-Location host
  & $mypy .
  if ($LASTEXITCODE -ne 0) { $fail = $true }
  Pop-Location
} else { Write-Warning "no mypy - skipping types (CI still enforces it)" }

if ($fail) { Write-Error "VERIFY FAILED - fix the failing test before stopping."; exit 1 }
Write-Host "ALL VERIFIABLE CHECKS PASSED" -ForegroundColor Green; exit 0
