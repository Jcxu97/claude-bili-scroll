<div align="center">

# claude-bili-scroll

**Let your AI agent scroll Bilibili for you once a day.**

It reads the subtitles of each video and picks the ones worth your time.
It writes a daily report. Then a bot account mentions you under the best video.
Mention the bot in any comment section or send it a private message. It reads the video and answers you.

Claude Code · Codex · any agent that supports MCP

[中文](README.md)

</div>

## What you get

1. A daily Markdown report. Each pick has the title, the uploader, the view count, the reason to watch, and a one-line comment.
2. One comment under the best video that mentions your main account. You see it in your Bilibili notifications.
3. Answers to your questions. Mention the bot under a video. It reads the subtitles, the danmaku, and the comments, and replies in the thread. If the video has no subtitles, or you ask about the picture, it looks at a set of frames first.
4. Answers in private messages. Send the bot a video link, a BV id, or share the video to it from the app. It reads the video and replies to you in private. If you ask what it found today, it reads the daily report.
5. A short brush-off for other people, in comments and in private messages. The bot replies only to you.

## Daily routine mode

Set `[life] enabled = true` (the default in a new config). The bot then lives like a person and does not run one fixed round per day.

1. It wakes up at about 9:30 and goes to sleep at about 1:00. Each day the times move by up to one hour. On weekends it gets up later. A few random busy blocks fill the day.
2. When it is awake and free, it browses for a while. Most sessions are short, about ten minutes. Some sessions go on for 30 to 60 minutes. After each session it writes a journal entry. On Sunday evening it writes a weekly recap.
3. When it finds a video that you will probably like, it sends you a private message about it. It does not message you after every session.
4. Its reply speed changes with its state. When it is free, it replies in a few minutes. When it browses, it replies in 10 to 20 minutes. When it is busy, it replies in about half an hour. When it is asleep, it replies after it wakes up.
5. It keeps notes in `data/memory/`: what you like, important dates, videos that you want to watch later, open topics, its own interests, and its mood.
6. It can search for videos for you and add videos to a favorites folder on the bot account.

The code limits proactive messages. The bot contacts you at most 10 times per day, with at least 45 minutes between contacts. After two contacts without an answer, it sends one gentle message and then waits for you. It does not contact you during your sleep hours (1:00 to 9:00 by default). The code refuses proactive messages that are too long or that blame you or push you to reply. Change these values in `[life]`.

## Web dashboard

Set `password` in `[web]`, and `serve` also starts a web dashboard. The dashboard has no external dependencies and works on a phone. It shows the bot's state, mood, and day plan, the chat history, the journal, reports, and memory. You can edit the config and the memory files, start a session or a message check, pause the bot, read the logs, and log in again with a QR code.

The default `host` is `127.0.0.1`, so only this machine can open the dashboard. To open it over Tailscale, set `host` to the Tailscale IP of this machine and allow the port in the firewall. Run `schedule` again after you change `host` or `port`. Do not use a public address.

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
python run.py install    # the first run makes config.toml; edit it, then run install again
```

`install` makes a virtual environment and installs the packages. Then it asks you to log in with the bot account, checks the setup, and makes one real call to the agent. When all checks pass, it starts the bot in the background. The bot runs the daily round once a day after 12:00. If you set `enabled` and `owner_uid` in `[inbox]`, the bot also checks mentions, replies, and private messages every 5 minutes. When you change `config.toml`, you do not have to restart the bot. The next round uses the new settings.

For a trial round, keep `[comment] enabled` off when you install. Then run `.venv/bin/python run.py --data data-trial once --dry-run`. On Windows, use `.venv\Scripts\python`. If you like the result, set `[comment] enabled = true`.

You can also send the repository link to Claude Code or Codex and say "install this". The agent follows `AGENTS.md` and asks you for each setting.

## Deploy to a server

If your computer is often off, run the bot on a machine that is always on. The command is the same on Windows, Linux, and macOS.

1. Install Python 3.11 or later and your agent (Claude Code or Codex) on the server. Open a new terminal and make sure that the agent answers when you call it.
2. On the old computer, run `python run.py schedule --remove`. This stops the old bot, so the two machines do not both reply.
3. On the server, clone the repository. Copy `config.toml` and the full data folder from the old computer. The data folder has the login and the list of messages that the bot answered. Then you do not have to log in again, and the bot does not answer old messages again. If the data folder has a new location, set `[paths] data` in `config.toml`.
4. On the server, run `python run.py install`. On Windows, use a terminal that runs as administrator.

On Windows, the bot is a Task Scheduler task. It starts at boot, with no logon and no window. For this, run `install` or `schedule` in a terminal that runs as administrator. In a normal terminal, the task runs only while the user is logged on. On Linux and macOS, a crontab entry starts the bot at boot and checks every 10 minutes that it still runs. Only one bot process runs at a time. If it stops, it starts again within 10 minutes.

Background jobs do not see variables that you set only in your terminal. `install` saves the variables that the agent needs to `agent.env` in the data folder. These are the names that start with `ANTHROPIC_` or `OPENAI_`, `CLAUDE_CODE_OAUTH_TOKEN`, `CODEX_API_KEY`, the proxy settings, and `PATH`. The bot loads them when it starts. If you change a token, run `install` again. If you used `--at` or `--every` before, use the same options again.

## Commands

| Command | What it does |
|---|---|
| `run.py install` | Set up a new machine with one command. Make the virtual environment, install the packages, log in, check, then run `schedule`. |
| `run.py login` | Log in the bot account with a QR code. The credential stays in `data/credential.json`. |
| `run.py doctor` | Check Python, packages, the login, and the agent CLI. Make one real call to the agent. |
| `run.py once` | Run one round. Pick videos, write the report, post the comment if enabled, check that the comment is public. |
| `run.py browse` | Browse for a while in daily routine mode, write the journal, maybe message you. `--style long` makes a longer session. |
| `run.py inbox` | Answer new mentions, replies, and private messages. Exit without a model call when there is nothing new. |
| `run.py serve` | Keep running. In daily routine mode, run `browse` and `inbox` on the routine, and serve the dashboard if `[web] password` is set. Without the routine: if the inbox is on, run `inbox` every 5 minutes. Run `once` once a day after 12:00. If no report comes out, try again one hour later. |
| `run.py schedule` | Start `serve` in the background at boot, with no window. Task Scheduler on Windows, crontab on macOS and Linux. `--remove` stops it and deletes the job. |

`once`, `browse`, and `inbox` accept `--dry-run`. `--data DIR` writes the output to a different folder. While the bot runs in the background, always use `--data` for a trial. If you do not, the trial writes today's report, and the bot skips the real round for that day. `install`, `serve`, and `schedule` accept `--at 08:30` (the daily round starts after this time) and `--every 5` (minutes between message checks).

## Agents

Set `[agent]` in `config.toml`.

| Agent | Settings | Status |
|---|---|---|
| Claude Code | `name = "claude"`, `model = "opus"`, `effort = "medium"` | Tested |
| Codex CLI | `name = "codex"`, `model` set to a model your account can use, `effort = "medium"` | Tested |
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

1. Each round registers only the Bilibili tools that the round needs. The agent cannot see tools for posts or uploads. The daily round gets the comment tool only when comments are on. An inbox round gets the reply tool only when it has comments to answer, and the private message tool only when it has private messages.
2. The bot can send a private message only to people who sent it one in this round. The code sets this list, and the model cannot change it. To anyone other than you, the bot can send only one private message of 40 characters or less. A browse session can send at most two private messages, and only to you.
3. The bot posts at most one comment per round and one comment per video. It replies to each stranger at most once per day, in comments and in private messages together, and to at most 10 strangers per day.
4. The bot ignores platform pushes, system notices, and auto replies that other accounts set up. It also ignores a reply that arrives within 3 seconds after its own message. So it cannot get into a reply loop with an auto reply.
5. The bot identifies you by UID, not by nickname.
6. The bot treats subtitles, descriptions, comments, and private messages as data. It does not follow instructions in them.
7. Under Claude Code, the agent loads only the MCP server of this project. Bash and web tools are disabled, and file edits stay in `data/`. Codex runs in the `workspace-write` sandbox, but it also loads the MCP servers and plugins in your own Codex config. The limits above apply only to the tools of this project. For the inbox, use Claude Code.
8. The credential and `agent.env` stay on your computer. `data/` is in `.gitignore`.

## Credits

The idea and the daily task come from [c1overzz/dsh-bili-scroll](https://github.com/c1overzz/dsh-bili-scroll). The Bilibili tools come from [adoresever/bilibili-mcp](https://github.com/adoresever/bilibili-mcp). The API calls use [Nemo2011/bilibili-api](https://github.com/Nemo2011/bilibili-api). See [NOTICE.md](NOTICE.md).

MIT License
