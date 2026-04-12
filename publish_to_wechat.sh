#!/bin/bash
# 将已生成的 Obsidian AI Daily 文章直接发布到微信公众号草稿箱
# 用法：
#   bash publish_to_wechat.sh                        # 发布今天的文章
#   bash publish_to_wechat.sh 20260411               # 发布指定日期的文章
#   bash publish_to_wechat.sh 20260411 grace         # 指定主题
#   bash publish_to_wechat.sh --themes               # 列出所有可用主题

set -e

VALID_THEMES=("default" "grace" "simple" "modern")

# ── --themes 帮助 ─────────────────────────────────────────────────────────────
if [ "$1" = "--themes" ]; then
  echo "可用主题："
  for t in "${VALID_THEMES[@]}"; do
    [ "$t" = "default" ] && echo "  $t（默认）" || echo "  $t"
  done
  exit 0
fi

# ── 日期 ──────────────────────────────────────────────────────────────────────
if [ -n "$1" ]; then
  RAW="$1"
  DATE_STR="${RAW:0:4}-${RAW:4:2}-${RAW:6:2}"
else
  DATE_STR=$(date +%Y-%m-%d)
  RAW=$(date +%Y%m%d)
fi

# ── 主题 ──────────────────────────────────────────────────────────────────────
THEME="${2:-default}"
VALID=0
for t in "${VALID_THEMES[@]}"; do
  [ "$t" = "$THEME" ] && VALID=1 && break
done
if [ "$VALID" = "0" ]; then
  echo "错误：不支持的主题 \"$THEME\"" >&2
  echo "可用主题：${VALID_THEMES[*]}" >&2
  exit 1
fi

# ── 路径（与 config.yaml 保持一致）────────────────────────────────────────────
OUTPUT_DIR="/Users/shenni/obsidian/AI Daily"
MD_FILE="$OUTPUT_DIR/AI Daily-${RAW}.md"
WECHAT_SCRIPT="$HOME/.claude/plugins/marketplaces/baoyu-skills/skills/baoyu-post-to-wechat/scripts/wechat-api.ts"
COVER="/Users/shenni/repository/auto-report-daily/assets/default-cover.png"

# ── 前置检查 ──────────────────────────────────────────────────────────────────
if [ ! -f "$MD_FILE" ]; then
  echo "错误：文章不存在：$MD_FILE" >&2
  exit 1
fi

if [ ! -f "$WECHAT_SCRIPT" ]; then
  echo "错误：wechat-api.ts 不存在，请先安装 baoyu-skills" >&2
  exit 1
fi

if command -v bun &>/dev/null; then
  BUN="bun"
elif command -v npx &>/dev/null; then
  BUN="npx -y bun"
else
  echo "错误：未找到 bun 或 npx" >&2
  exit 1
fi

# ── 剥掉 YAML frontmatter ─────────────────────────────────────────────────────
TMPFILE=$(mktemp /tmp/wechat-XXXX.md)
trap 'rm -f "$TMPFILE"' EXIT

python3 - "$MD_FILE" "$TMPFILE" <<'EOF'
import sys
content = open(sys.argv[1], encoding='utf-8').read()
if content.startswith('---'):
    second = content.find('\n---', 3)
    if second != -1:
        content = content[second + 4:].lstrip('\n')
open(sys.argv[2], 'w', encoding='utf-8').write(content)
EOF

# ── 发布 ──────────────────────────────────────────────────────────────────────
TITLE="AI Daily Summary - ${DATE_STR}"
echo "发布：$TITLE"

CMD=($BUN "$WECHAT_SCRIPT" "$TMPFILE" --title "$TITLE" --theme "$THEME" --no-cite)
[ -f "$COVER" ] && CMD+=(--cover "$COVER")

"${CMD[@]}"
