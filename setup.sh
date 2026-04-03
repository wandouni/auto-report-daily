#!/usr/bin/env bash
# AI Daily Summary — 安装脚本
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_PATH="$SCRIPT_DIR/ai_daily_summary.py"
OUTPUT_DIR="/Users/shenni/obsidian/AI Daily"

echo "=== AI Daily Summary 安装 ==="

# 1. 安装 Python 依赖
echo "[1/3] 安装 Python 依赖..."
pip3 install openai pyyaml

# 2. 创建输出目录
echo "[2/3] 创建输出目录：$OUTPUT_DIR"
mkdir -p "$OUTPUT_DIR"

# 3. 写入 crontab（去重）
echo "[3/3] 配置 crontab..."

CRON_JOB="0 18 * * 1-5 cd \"$SCRIPT_DIR\" && python3 \"$SCRIPT_PATH\" >> \"$SCRIPT_DIR/cron.log\" 2>&1"

# 获取当前 crontab（忽略空 crontab 的错误）
CURRENT_CRON="$(crontab -l 2>/dev/null || true)"

if echo "$CURRENT_CRON" | grep -qF "$SCRIPT_PATH"; then
    echo "  crontab 条目已存在，跳过。"
else
    (
        echo "$CURRENT_CRON"
        echo "$CRON_JOB"
    ) | crontab -
    echo "  crontab 条目已添加：$CRON_JOB"
fi

echo ""
echo "=== 安装完成 ==="
echo ""
echo "⚠️  重要：请在 macOS「系统设置 → 隐私与安全性 → 完全磁盘访问权限」中"
echo "   添加 /usr/sbin/cron，否则 cron 无法访问 Obsidian vault 中的文件。"
echo ""
echo "📝 下一步："
echo "   1. 编辑 $SCRIPT_DIR/config.yaml，填入你的 API key"
echo "   2. 手动测试：python3 \"$SCRIPT_PATH\""
echo "   3. 脚本将在每个工作日 18:00 自动执行"
