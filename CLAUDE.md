# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Purpose

A macOS-local Python automation tool that runs every weekday at 18:00 via crontab. It collects the day's work/learning data from three sources (Obsidian Day Planner, Obsidian Clippings, Claude CLI conversation history), sends it to an LLM, and writes a structured Markdown daily summary into an Obsidian vault. Optionally publishes the result as a draft to a WeChat Official Account.

## Running the Script

```bash
python3 ai_daily_summary.py             # run for today
python3 ai_daily_summary.py 20260402    # run for a specific date (YYYYMMDD)
```

Setup (first time):
```bash
bash setup.sh   # installs pip deps (openai, pyyaml) and registers the crontab entry
```

Dependencies (Python 3 only, no build step):
```bash
pip3 install openai pyyaml
```

## Architecture

The entire application is a single file: `ai_daily_summary.py` (~517 lines). Configuration is external via `config.yaml` (gitignored; use `config.yaml.example` as template).

### Execution Flow (`main()`)

1. Resolve `config.yaml` and `ai_daily.log` relative to the script's own directory
2. Parse optional `YYYYMMDD` date argument (defaults to today)
3. Load config → collect data from 3 sources → call LLM → write Obsidian Markdown → optionally publish to WeChat

### Data Sources

| Function | Source path | Filter mechanism |
|---|---|---|
| `read_day_planner()` | `{vault}/Day Planners/YYYY-MM-DD.md` | Exact filename match |
| `read_clippings()` | `{vault}/Clippings/*.md` | `os.stat().st_birthtime` (macOS file birth date) |
| `read_claude_cli()` | `~/.claude/projects/**/*.jsonl` | File `mtime` coarse filter + per-message `timestamp` ISO field |

All source readers are fault-tolerant: missing files/dirs log a warning and return empty string.

### LLM Integration

- Uses `openai` Python SDK with a custom `base_url` (compatible with DeepSeek and Kimi, both OpenAI-compatible APIs)
- Provider selected by `llm_provider` in config (`deepseek` or `kimi`)
- System prompt is hardcoded in `SYSTEM_PROMPT` constant (Chinese-language, instructs LLM as a daily study summary assistant for a power-systems product manager)
- Temperature: 0.3, max_tokens: 4096

### Output

- Writes `{output_dir}/AI Daily-YYYYMMDD.md` with YAML frontmatter recording source char counts and generation timestamp
- `output_dir` defaults to `/Users/shenni/obsidian/AI Daily`

### WeChat Publishing

- Guarded by `wechat.enabled` in config
- Calls an external TypeScript script at a hardcoded path: `~/.claude/plugins/marketplaces/baoyu-skills/skills/baoyu-post-to-wechat/scripts/wechat-api.ts` via `bun` (falls back to `npx -y bun`)
- WeChat credentials (`WECHAT_APP_ID`, `WECHAT_APP_SECRET`) live in `~/.baoyu-skills/.env`, not in this repo

## Configuration

`config.yaml` (gitignored) keys:
- `llm_provider`: `deepseek` or `kimi`
- `llm.deepseek` / `llm.kimi`: `api_key`, `base_url`, `model`
- `vault`: Obsidian vault root path
- `output_dir`: Where summary `.md` files are written
- `max_input_chars`: Max characters fed to LLM (default: 60,000)
- `wechat.enabled`: Boolean toggle
- `wechat.theme`: CSS theme for WeChat articles (`default`/`grace`/`simple`/`modern`)
- `wechat.cover`: Path to cover image

## Scheduling (macOS crontab)

The crontab entry fires weekdays at 18:00:
```
0 18 * * 1-5 cd "/Users/shenni/repository/auto-report-daily" && /usr/local/bin/python3 "...ai_daily_summary.py" >> ".../cron.log" 2>&1
```

`setup.sh` manages this entry idempotently. The `PATH` line in crontab must include the directory containing `npx`/`bun` for WeChat publishing to work in the restricted cron environment. macOS System Settings → Privacy → Full Disk Access must be granted to cron for Obsidian vault reads.

## Known Issues

- WeChat publishing returns `40164: invalid ip ... not in whitelist` when the machine's public IP changes — this is a WeChat developer console configuration issue (IP whitelist), not a code bug.
