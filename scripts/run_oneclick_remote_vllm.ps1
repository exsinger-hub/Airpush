param(
    [string]$Domain = "cqed_plasmonics",
    [string]$RemoteUser = "your-username",
    [string]$RemoteHost = "YOUR_SERVER_IP",
    [string]$RemotePython = "/path/to/your/miniconda/envs/vllm/bin/python",
    [string]$RemoteModelPath = "./Qwen2.5-32B-Instruct-AWQ",
    [string]$RemoteLog = "~/logs/vllm_8000.log",
    [int]$WaitSeconds = 120,
    [switch]$DryRun = $false
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot

Write-Host "[OneClick] Project: $projectRoot"
Write-Host "[OneClick] Domain: $Domain"
Write-Host "[OneClick] Remote: $RemoteUser@$RemoteHost"

$remoteStart = "mkdir -p ~/logs; if ss -ltn | grep -q ':8000 '; then echo '[Remote] vLLM already listening on :8000'; else nohup CUDA_VISIBLE_DEVICES=0,1,2,3 $RemotePython -m vllm.entrypoints.openai.api_server --model $RemoteModelPath --tensor-parallel-size 4 --max-model-len 32768 --max-num-seqs 16 --gpu-memory-utilization 0.85 --quantization awq_marlin --port 8000 --served-model-name qwen-32b > $RemoteLog 2>&1 & echo '[Remote] started vLLM, log: $RemoteLog'; fi"

Write-Host "[1/3] Start remote vLLM..."
ssh "$RemoteUser@$RemoteHost" "bash -lc \"$remoteStart\""

Write-Host "[2/3] Wait for vLLM health..."
$ok = $false
for ($i = 0; $i -lt $WaitSeconds; $i++) {
    try {
        $resp = Invoke-RestMethod -Method Get -Uri "http://$RemoteHost`:8000/v1/models" -TimeoutSec 5
        if ($resp.data) {
            $ok = $true
            break
        }
    }
    catch {
        Start-Sleep -Seconds 1
    }
}

if (-not $ok) {
    throw "vLLM health check failed after ${WaitSeconds}s: http://$RemoteHost:8000/v1/models"
}

Write-Host "[3/3] Run local pipeline..."
Push-Location $projectRoot
try {
    if ($DryRun) {
        & powershell -ExecutionPolicy Bypass -File "$projectRoot/scripts/run_medpaper_flow.ps1" -Domain $Domain -DryRun
    }
    else {
        & powershell -ExecutionPolicy Bypass -File "$projectRoot/scripts/run_medpaper_flow.ps1" -Domain $Domain
    }
}
finally {
    Pop-Location
}

Write-Host "[Done] One-click flow finished."
