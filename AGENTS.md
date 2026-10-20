# 给 AI agent 看的说明

用户把这个仓库的链接发给你，说"帮我装这个"，就按下面的顺序做。不要跳步。

## 安装

1. 运行 `python --version`，确认 Python 是 3.11 以上。没有的话推荐装 [uv](https://docs.astral.sh/uv/)，它能自己拉 Python。
2. 克隆仓库，进入目录，建虚拟环境。
   ```
   git clone https://github.com/Jcxu97/claude-bili-scroll
   cd claude-bili-scroll
   python -m venv .venv
   ```
   然后用 `.venv` 里的 pip 运行 `pip install -r requirements.txt`（Windows 是 `.venv\Scripts\pip`，macOS 和 Linux 是 `.venv/bin/pip`）。国内网络慢就加 `-i https://pypi.tuna.tsinghua.edu.cn/simple`。之后所有命令都用 `.venv` 里的 python 跑。
3. 运行 `cp config.example.toml config.toml`，然后问用户下面几件事，按回答填写。
   1. 用哪个 agent 跑（Claude Code / Codex / 别的），模型和思考强度
   2. 想看哪些题材（填 `[scroll] keywords`）
   3. 要不要自动评论 @ 主号。要的话问主号昵称，填 `[comment] at`，再把 `enabled` 改成 `true`
   4. 要不要回复 @ 和评论。要的话问主号 UID，填 `[inbox] owner_uid`，再把 `enabled` 改成 `true`
   5. 人设用中性（`personas/neutral.md`）还是 Claude 大小姐（`personas/ojousama.md`）
4. 让用户准备一个 B 站小号，不要用主号。然后运行 `python run.py login`，让用户用小号的 App 扫码，确认时选"长期"。
5. `python run.py doctor`，全部 `[ok]` 才往下走。
6. 先用 `python run.py --data data-trial once --dry-run` 试运行一次。它只写日报，不发评论。让用户看一眼 `data-trial/out/` 里的日报满不满意。
7. 用户满意了，`python run.py schedule` 装定时任务（默认每天 12:00 跑一轮，开了收件箱的话每 10 分钟查一次 @）。

## 不要做的事

1. 不要替用户打开自动评论或者收件箱。评论和回复都是用用户的账号公开说话，必须用户自己点头。
2. 不要把 `data/` 里的任何东西提交到 git 或者发给别人。`credential.json` 是登录凭证，拿到它就能登录这个号。
3. 不要改 `bili_mcp/server.py` 里的工具放行名单逻辑（`BILI_MCP_TOOLS`），那是限制 agent 能做什么的唯一一道硬限制。

## 常见问题

1. 报 `-352` 是 B 站风控。不带 cookie 的请求会被拦，本项目已经在需要的地方带上了游客 cookie 或登录凭证。如果还是报，多半是凭证过期了，重新 `login`。
2. 很多视频被"因无字幕跳过"，是因为 B 站只给一部分视频生成 AI 字幕，接口读不到就只能跳过。
3. 评论发出去了但主号没收到 @，多半是新号或低等级号的评论被折叠了。日报末尾的"评论可见性检查"会告诉你别人能不能看到。
