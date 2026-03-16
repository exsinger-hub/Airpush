param(
    [string]$BaseUrl = ""
)

if (-not $BaseUrl) {
    if ($env:OPENAI_BASE_URL) {
        $BaseUrl = $env:OPENAI_BASE_URL
    }
    elseif (Test-Path "config/runtime.yaml") {
        $line = Select-String -Path "config/runtime.yaml" -Pattern '^\s*base_url\s*:\s*"?([^"#]+)"?' | Select-Object -First 1
        if ($line -and $line.Matches.Count -gt 0) {
            $BaseUrl = $line.Matches[0].Groups[1].Value.Trim()
        }
    }
}

if (-not $BaseUrl) {
    $BaseUrl = "http://localhost:8000/v1"
}

$modelsUrl = "$BaseUrl/models"
Write-Host "[MedPaper-Flow] 检查 vLLM 服务: $modelsUrl"

try {
    $resp = Invoke-RestMethod -Method Get -Uri $modelsUrl -TimeoutSec 15
    Write-Host "服务可用，模型列表："
    $resp.data | Select-Object id | Format-Table -AutoSize
}
catch {
    Write-Error "vLLM 服务不可达，请先确认服务器端已启动并且 SSH 隧道已建立。$_"
    exit 1
}
