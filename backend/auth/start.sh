#!/usr/bin/env bash
# ============================================================
# AskSource_Helper · auth 微服务启动脚本
# 用法：
#   ./start.sh              # 默认 dev 模式启动（uvicorn 热重载）
#   ./start.sh dev          # 同上
#   ./start.sh prod         # 生产模式（关闭热重载，多 worker）
#   ./start.sh install      # 安装 / 修复后端依赖（pip install -e .）
#   PORT=8002 ./start.sh    # 通过环境变量指定端口（默认 8001）
# ============================================================

set -euo pipefail

# 切到 backend 目录（auth 的上一级），保证 auth 包可导入、.env 可被读取
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$BACKEND_DIR"

MODE="${1:-dev}"
PORT="${PORT:-8001}"
HOST="${HOST:-127.0.0.1}"
WORKERS="${WORKERS:-4}"

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

# ---------- 选择 Python 解释器（优先 backend/.venv） ----------
if [[ -x ".venv/bin/python" ]]; then
  PY=".venv/bin/python"
elif [[ -x "$SCRIPT_DIR/.venv/bin/python" ]]; then
  PY="$SCRIPT_DIR/.venv/bin/python"
else
  PY="$(command -v python3 || command -v python || true)"
fi
[[ -n "$PY" ]] || { err "未检测到 Python，请先安装 Python (>=3.10)"; exit 1; }

command -v "$PY" >/dev/null 2>&1 || { err "Python 解释器不可用: $PY"; exit 1; }
info "Python: $("$PY" --version 2>&1)  ($PY)"
info "工作目录: $BACKEND_DIR"

# ---------- 依赖检查 / 自动安装 ----------
ensure_deps() {
  if ! "$PY" -c "import fastapi, uvicorn, sqlalchemy, aiomysql" >/dev/null 2>&1; then
    warn "依赖不完整，开始安装 (pip install -e .) ..."
    "$PY" -m pip install -e .
    ok "依赖安装完成"
  else
    ok "依赖已就绪"
  fi
}

# ---------- 模式分发 ----------
case "$MODE" in
  install)
    info "执行 pip install -e . ..."
    "$PY" -m pip install -e .
    ok "依赖安装完成"
    ;;
  dev)
    ensure_deps
    info "以开发模式启动 auth 服务 http://$HOST:$PORT （热重载）..."
    exec env AUTH_HOST="$HOST" AUTH_PORT="$PORT" AUTH_RELOAD=1 "$PY" -m auth.main
    ;;
  prod)
    ensure_deps
    info "以生产模式启动 auth 服务 http://$HOST:$PORT （$WORKERS workers）..."
    exec "$PY" -m uvicorn auth.main:app --host "$HOST" --port "$PORT" --workers "$WORKERS"
    ;;
  -h|--help|help)
    sed -n '2,11p' "$0"
    ;;
  *)
    err "未知模式: $MODE"
    sed -n '2,11p' "$0"
    exit 1
    ;;
esac
