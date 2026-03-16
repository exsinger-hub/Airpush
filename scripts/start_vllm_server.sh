#!/usr/bin/env bash
set -euo pipefail

# 在远程 4x4090 服务器执行本脚本
# 依赖: python, pip, tmux

SESSION_NAME="vllm_service"
MODEL="Qwen/Qwen2.5-32-Instruct-AWQ"
PORT="8000"
MAX_LEN="32768"
TP_SIZE="4"
GPU_IDS="0,1,2,3"

pip install -U vllm

if tmux has-session -t "${SESSION_NAME}" 2>/dev/null; then
  echo "tmux session ${SESSION_NAME} 已存在，直接附着查看日志..."
  tmux attach -t "${SESSION_NAME}"
  exit 0
fi

tmux new -d -s "${SESSION_NAME}" \
  "CUDA_VISIBLE_DEVICES=${GPU_IDS} python -m vllm.entrypoints.openai.api_server \
    --model ${MODEL} \
    --tensor-parallel-size ${TP_SIZE} \
    --max-model-len ${MAX_LEN} \
    --port ${PORT}"

echo "vLLM 已在 tmux 会话 ${SESSION_NAME} 启动。"
echo "查看日志: tmux attach -t ${SESSION_NAME}"
echo "后台退出: Ctrl+B 然后 D"
