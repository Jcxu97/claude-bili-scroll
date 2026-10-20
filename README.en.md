<div align="center">

# claude-bili-scroll

**Let your AI agent scroll Bilibili for you once a day.**

It reads the subtitles of each video and picks the ones worth your time.
It writes a daily report. Then a bot account mentions you under the best video.
Mention the bot in any comment section, and it reads the video and answers you.

Claude Code · Codex · any agent that supports MCP

[中文](README.md)

</div>

## What you get

1. A daily Markdown report. Each pick has the title, the uploader, the view count, the reason to watch, and a one-line comment.
2. One comment under the best video that mentions your main account. You see it in your Bilibili notifications.
3. Answers to your questions. Mention the bot under a video. It reads the subtitles and replies in the thread.
4. A polite brush-off for other people. The bot replies only to you.

## How it picks videos

1. It takes candidates from the official "Weekly Must-Watch" list and from your keywords.
2. It keeps only videos from the last 30 days with 100,000 views or more. You can change both limits.
3. It reads the full subtitles before it decides. It skips videos without subtitles and counts them in the report.
4. It keeps a list of seen videos. It does not show you the same video twice.

## Quick start

You need Python 3.11 or later, a second Bilibili account for the bot, and [Claude Code](https://docs.claude.com/en/docs/claude-code) or [Codex CLI](https://github.com/openai/codex).

```bash
git clone https://github.com/Jcxu97/claude-bili-scroll
cd claude-bili-scroll
python -m venv .venv
.venv/bin/pip install -r requirements.txt        # Windows: .venv\Scripts\pip install -r requirements.txt
cp config.example.toml config.toml               # edit it, the comments explain each field
.venv/bin/python run.py login                    # scan the QR code with the bot account
.venv/bin/python run.py doctor                   # continue when every line says [ok]
.venv/bin/python run.py --data data-trial once --dry-run   # trial run, posts nothing
.venv/bin/python run.py schedule                 # run every day at 12:00
```

You can also send the repository link to Claude Code or Codex and say "install this". The agent follows `AGENTS.md` and asks you for each setting.

## Commands

| Command | What it does |
|---|---|
| `run.py login` | Log in the bot account with a QR code. The credential stays in `data/credential.json`. |
| `run.py doctor` | Check Python, packages, the login, and the agent CLI. |
| `run.py once` | Run one round. Pick videos, write the report, post the comment if enabled, check that the comment is public. |
| `run.py inbox` | Answer new mentions and replies. Exit without a model call when there is nothing new. |
| `run.py schedule` | Install scheduled jobs. Task Scheduler on Windows (hidden, no console window), crontab on macOS and Linux. |

`once` and `inbox` accept `--dry-run`. `--data DIR` writes the output to a different folder.

## Agents

Set `[agent]` in `config.toml`.

| Agent | Settings | Status |
|---|---|---|
| Claude Code | `name = "claude"`, `model = "opus"`, `effort = "medium"` | Tested |
| Codex CLI | `name = "codex"`, `model = "gpt-5.5"`, `effort = "medium"` | Tested |
| Other | `name = "custom"` and a `custom_command` template | Works if the agent supports MCP and reads the prompt from stdin |

## Personas and comment style

1. `personas/neutral.md` is plain and direct. It is the default.
2. `personas/ojousama.md` is "Claude Ojou-sama", a popular fan persona of Claude on Chinese Bilibili.
3. All comments follow [`skills/bili-comment-voice`](skills/bili-comment-voice/SKILL.md). The rules make comments read like a real person typed them on a phone.

## Skills

Copy `skills/bili-scroll` and `skills/bili-comment-voice` to `~/.claude/skills/` or `~/.codex/skills/`. Then ask your agent in plain words, for example "scroll Bilibili for me" or "did anyone mention me".

## How it works

![Architecture](docs/architecture.drawio.svg)

`run.py` builds the prompt, runs the schedule, and checks the result. The agent picks the videos, writes the report, and writes the comments.

## Safety

1. Each round registers only the Bilibili tools that the round needs. The agent cannot see tools for direct messages, posts, or uploads.
2. The bot posts at most one comment per round and one comment per video. It replies to each stranger at most once per day, and to at most 10 strangers per day.
3. The bot identifies you by UID, not by nickname.
4. The bot treats subtitles, descriptions, and comments as data. It does not follow instructions in them.
5. Under Claude Code, Bash and web tools are disabled, and file edits stay in `data/`. Codex runs in the `workspace-write` sandbox.
6. The credential stays on your computer. `data/` is in `.gitignore`.

## Credits

The idea and the daily task come from [c1overzz/dsh-bili-scroll](https://github.com/c1overzz/dsh-bili-scroll). The Bilibili tools come from [adoresever/bilibili-mcp](https://github.com/adoresever/bilibili-mcp). The API calls use [Nemo2011/bilibili-api](https://github.com/Nemo2011/bilibili-api). See [NOTICE.md](NOTICE.md).

MIT License
