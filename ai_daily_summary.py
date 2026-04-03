#!/usr/bin/env python3
"""
AI Daily Summary Tool
自动从 Day Planner、Clippings、Claude CLI 对话记录收集当天内容，
调用 LLM API 生成结构化总结，写入 Obsidian AI Daily 目录。
"""

import os
import sys
import json
import shutil
import logging
import subprocess
import tempfile
from datetime import datetime, date
from pathlib import Path
from typing import Optional

import yaml
from openai import OpenAI

# ─────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────

def setup_logging(log_path: Path) -> logging.Logger:
    logger = logging.getLogger('ai_daily')
    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', '%Y-%m-%d %H:%M:%S')

    # 终端
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    # 文件
    fh = logging.FileHandler(log_path, encoding='utf-8')
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    return logger


# ─────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────

def load_config(config_path: Path) -> dict:
    if not config_path.exists():
        print(f'[ERROR] 配置文件不存在：{config_path}', file=sys.stderr)
        sys.exit(1)
    with open(config_path, encoding='utf-8') as f:
        return yaml.safe_load(f)


# ─────────────────────────────────────────────
# 数据源 1：Day Planner
# ─────────────────────────────────────────────

def read_day_planner(vault: str, target_date: date, logger: logging.Logger) -> str:
    date_str = target_date.strftime('%Y-%m-%d')
    file_path = Path(vault) / 'Day Planners' / f'{date_str}.md'

    if not file_path.exists():
        logger.warning(f'Day Planner 文件不存在：{file_path}')
        return ''

    content = file_path.read_text(encoding='utf-8')
    logger.info(f'Day Planner 读取成功：{file_path}，{len(content)} 字符')
    return content


# ─────────────────────────────────────────────
# 数据源 2：Clippings
# ─────────────────────────────────────────────

def read_clippings(vault: str, target_date: date, logger: logging.Logger) -> str:
    clippings_dir = Path(vault) / 'Clippings'

    if not clippings_dir.exists():
        logger.warning(f'Clippings 目录不存在：{clippings_dir}')
        return ''

    md_files = sorted(clippings_dir.glob('*.md'))
    today_files = []

    for fp in md_files:
        try:
            birth = datetime.fromtimestamp(os.stat(fp).st_birthtime).date()
            if birth == target_date:
                today_files.append(fp)
        except Exception as e:
            logger.warning(f'读取文件创建时间失败：{fp}，{e}')

    if not today_files:
        logger.info(f'Clippings：当天（{target_date}）无新建文件')
        return ''

    parts = []
    for fp in today_files:
        content = fp.read_text(encoding='utf-8')
        parts.append(f'### 📄 {fp.name}\n\n{content}')
        logger.info(f'Clippings 文件：{fp.name}，{len(content)} 字符')

    result = '\n\n'.join(parts)
    logger.info(f'Clippings 合计：{len(today_files)} 个文件，{len(result)} 字符')
    return result


# ─────────────────────────────────────────────
# 数据源 3：Claude CLI 对话记录
# ─────────────────────────────────────────────

def _project_display_name(dir_name: str) -> str:
    """从目录名提取可读项目名。"""
    for sep in ['-repository-', '-project-']:
        if sep in dir_name:
            return dir_name.split(sep, 1)[-1]
    return dir_name


def _parse_content(content) -> str:
    """解析 content 字段（字符串或数组）。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = [item.get('text', '') for item in content if isinstance(item, dict) and item.get('type') == 'text']
        return '\n'.join(texts)
    return str(content)


def read_claude_cli(target_date: date, logger: logging.Logger) -> str:
    projects_dir = Path.home() / '.claude' / 'projects'

    if not projects_dir.exists():
        logger.warning(f'Claude CLI 目录不存在：{projects_dir}')
        return ''

    MAX_MSG_CHARS = 2000
    MAX_MSGS_PER_PROJECT = 50

    project_sections = []

    for project_dir in sorted(projects_dir.iterdir()):
        if not project_dir.is_dir():
            continue

        jsonl_files = list(project_dir.glob('*.jsonl'))
        # 用文件 mtime 做粗过滤：当天未修改的文件肯定没有当天消息
        candidate_jsonl = [
            fp for fp in jsonl_files
            if datetime.fromtimestamp(fp.stat().st_mtime).date() >= target_date
        ]

        if not candidate_jsonl:
            continue

        project_name = _project_display_name(project_dir.name)
        messages = []

        for jsonl_path in sorted(candidate_jsonl):
            try:
                with open(jsonl_path, encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            obj = json.loads(line)
                        except json.JSONDecodeError:
                            continue

                        # 按消息自身 timestamp 过滤，精确匹配目标日期
                        ts_str = obj.get('timestamp', '')
                        if ts_str:
                            try:
                                msg_date = datetime.fromisoformat(ts_str.replace('Z', '+00:00')).date()
                                if msg_date != target_date:
                                    continue
                            except ValueError:
                                pass

                        # 实际格式：{"type": "user"/"assistant", "message": {"role": ..., "content": ...}}
                        msg = obj.get('message') or obj
                        role = msg.get('role', '')
                        if role not in ('user', 'assistant'):
                            continue

                        raw = _parse_content(msg.get('content', ''))
                        if len(raw) > MAX_MSG_CHARS:
                            raw = raw[:MAX_MSG_CHARS] + '...(已截断)'

                        label = '🧑 用户' if role == 'user' else '🤖 Claude'
                        messages.append(f'**{label}**: {raw}')

                        if len(messages) >= MAX_MSGS_PER_PROJECT:
                            break

            except Exception as e:
                logger.warning(f'解析 JSONL 文件失败：{jsonl_path}，{e}')

            if len(messages) >= MAX_MSGS_PER_PROJECT:
                break

        if messages:
            section = f'### 🖥️ CLI项目: {project_name}\n\n' + '\n'.join(messages)
            project_sections.append(section)
            logger.info(f'Claude CLI 项目 [{project_name}]：{len(messages)} 条消息')

    if not project_sections:
        logger.info(f'Claude CLI：当天（{target_date}）无对话记录')
        return ''

    result = '\n\n'.join(project_sections)
    logger.info(f'Claude CLI 合计：{len(project_sections)} 个项目，{len(result)} 字符')
    return result


# ─────────────────────────────────────────────
# 拼接输入内容
# ─────────────────────────────────────────────

def build_input(day_planner: str, clippings: str, claude_cli: str, max_chars: int) -> str:
    sections = []

    if day_planner:
        sections.append(f'## 📋 Day Planner 今日记录\n\n{day_planner}')

    if clippings:
        sections.append(f'## 📎 Claude Web 对话摘录 (Clippings)\n\n{clippings}')

    if claude_cli:
        sections.append(f'## 🖥️ Claude CLI 对话记录\n\n{claude_cli}')

    combined = '\n\n---\n\n'.join(sections)

    if len(combined) > max_chars:
        combined = combined[:max_chars] + '\n\n...(内容过长，已截断)'

    return combined


# ─────────────────────────────────────────────
# LLM 调用
# ─────────────────────────────────────────────

SYSTEM_PROMPT = """你是一个专业的每日学习总结助手，服务对象是一位电力系统行业的产品经理。

请根据以下今日原始内容，生成一份结构化的每日 AI 学习总结。要求：

## 总结要求
1. **问题解答**：从 Day Planner 中识别出"问题"和"待学习的小知识点"，逐一给出简明扼要的回答。回答必须结合具体的数据、例子或应用场景，不要泛泛而谈。
2. **Claude Web 对话摘要**：总结 Clippings 中的 Claude Web 对话内容，提炼核心知识点和结论。
3. **Claude CLI 工作摘要**：总结 CLI 对话中的编码/设计工作，提炼关键决策、解决的问题、学到的技术要点。
4. **今日收获**：用 3-5 条要点概括今天最有价值的学习内容。

## 输出格式
用 Markdown 格式输出，使用二级标题分节。语言风格：专业但不枯燥，像一位资深同事在帮你做复盘。

## Markdown 格式规范（严格遵守）
- **问题解答**：Q 行用四级标题（`####`），解答内容紧接在 Q 的下一行直接书写，不加"A："前缀，Q 与解答之间只换行不加空行，每组之间保留一个空行：
  ```
  #### Q：xxx
  xxx（解答内容直接书写，不加任何前缀）

  #### Q：xxx
  xxx（解答内容直接书写，不加任何前缀）
  ```
- **列表使用原则**：**只有当一级条目下有二级子项（`-`）时才使用列表**；只要没有二级子项，无论有几条、文中是否提到"X个方面/X点"，一律改为独立段落，不使用任何列表符号
- **列表层级**：最多两级，禁止三级及以上嵌套。一级必须用数字序号（`1.` `2.`），二级必须用 `-`，二级缩进 4 个空格。二级子项必须独立成行，不允许融入一级条目的文字中：
  ```
  1. 一级条目标题
      - 二级子项
      - 二级子项
  2. 一级条目标题
      - 二级子项
  ```
- **今日收获**：各条收获之间不加空行，连续段落展示；每段开头用一句加粗的总结句，后接具体说明；**禁止使用"首先""其次""最后""第一""第二"等序号性连接词**：
  ```
  **总结句。** 具体说明……
  **总结句。** 具体说明……
  **总结句。** 具体说明……
  ```
- **禁止使用"首先""其次""最后""第一""第二"等序号性过渡词**，无论在哪个章节，需要分层时直接用加粗总结句起段，或使用列表
- **列表位置**：列表只能出现在一个内容块（段落或章节）的末尾；列表之后不允许再跟正文段落
- **超过两级的内容**：不允许再缩进，直接在所属段落或二级条目的文字内用「；」「：」「（）」等标点区分层次
- **禁止在段落文字末尾直接跟随缩进列表**，如需列举必须将父级也写成列表项
- **段落间距**：每个独立段落、列表块、标题之间保留一个空行，不要连续空行；**段落内部（包括列表各条目之间）不加空行**
- **合理分段**：每个段落只表达一个完整意思，不要将多个不同逻辑点堆积在同一段落中；一段超过 5 行时须主动拆分"""


def call_llm(config: dict, user_content: str, logger: logging.Logger) -> str:
    provider = config.get('llm_provider', 'deepseek')
    llm_cfg = config.get('llm', {}).get(provider, {})

    api_key = llm_cfg.get('api_key', '')
    if not api_key or api_key.startswith('sk-xxx'):
        logger.error(f'LLM API key 未配置（provider: {provider}）')
        sys.exit(1)

    base_url = llm_cfg.get('base_url', '')
    model = llm_cfg.get('model', '')

    logger.info(f'调用 LLM：provider={provider}, model={model}')

    client = OpenAI(api_key=api_key, base_url=base_url)

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {'role': 'system', 'content': SYSTEM_PROMPT},
                {'role': 'user', 'content': user_content},
            ],
            temperature=0.3,
            max_tokens=4096,
        )
        result = resp.choices[0].message.content
        logger.info(f'LLM 调用成功，输出 {len(result)} 字符')
        return result
    except Exception as e:
        logger.error(f'LLM API 调用失败：{e}')
        sys.exit(1)


# ─────────────────────────────────────────────
# 写输出文件
# ─────────────────────────────────────────────

def write_output(
    output_dir: str,
    target_date: date,
    summary: str,
    day_planner_len: int,
    clippings_len: int,
    cli_len: int,
    logger: logging.Logger,
) -> Path:
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    date_str = target_date.strftime('%Y-%m-%d')
    filename = f'AI Daily-{target_date.strftime("%Y%m%d")}.md'
    out_path = out_dir / filename

    generated_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    if not summary:
        body = '> 今日无可总结的内容。'
    else:
        body = summary

    content = f"""---
date: {date_str}
type: ai-daily-summary
sources:
    day_planner: {day_planner_len} 字符
    clippings: {clippings_len} 字符
    claude_cli: {cli_len} 字符
generated_at: {generated_at}
---

# 📅 AI Daily Summary - {date_str}

{body}
"""

    out_path.write_text(content, encoding='utf-8')
    logger.info(f'输出文件写入完成：{out_path}')
    return out_path


# ─────────────────────────────────────────────
# 发布到微信公众号
# ─────────────────────────────────────────────

WECHAT_API_SCRIPT = Path.home() / '.claude/plugins/marketplaces/baoyu-skills/skills/baoyu-post-to-wechat/scripts/wechat-api.ts'


def _strip_frontmatter(content: str) -> str:
    """去掉 YAML frontmatter（--- ... ---）。"""
    if not content.startswith('---'):
        return content
    second = content.find('\n---', 3)
    if second == -1:
        return content
    return content[second + 4:].lstrip('\n')


def _resolve_bun() -> str:
    """返回可用的 bun 命令，找不到返回空字符串。"""
    if shutil.which('bun'):
        return 'bun'
    if shutil.which('npx'):
        return 'npx -y bun'
    return ''


def publish_to_wechat(
    out_path: Path,
    target_date: date,
    config: dict,
    logger: logging.Logger,
):
    wechat_cfg = config.get('wechat', {})
    if not wechat_cfg.get('enabled', False):
        return

    if not WECHAT_API_SCRIPT.exists():
        logger.error(f'baoyu-post-to-wechat 脚本不存在：{WECHAT_API_SCRIPT}')
        return

    bun = _resolve_bun()
    if not bun:
        logger.error('未找到 bun 或 npx，无法发布到微信公众号')
        return

    # 剥掉 frontmatter，写临时文件
    original = out_path.read_text(encoding='utf-8')
    body = _strip_frontmatter(original)

    with tempfile.NamedTemporaryFile(
        mode='w', suffix='.md', encoding='utf-8', delete=False
    ) as tmp:
        tmp.write(body)
        tmp_path = tmp.name

    try:
        title = f'AI Daily Summary - {target_date.strftime("%Y-%m-%d")}'
        theme = wechat_cfg.get('theme', 'default')
        cover = wechat_cfg.get('cover', '')

        cmd = bun.split() + [str(WECHAT_API_SCRIPT), tmp_path,
                              '--theme', theme,
                              '--title', title,
                              '--no-cite']
        if cover:
            cmd += ['--cover', cover]

        logger.info(f'发布到微信公众号：{" ".join(cmd)}')
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

        if result.returncode == 0:
            logger.info(f'微信公众号发布成功\n{result.stdout.strip()}')
        else:
            logger.error(f'微信公众号发布失败（exit {result.returncode}）\n{result.stderr.strip()}')
    except subprocess.TimeoutExpired:
        logger.error('微信公众号发布超时')
    except Exception as e:
        logger.error(f'微信公众号发布异常：{e}')
    finally:
        os.unlink(tmp_path)


# ─────────────────────────────────────────────
# 主流程
# ─────────────────────────────────────────────

def main():
    # 脚本所在目录作为工具目录
    tool_dir = Path(__file__).parent.resolve()
    config_path = tool_dir / 'config.yaml'
    log_path = tool_dir / 'ai_daily.log'

    logger = setup_logging(log_path)

    # 目标日期
    if len(sys.argv) >= 2:
        try:
            target_date = datetime.strptime(sys.argv[1], '%Y%m%d').date()
        except ValueError:
            logger.error(f'日期格式错误，应为 YYYYMMDD，实际为：{sys.argv[1]}')
            sys.exit(1)
    else:
        target_date = date.today()

    logger.info(f'======== AI Daily Summary 开始，目标日期：{target_date} ========')

    config = load_config(config_path)

    vault = config.get('vault', '/Users/shenni/obsidian')
    output_dir = config.get('output_dir', '/Users/shenni/obsidian/AI Daily')
    max_chars = config.get('max_input_chars', 60000)

    # 收集数据源
    day_planner = read_day_planner(vault, target_date, logger)
    clippings = read_clippings(vault, target_date, logger)
    claude_cli = read_claude_cli(target_date, logger)

    dp_len = len(day_planner)
    cl_len = len(clippings)
    cc_len = len(claude_cli)

    logger.info(f'数据源字符数 — Day Planner: {dp_len}, Clippings: {cl_len}, Claude CLI: {cc_len}')

    # 生成总结
    if dp_len == 0 and cl_len == 0 and cc_len == 0:
        logger.info('三个数据源全部为空，生成空报告')
        summary = ''
    else:
        user_content = build_input(day_planner, clippings, claude_cli, max_chars)
        summary = call_llm(config, user_content, logger)

    # 写入文件
    out_path = write_output(output_dir, target_date, summary, dp_len, cl_len, cc_len, logger)

    # 发布到微信公众号
    publish_to_wechat(out_path, target_date, config, logger)

    logger.info(f'======== 完成，输出：{out_path} ========')


if __name__ == '__main__':
    main()
