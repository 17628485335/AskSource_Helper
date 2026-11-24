#!/usr/bin/env bash
# ============================================================
# AskSource_Helper · Frontend 启动脚本
# 用法：
#   ./start.sh              # 默认以 dev 模式启动 (vite)
#   ./start.sh dev          # 同上
#   ./start.sh build        # 类型检查 + 生产构建
#   ./start.sh preview      # 构建完成后本地预览 dist
#   ./start.sh install      # 仅安装 / 修复依赖
#   PORT=5174 ./start.sh    # 通过环境变量指定端口
# ============================================================

set -euo pipefail

# 切到脚本所在目录，保证相对路径正确
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

MODE="${1:-dev}"
PORT="${PORT:-}"

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

# ---------- 环境校验 ----------
command -v node >/dev/null 2>&1 || { err "未检测到 node，请先安装 Node.js (>=18)"; exit 1; }
command -v npm  >/dev/null 2>&1 || { err "未检测到 npm，请先安装 npm"; exit 1; }

info "Node: $(node -v)  npm: $(npm -v)"
info "工作目录: $SCRIPT_DIR"

# ---------- 依赖检查 / 自动安装 ----------
ensure_deps() {
  if [[ ! -d "node_modules" ]]; then
    warn "未检测到 node_modules，开始安装依赖 ..."
    npm install
    ok "依赖安装完成"
  else
    ok "依赖已就绪"
  fi
}

# ---------- 端口参数 ----------
build_port_flag() {
  if [[ -n "$PORT" ]]; then
    printf -- "--port %s" "$PORT"
  else
    printf -- ""
  fi
}

# ---------- 模式分发 ----------
case "$MODE" in
  install)
    info "执行 npm install ..."
    rm -rf node_modules package-lock.json 2>/dev/null || true
    npm install
    ok "依赖重装完成"
    ;;
  dev)
    ensure_deps
    PF="$(build_port_flag)"
    info "启动 Vite 开发服务器 ${PORT:+(端口 $PORT)} ..."
    # shellcheck disable=SC2086
    exec npm run dev -- $PF
    ;;
  build)
    ensure_deps
    info "执行 vue-tsc 类型检查 + vite build ..."
    npm run build
    ok "构建完成，产物目录: $SCRIPT_DIR/dist"
    ;;
  preview)
    ensure_deps
    if [[ ! -d "dist" ]]; then
      warn "未检测到 dist，先执行一次 build ..."
      npm run build
    fi
    PF="$(build_port_flag)"
    info "启动本地预览服务 ${PORT:+(端口 $PORT)} ..."
    # shellcheck disable=SC2086
    exec npm run preview -- $PF
    ;;
  -h|--help|help)
    sed -n '2,12p' "$0"
    ;;
  *)
    err "未知模式: $MODE"
    sed -n '2,12p' "$0"
    exit 1
    ;;
esac
