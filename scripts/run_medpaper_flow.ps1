param(
    [switch]$DryRun = $false,
    [string]$Domain = ""
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot

if ([string]::IsNullOrWhiteSpace($Domain)) {
    if (-not [string]::IsNullOrWhiteSpace($env:DOMAIN)) {
        $Domain = $env:DOMAIN
    }
    else {
        $Domain = "medical"
    }
}

Write-Host "[MedPaper-Flow] Project: $projectRoot"
Write-Host "[MedPaper-Flow] Domain: $Domain"

$pythonExe = if (Get-Command python -ErrorAction SilentlyContinue) { "python" } else { "python3" }
if (-not (Get-Command $pythonExe -ErrorAction SilentlyContinue)) {
    throw "Python not found. Ensure python or python3 is available in PATH."
}

Push-Location $projectRoot
try {
    $env:DOMAIN = $Domain

    Write-Host "[1/3] Check vLLM..."
    & powershell -ExecutionPolicy Bypass -File "$projectRoot/scripts/check_vllm.ps1"

    Write-Host "[2/3] Run deploy test..."
    & $pythonExe "$projectRoot/scripts/test_remote_llm.py" --server-ip 127.0.0.1 --port 8000 --model qwen-32b

    if ($DryRun) {
        $env:DRY_RUN = "true"
        Write-Host "[3/3] Run main pipeline (DRY_RUN=true)..."
    }
    else {
        Write-Host "[3/3] Run main pipeline..."
    }

    & $pythonExe "$projectRoot/main.py"

    Write-Host "[Done] MedPaper-Flow finished."
}
finally {
    Pop-Location
}
