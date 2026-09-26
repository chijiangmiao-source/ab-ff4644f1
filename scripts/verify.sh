#!/usr/bin/env sh
# Compose 验收入口：
#   1. 检查镜像构建（web/verify 同一镜像）
#   2. 启动 web 并等待健康检查通过
#   3. 运行 verify：最短概率反例断言 + 引擎测试 + 真实 API 冒烟
#   4. verify 结束即退出，脚本透传其退出码作为验收退出码
set -eu

cd "$(dirname "$0")/.."

echo ">> [1/3] 构建镜像（检查构建）"
docker compose build

echo ">> [2/3] 启动 web 并等待健康检查"
docker compose up -d web

echo ">> [3/3] 运行一次性验收 verify（结束后退出）"
set +e
docker compose up --abort-on-container-exit --exit-code-from verify verify
code=$?
set -e

echo ">> verify 退出码: $code （0 = 验收通过）"
docker compose stop web >/dev/null 2>&1 || true
exit $code
