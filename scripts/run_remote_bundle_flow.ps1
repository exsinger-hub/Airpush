param(
    [string]$Domain = "medical",
    [string]$RemoteUser = "your-username",
    [string]$RemoteHost = "YOUR_SERVER_IP",
    [string]$RemotePython = "/path/to/your/miniconda/envs/vllm/bin/python",
    [string]$RemoteProjectRoot = "~/medpaper-flow",
    [string]$RemoteBundleRoot = "~/medpaper-flow/import-bundles",
    [string]$LocalBundleDir = "",
    [int]$PdfTopK = 0,
    [switch]$TransferOnly = $false
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = if (Get-Command python -ErrorAction SilentlyContinue) { "python" } else { "python3" }

function ConvertTo-BashSingleQuoted {
    param(
        [Parameter(Mandatory = $true)][string]$Value
    )

    $singleQuoteEscape = "'" + '"' + "'" + '"' + "'"
    return ("'" + ($Value -replace "'", $singleQuoteEscape) + "'")
}

function ConvertTo-BashDoubleQuoted {
    param(
        [Parameter(Mandatory = $true)][string]$Value
    )

    return ('"' + ($Value -replace '"', '\"') + '"')
}

function Resolve-RemoteShellPath {
    param(
        [Parameter(Mandatory = $true)][string]$Value
    )

    if ($Value -eq "~") {
        return '${HOME}'
    }

    if ($Value.StartsWith("~/")) {
        return '${HOME}/' + $Value.Substring(2)
    }

    return $Value
}

function Assert-LastExitCode {
    param(
        [Parameter(Mandatory = $true)][string]$CommandName
    )

    if ($LASTEXITCODE -ne 0) {
        throw "$CommandName failed with exit code $LASTEXITCODE"
    }
}

if (-not (Get-Command $pythonExe -ErrorAction SilentlyContinue)) {
    throw "Python not found. Ensure python or python3 is available in PATH."
}

if ([string]::IsNullOrWhiteSpace($LocalBundleDir)) {
    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $LocalBundleDir = Join-Path $projectRoot "transfer/$Domain/$timestamp"
}

Write-Host "[Bundle] Build local bundle..." -ForegroundColor Cyan
& $pythonExe "$projectRoot/scripts/build_papers_bundle.py" --domain $Domain --output-dir $LocalBundleDir --pdf-top-k $PdfTopK
Assert-LastExitCode "build_papers_bundle.py"

$bundleName = Split-Path -Leaf $LocalBundleDir
$remoteBundlePath = "$RemoteBundleRoot/$bundleName"
$remoteProjectRootExpr = Resolve-RemoteShellPath $RemoteProjectRoot
$remoteBundlePathExpr = Resolve-RemoteShellPath $remoteBundlePath

Write-Host "[Bundle] Ensure remote directory..." -ForegroundColor Cyan
ssh "$RemoteUser@$RemoteHost" "mkdir -p $RemoteBundleRoot"
Assert-LastExitCode "remote directory creation"

Write-Host "[Bundle] Transfer bundle to remote..." -ForegroundColor Cyan
scp -r "$LocalBundleDir" "${RemoteUser}@${RemoteHost}:$RemoteBundleRoot/"
Assert-LastExitCode "bundle transfer"

if ($TransferOnly) {
    Write-Host "[Done] Bundle transferred: $remoteBundlePath" -ForegroundColor Green
    exit 0
}

$remotePreflightCommand = @(
    "set -euo pipefail",
    ("test -d " + (ConvertTo-BashDoubleQuoted $remoteProjectRootExpr)),
    ("test -f " + (ConvertTo-BashDoubleQuoted "$remoteProjectRootExpr/main.py"))
) -join "; "

$escapedRemotePreflightCommand = ConvertTo-BashSingleQuoted $remotePreflightCommand

Write-Host "[Bundle] Validate remote project..." -ForegroundColor Cyan
ssh "$RemoteUser@$RemoteHost" "bash -lc $escapedRemotePreflightCommand"
Assert-LastExitCode "remote project validation"

$remoteCommand = @(
    "set -euo pipefail",
    ("cd " + (ConvertTo-BashDoubleQuoted $remoteProjectRootExpr)),
    ("export DOMAIN=" + (ConvertTo-BashSingleQuoted $Domain)),
    ("export IMPORT_PAPERS_FILE=" + (ConvertTo-BashDoubleQuoted "$remoteBundlePathExpr/papers.json")),
    ("export IMPORT_PDF_ROOT=" + (ConvertTo-BashDoubleQuoted $remoteBundlePathExpr)),
    "export LOCAL_PDF_ONLY=true",
    ("export LOG_FILE=" + (ConvertTo-BashSingleQuoted "logs/run-$Domain-import.log")),
    ((ConvertTo-BashSingleQuoted $RemotePython) + " main.py")
) -join "; "

$escapedRemoteCommand = ConvertTo-BashSingleQuoted $remoteCommand

Write-Host "[Bundle] Run remote imported pipeline..." -ForegroundColor Cyan
ssh "$RemoteUser@$RemoteHost" "bash -lc $escapedRemoteCommand"
Assert-LastExitCode "remote imported pipeline"

Write-Host "[Done] Remote imported flow finished." -ForegroundColor Green