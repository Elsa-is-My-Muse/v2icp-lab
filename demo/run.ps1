param(
    [switch]$Quick,
    [switch]$Tests
)

$ErrorActionPreference = 'Stop'
Push-Location (Split-Path $PSScriptRoot -Parent)
try {
    if ($Tests) {
        python -m unittest discover -s tests -v
    } elseif ($Quick) {
        python -m demo.run_demo --interval 1
    } else {
        python -m demo.run_demo
    }
    $result = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $result
