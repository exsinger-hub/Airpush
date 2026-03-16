from __future__ import annotations

import argparse
import os

from openai import OpenAI


def main() -> None:
    parser = argparse.ArgumentParser(description="Test OpenAI-compatible vLLM endpoint")
    parser.add_argument("--server-ip", default=os.getenv("VLLM_SERVER_IP", "127.0.0.1"))
    parser.add_argument("--port", default=os.getenv("VLLM_SERVER_PORT", "8000"))
    parser.add_argument(
        "--model",
        default=os.getenv("LLM_DEEP_MODEL", "Qwen/Qwen2.5-72B-Instruct-AWQ"),
        help="Must match vLLM served model name",
    )
    args = parser.parse_args()

    client = OpenAI(
        api_key="EMPTY",
        base_url=f"http://{args.server_ip}:{args.port}/v1",
    )

    print(f"Connecting to http://{args.server_ip}:{args.port}/v1 ...")
    response = client.chat.completions.create(
        model=args.model,
        messages=[
            {"role": "system", "content": "你是一个严谨的医学影像 AI 助手。"},
            {"role": "user", "content": "请用一句话解释什么是 MRI 的 T1 和 T2 加权成像？"},
        ],
        temperature=0.2,
        max_tokens=120,
        timeout=60,
    )

    print("\n模型回复:\n")
    print(response.choices[0].message.content or "")


if __name__ == "__main__":
    main()
