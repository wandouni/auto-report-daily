#!/bin/bash
# 将任意 Markdown 文件发布到微信公众号草稿箱
# 用法：
#   bash publish_md_to_wechat.sh <文件路径>                  # 使用文件名作为标题
#   bash publish_md_to_wechat.sh <文件路径> "自定义标题"      # 指定标题
#   bash publish_md_to_wechat.sh <文件路径> "标题" modern    # 指定标题和主题
#   bash publish_md_to_wechat.sh --themes                   # 列出所有可用主题

set -e

VALID_THEMES=("default" "grace" "simple" "modern")

# ── --themes 帮助 ─────────────────────────────────────────────────────────────
if [ "$1" = "--themes" ]; then
  echo "可用主题："
  for t in "${VALID_THEMES[@]}"; do
    [ "$t" = "modern" ] && echo "  $t（默认）" || echo "  $t"
  done
  exit 0
fi

# ── 参数校验 ──────────────────────────────────────────────────────────────────
if [ -z "$1" ]; then
  echo "用法：bash publish_md_to_wechat.sh <文件路径> [标题] [主题]" >&2
  echo "      bash publish_md_to_wechat.sh --themes" >&2
  exit 1
fi

MD_FILE="$1"
if [ ! -f "$MD_FILE" ]; then
  echo "错误：文件不存在：$MD_FILE" >&2
  exit 1
fi

# ── 标题：优先用第二个参数，否则取文件名（去掉扩展名）────────────────────────
if [ -n "$2" ]; then
  TITLE="$2"
else
  TITLE=$(basename "$MD_FILE" .md)
fi

# ── 主题 ──────────────────────────────────────────────────────────────────────
THEME="${3:-modern}"
VALID=0
for t in "${VALID_THEMES[@]}"; do
  [ "$t" = "$THEME" ] && VALID=1 && break
done
if [ "$VALID" = "0" ]; then
  echo "错误：不支持的主题 \"$THEME\"" >&2
  echo "可用主题：${VALID_THEMES[*]}" >&2
  exit 1
fi

# ── 路径 ──────────────────────────────────────────────────────────────────────
WECHAT_SCRIPT="$HOME/.claude/plugins/marketplaces/baoyu-skills/skills/baoyu-post-to-wechat/scripts/wechat-api.ts"
COVER="/Users/shenni/repository/auto-report-daily/assets/default-cover.png"

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

# ── 剥掉 YAML frontmatter（如有）────────────────────────────────────────────
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
echo "发布：$TITLE（主题：$THEME）"

CMD=($BUN "$WECHAT_SCRIPT" "$TMPFILE" --title "$TITLE" --theme "$THEME" --no-cite)
[ -f "$COVER" ] && CMD+=(--cover "$COVER")

"${CMD[@]}"
