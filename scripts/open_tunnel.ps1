param(
    [string]$Server = "your-username@YOUR_SERVER_IP",
    [int]$LocalPort = 8000,
    [int]$RemotePort = 8000
)

Write-Host "[MedPaper-Flow] 建立 SSH 隧道: localhost:$LocalPort -> $Server:$RemotePort"
Write-Host "首次连接会要求输入服务器密码（不会保存到本地文件）。"

ssh -N -L "$LocalPort`:localhost:$RemotePort" $Server
