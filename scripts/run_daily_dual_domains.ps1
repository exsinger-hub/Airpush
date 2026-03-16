param(
    [switch]$DryRun,
    [switch]$SkipPreflight,
    [bool]$StopOnDomainError = $false,
    [bool]$SkipRemoteVllmStart = $false,
    [bool]$SkipRemoteVllmStop = $false,
    [string]$RemoteUser = "your-username",
    [string]$RemoteHost = "YOUR_SERVER_IP",
    [string]$RemotePython = "/path/to/your/miniconda/envs/vllm/bin/python",
    [string]$RemoteModelPath = "./Qwen2.5-32B-Instruct-AWQ",
    [string]$RemoteLog = "~/logs/vllm_8000.log",
    [int]$WaitSeconds = 300
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = if (Get-Command python -ErrorAction SilentlyContinue) { "python" } else { "python3" }

if (-not (Get-Command $pythonExe -ErrorAction SilentlyContinue)) {
    throw "Python not found. Ensure python or python3 is available in PATH."
}

$stopOnDomainErrorFlag = [bool]$StopOnDomainError
$skipRemoteVllmStartFlag = [bool]$SkipRemoteVllmStart
$skipRemoteVllmStopFlag = [bool]$SkipRemoteVllmStop

function Test-RemoteVllmHealth {
    try {
        $resp = Invoke-RestMethod -Method Get -Uri "http://$RemoteHost`:8000/v1/models" -TimeoutSec 5
        return [bool]($resp.data)
    }
    catch {
        return $false
    }
}

function Start-RemoteVllmServer {
    Write-Host "[Remote] Start vLLM on $RemoteUser@$RemoteHost ..."
    $remoteStart = "mkdir -p ~/logs; if ss -ltn | grep -q ':8000 '; then echo '[Remote] vLLM already listening on :8000'; else nohup env CUDA_VISIBLE_DEVICES=0,1,2,3 $RemotePython -m vllm.entrypoints.openai.api_server --model $RemoteModelPath --tensor-parallel-size 4 --max-model-len 32768 --max-num-seqs 16 --gpu-memory-utilization 0.85 --quantization awq_marlin --port 8000 --served-model-name qwen-32b > $RemoteLog 2>&1 < /dev/null & echo '[Remote] started vLLM, log: $RemoteLog'; fi"
    ssh "$RemoteUser@$RemoteHost" "bash -lc \"$remoteStart\""

    $ok = $false
    for ($i = 0; $i -lt $WaitSeconds; $i++) {
        if (Test-RemoteVllmHealth) {
            $ok = $true
            break
        }
        else {
            Start-Sleep -Seconds 1
        }
    }

    if (-not $ok) {
        throw "vLLM health check failed after ${WaitSeconds}s: http://$RemoteHost:8000/v1/models"
    }
    Write-Host "[Remote] vLLM health check passed." -ForegroundColor Green
}

function Ensure-RemoteVllmAvailable {
    param(
        [string]$Reason = ""
    )

    $reasonText = if ([string]::IsNullOrWhiteSpace($Reason)) { "" } else { " ($Reason)" }
    if (Test-RemoteVllmHealth) {
        Write-Host "[Remote] vLLM available$reasonText" -ForegroundColor Green
        return
    }

    Write-Host "[Remote] vLLM unavailable$reasonText, restarting..." -ForegroundColor Yellow
    Start-RemoteVllmServer
}

function Stop-RemoteVllmServer {
    Write-Host "[Remote] Stop vLLM and release GPU memory on $RemoteUser@$RemoteHost ..."
    $remoteStop = @"
pkill -f 'vllm.entrypoints.openai.api_server.*--port 8000' >/dev/null 2>&1 || true
fuser -k 8000/tcp >/dev/null 2>&1 || true
sleep 3
echo '[Remote] Remaining vLLM processes:'
ps -ef | grep vllm | grep -v grep || true
echo '[Remote] GPU status after cleanup:'
nvidia-smi || true
"@
    ssh "$RemoteUser@$RemoteHost" "bash -lc \"$remoteStop\""
}

function Invoke-DomainRun {
    param(
        [Parameter(Mandatory = $true)][string]$Domain,
        [Parameter(Mandatory = $true)][string]$LogFile,
        [switch]$DryRunMode
    )

    Write-Host ""
    Write-Host "========== DOMAIN: $Domain ==========" -ForegroundColor Cyan

    $env:DOMAIN = $Domain
    $env:LOG_FILE = $LogFile

    if ($DryRunMode) {
        $env:DRY_RUN = "true"
    }
    else {
        Remove-Item Env:DRY_RUN -ErrorAction SilentlyContinue
    }

    & $pythonExe "$projectRoot/main.py"
}

Push-Location $projectRoot
try {
    if (-not $skipRemoteVllmStartFlag) {
        Start-RemoteVllmServer
    }
    else {
        Ensure-RemoteVllmAvailable -Reason "skip-start mode pre-check"
    }

    if (-not $SkipPreflight) {
        Ensure-RemoteVllmAvailable -Reason "before preflight"
        Write-Host "[Preflight] Check vLLM..."
        & powershell -ExecutionPolicy Bypass -File "$projectRoot/scripts/check_vllm.ps1" -BaseUrl "http://$RemoteHost`:8000/v1"

        Write-Host "[Preflight] Run deploy test..."
        & $pythonExe "$projectRoot/scripts/test_remote_llm.py" --server-ip $RemoteHost --port 8000 --model qwen-32b
    }

    $domains = @(
        @{ Name = "medical"; Log = "$projectRoot/logs/run-medical.log" },
        @{ Name = "cqed_plasmonics"; Log = "$projectRoot/logs/run-cqed_plasmonics.log" }
    )

    foreach ($item in $domains) {
        try {
            Ensure-RemoteVllmAvailable -Reason "before domain $($item.Name)"
            Invoke-DomainRun -Domain $item.Name -LogFile $item.Log -DryRunMode:$DryRun
        }
        catch {
            Write-Host "[ERROR] Domain $($item.Name) failed: $($_.Exception.Message)" -ForegroundColor Red
            if ($stopOnDomainErrorFlag) {
                throw
            }
        }
    }

    Write-Host ""
    Write-Host "[Done] Daily dual-domain pipeline finished." -ForegroundColor Green
}
finally {
    if (-not $skipRemoteVllmStopFlag) {
        try {
            Stop-RemoteVllmServer
        }
        catch {
            Write-Host "[WARN] Failed to stop remote vLLM cleanly: $($_.Exception.Message)" -ForegroundColor Yellow
        }
    }
    Remove-Item Env:DOMAIN -ErrorAction SilentlyContinue
    Remove-Item Env:LOG_FILE -ErrorAction SilentlyContinue
    if (-not $DryRun) {
        Remove-Item Env:DRY_RUN -ErrorAction SilentlyContinue
    }
    Pop-Location
}
