#!/usr/bin/env bash
set -euo pipefail

# 一次性运行脚本（Linux/macOS）
# 用法：
#   bash scripts/run_medpaper_flow_once.sh --domain medical
#   bash scripts/run_medpaper_flow_once.sh --domain cqed_plasmonics --dry-run

DOMAIN="medical"
DRY_RUN="false"
SKIP_CHECK="false"
PYTHON_BIN=""
START_VLLM="false"
VLLM_LOG="logs/vllm_8000.log"
VLLM_WAIT_SEC="90"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --domain)
      DOMAIN="${2:-medical}"
      shift 2
      ;;
    --dry-run)
      DRY_RUN="true"
      shift
      ;;
    --skip-check)
      SKIP_CHECK="true"
      shift
      ;;
    --python)
      PYTHON_BIN="${2:-}"
      shift 2
      ;;
    --start-vllm)
      START_VLLM="true"
      shift
      ;;
    --vllm-log)
      VLLM_LOG="${2:-logs/vllm_8000.log}"
      shift 2
      ;;
    --vllm-wait)
      VLLM_WAIT_SEC="${2:-90}"
      shift 2
      ;;
    -h|--help)
      echo "Usage: $0 [--domain <name>] [--dry-run] [--skip-check] [--python <bin>] [--start-vllm] [--vllm-log <path>] [--vllm-wait <sec>]"
      exit 0
      ;;
    *)
      echo "Unknown arg: $1"
      exit 1
      ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if [[ -z "$PYTHON_BIN" ]]; then
  if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
  elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="python"
  else
    echo "[Error] python/python3 not found"
    exit 1
  fi
fi

export DOMAIN
export DRY_RUN

echo "[MedPaper-Flow] Project: $PROJECT_ROOT"
echo "[MedPaper-Flow] Domain:  $DOMAIN"
echo "[MedPaper-Flow] DryRun:  $DRY_RUN"
echo "[MedPaper-Flow] Python:  $PYTHON_BIN"
echo "[MedPaper-Flow] StartVLLM: $START_VLLM"
echo "[MedPaper-Flow] VLLM_WAIT_SEC: $VLLM_WAIT_SEC"

cd "$PROJECT_ROOT"

if [[ "$START_VLLM" == "true" ]]; then
  echo "[0/3] Start vLLM server..."
  if command -v curl >/dev/null 2>&1; then
    if curl -sf "http://127.0.0.1:8000/v1/models" >/dev/null 2>&1; then
      echo "[MedPaper-Flow] vLLM already online at http://127.0.0.1:8000/v1"
    else
      "$PYTHON_BIN" -c "import vllm" >/dev/null 2>&1 || {
        echo "[Error] vLLM not installed in $PYTHON_BIN environment"
        echo "        Try: $PYTHON_BIN -m pip install -U vllm"
        exit 1
      }

      mkdir -p "$(dirname "$VLLM_LOG")"
      CUDA_VISIBLE_DEVICES=0,1,2,3 "$PYTHON_BIN" -m vllm.entrypoints.openai.api_server \
        --model ./Qwen2.5-32B-Instruct-AWQ \
        --tensor-parallel-size 4 \
        --max-model-len 32768 \
        --max-num-seqs 16 \
        --gpu-memory-utilization 0.85 \
        --quantization awq_marlin \
        --port 8000 \
        --served-model-name qwen-32b >"$VLLM_LOG" 2>&1 &
      echo "[MedPaper-Flow] vLLM started (pid=$!, log=$VLLM_LOG)"

      ok="false"
      for _ in $(seq 1 "$VLLM_WAIT_SEC"); do
        if curl -sf "http://127.0.0.1:8000/v1/models" >/dev/null 2>&1; then
          ok="true"
          break
        fi
        sleep 1
      done

      if [[ "$ok" != "true" ]]; then
        echo "[Error] vLLM did not become healthy within ${VLLM_WAIT_SEC}s"
        echo "[Hint] tail -n 120 $VLLM_LOG"
        tail -n 120 "$VLLM_LOG" || true
        exit 1
      fi
      echo "[MedPaper-Flow] vLLM health check passed"
    fi
  else
    echo "[Warn] curl not found, skip local health probing"
    mkdir -p "$(dirname "$VLLM_LOG")"
    CUDA_VISIBLE_DEVICES=0,1,2,3 "$PYTHON_BIN" -m vllm.entrypoints.openai.api_server \
      --model ./Qwen2.5-32B-Instruct-AWQ \
      --tensor-parallel-size 4 \
      --max-model-len 32768 \
      --max-num-seqs 16 \
      --gpu-memory-utilization 0.85 \
      --quantization awq_marlin \
      --port 8000 \
      --served-model-name qwen-32b >"$VLLM_LOG" 2>&1 &
    echo "[MedPaper-Flow] vLLM started (pid=$!, log=$VLLM_LOG)"
    sleep 8
  fi
fi

if [[ "$SKIP_CHECK" != "true" ]]; then
  echo "[1/3] Check vLLM..."
  "$PYTHON_BIN" scripts/test_remote_llm.py --server-ip "$SERVER_HOST" --port "$SERVER_PORT" --model qwen-32b || {
    echo "[Warn] vLLM deploy test failed; continue running main pipeline."
  }
else
  echo "[1/3] Skip vLLM check (--skip-check)"
fi

echo "[2/3] Run main pipeline..."
"$PYTHON_BIN" main.py

echo "[Done] MedPaper-Flow finished."
