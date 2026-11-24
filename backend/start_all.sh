#!/usr/bin/env bash
# ============================================================
# AskSource_Helper · Backend 一键启动脚本
# 同时启动：
#   - auth 独立微服务  http://127.0.0.1:8001  (auth.main:app)
#   - 主服务 app.main   http://127.0.0.1:8000  (app.main:app)
#
# 用法：
#   ./start_all.sh                 # 启动两个服务
#   AUTH_PORT=8002 ./start_all.sh  # 自定义端口 / 主机
#   RELOAD=0 ./start_all.sh        # 关闭热重载（默认开启）
# ============================================================

set -euo pipefail

# 切到 backend 目录，保证 app / auth 包可导入、.env 可被读取
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

AUTH_HOST="${AUTH_HOST:-127.0.0.1}"
AUTH_PORT="${AUTH_PORT:-8001}"
MAIN_HOST="${MAIN_HOST:-127.0.0.1}"
MAIN_PORT="${MAIN_PORT:-8000}"
RELOAD="${RELOAD:-1}"

# ---------- 颜色输出 ----------
if [[ -t 1 ]]; then
  C_RESET='\033[0m'; C_INFO='\033[36m'; C_OK='\033[32m'; C_WARN='\033[33m'; C_ERR='\033[31m'
else
  C_RESET=''; C_INFO=''; C_OK=''; C_WARN=''; C_ERR=''
fi
info() { printf "${C_INFO}[INFO]${C_RESET} %s\n"  "$*"; }
ok()   { printf "${C_OK}[OK]${C_RESET}   %s\n"  "$*"; }
warn() { printf "${C_WARN}[WARN]${C_RESET} %s\n"  "$*"; }
err()  { printf "${C_ERR}[ERR]${C_RESET}  %s\n"  "$*" >&2; }
a_info(){ printf "${C_INFO}[AUTH]${C_RESET} %s\n" "$*"; }
m_info(){ printf "${C_INFO}[MAIN]${C_RESET} %s\n" "$*"; }

# ---------- 选择 Python 解释器（优先 backend/.venv） ----------
if [[ -x ".venv/bin/python" ]]; then
  PY=".venv/bin/python"
else
  PY="$(command -v python3 || command -v python || true)"
fi
[[ -n "$PY" ]] || { err "未检测到 Python，请先安装 Python (>=3.10)"; exit 1; }
info "Python: $("$PY" --version 2>&1)  ($PY)"

# ---------- 依赖检查 / 自动安装 ----------
if ! "$PY" -c "import fastapi, uvicorn, sqlalchemy, aiomysql" >/dev/null 2>&1; then
  warn "依赖不完整，开始安装 (pip install -e .) ..."
  "$PY" -m pip install -e .
fi
ok "依赖已就绪"

RELOAD_FLAG=""
[[ "$RELOAD" == "1" ]] && RELOAD_FLAG="--reload"

PIDS=()

cleanup() {
  info "正在停止所有服务 ..."
  for pid in "${PIDS[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
  ok "已全部停止"
}
trap cleanup EXIT INT TERM

# ---------- 启动 auth 独立微服务 (8001) ----------
a_info "启动 auth 服务 http://$AUTH_HOST:$AUTH_PORT $RELOAD_FLAG"
env AUTH_HOST="$AUTH_HOST" AUTH_PORT="$AUTH_PORT" AUTH_RELOAD="$RELOAD" \
  "$PY" -m uvicorn auth.main:app --host "$AUTH_HOST" --port "$AUTH_PORT" $RELOAD_FLAG &
PIDS+=($!)

# ---------- 启动主服务 app.main (8000) ----------
m_info "启动主服务 http://$MAIN_HOST:$MAIN_PORT $RELOAD_FLAG"
"$PY" -m uvicorn app.main:app --host "$MAIN_HOST" --port "$MAIN_PORT" $RELOAD_FLAG &
PIDS+=($!)

echo
ok "两个服务已启动：auth(8001) + 主服务(8000)；按 Ctrl+C 停止"

# 轮询探测：任一进程退出即结束脚本（触发 cleanup 收尾）；兼容 macOS bash 3.2（无 wait -n）
while true; do
  for pid in "${PIDS[@]}"; do
    if ! kill -0 "$pid" 2>/dev/null; then
      warn "检测到进程 $pid 已退出，正在停止其余服务 ..."
      break 2
    fi
  done
  sleep 1
done
