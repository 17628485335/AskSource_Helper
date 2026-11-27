#!/usr/bin/env python3
"""PyCharm Debug 启动包装器：端口被本项目占用时先释放，再启动 uvicorn。

只清理命令行命中目标 app 且看起来是本项目的 uvicorn/wrapper 进程，避免误杀其它服务。
重启逻辑放在当前进程内，PyCharm 断点才能正常命中。
"""

import argparse
import os
import signal
import subprocess
import time


def find_listeners(port: int) -> list[int]:
    """macOS/Linux: 列出监听指定 TCP 端口的 PID。"""
    try:
        result = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        print(f"[runner] lsof 不可用，跳过端口检查（port={port}）", flush=True)
        return []
    return [int(line) for line in result.stdout.splitlines() if line.strip().isdigit()]


def command_of(pid: int) -> str:
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return ""
    return result.stdout.strip()


def free_port_if_ours(port: int, app: str) -> None:
    owners = find_listeners(port)
    if not owners:
        print(f"[runner] port {port} 空闲", flush=True)
        return

    for pid in owners:
        command = command_of(pid)
        ours = app in command and (
            "uvicorn" in command or "run_debug_service.py" in command
        )
        print(f"[runner] port {port} occupied by pid={pid}: {command}", flush=True)
        if not ours:
            raise SystemExit(
                f"[runner] 端口 {port} 被其它进程占用，未自动清理；请先手动关闭。"
            )
        os.kill(pid, signal.SIGTERM)

    deadline = time.time() + 3
    while time.time() < deadline:
        remaining = [pid for pid in owners if pid in find_listeners(port) or _pid_exists(pid)]
        if not remaining:
            print(f"[runner] 已释放 port {port}", flush=True)
            return
        time.sleep(0.1)

    for pid in owners:
        if _pid_exists(pid):
            os.kill(pid, signal.SIGKILL)
    print(f"[runner] 已强制释放 port {port}", flush=True)


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", required=True, help="uvicorn app spec, e.g. app.main:app")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()

    free_port_if_ours(args.port, args.app)

    import uvicorn

    print(
        f"[runner] starting {args.app} at http://{args.host}:{args.port} (reload=False)",
        flush=True,
    )
    uvicorn.run(args.app, host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    main()
