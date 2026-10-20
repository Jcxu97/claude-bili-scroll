# 给 AI agent 看的说明

用户把这个仓库的链接发给你，说"帮我装这个"，就按下面的顺序做。不要跳步。

## 安装

1. 运行 `python --version`，确认 Python 是 3.11 以上。没有的话推荐装 [uv](https://docs.astral.sh/uv/)，它能自己拉 Python。
2. 克隆仓库，进入目录。
   ```
   git clone https://github.com/Jcxu97/claude-bili-scroll
   cd claude-bili-scroll
   ```
3. 运行 `cp config.example.toml config.toml`，然后问用户下面几件事，按回答填写。
   1. 用哪个 agent 跑（Claude Code / Codex / 别的），模型和思考强度
   2. 想看哪些题材（填 `[scroll] keywords`）
   3. 要不要自动评论 @ 主号。要的话问主号昵称，填 `[comment] at`。`enabled` 先留 `false`，第 7 步试运行满意了再改成 `true`
   4. 要不要回复 @、评论和私信。要的话问主号 UID，填 `[inbox] owner_uid`，再把 `enabled` 改成 `true`
   5. 人设用中性（`personas/neutral.md`）还是 Claude 大小姐（`personas/ojousama.md`）
4. 让用户准备一个 B 站小号，不要用主号。
5. 运行 `python run.py install`。它会建 `.venv`、装依赖，然后运行登录，让用户用小号的 App 扫码，确认时选"长期"。国内网络慢就先设环境变量 `PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple`。
6. `install` 接着跑 `doctor`，会真的调用一次 agent。有 `[fail]` 就按提示修好，再运行一次 `install`。全部 `[ok]` 以后，它会让 `serve` 在后台常驻运行，每天 12:00 以后刷一轮。开了收件箱的话，默认每 5 分钟查一次 @、回复和私信。Windows 上用管理员终端运行 `install`，后台任务才能开机就跑，不用等用户登录。
7. 用 `.venv` 里的 python 运行 `run.py --data data-trial once --dry-run` 试一轮（Windows 是 `.venv\Scripts\python`，macOS 和 Linux 是 `.venv/bin/python`）。它只写日报，让用户看一眼 `data-trial/out/` 里的日报满不满意。用户要自动评论的话，满意了再把 `[comment] enabled` 改成 `true`，不用重启，下一轮生效。
8. 用户要搬到另一台机器（比如常开的服务器），先在旧机器上运行 `python run.py schedule --remove`，再把 `config.toml` 和整个数据目录拷到新机器，数据目录换了位置就改 `[paths] data`，最后在新机器上运行 `python run.py install`。

## 不要做的事

1. 不要替用户打开自动评论或者收件箱。评论、回复和私信都是用用户的账号说话，必须用户自己点头。
2. 不要把 `data/` 里的任何东西提交到 git 或者发给别人。`credential.json` 是登录凭证，拿到它就能登录这个号。`agent.env` 里存着 agent 的 API 令牌。
3. 不要改 `bili_mcp/server.py` 里的工具放行名单逻辑（`BILI_MCP_TOOLS`）和私信的限制（`BILI_DM_TO`、`BILI_DM_OWNER`），那是限制 agent 能做什么的硬限制。

## 常见问题

1. 报 `-352` 是 B 站风控。不带 cookie 的请求会被拦，本项目已经在需要的地方带上了游客 cookie 或登录凭证。如果还是报，多半是凭证过期了，重新 `login`。
2. 很多视频被"因无字幕跳过"，是因为 B 站只给一部分视频生成 AI 字幕，接口读不到就只能跳过。
3. 评论发出去了但主号没收到 @，多半是新号或低等级号的评论被折叠了。日报末尾的"评论可见性检查"会告诉你别人能不能看到。
