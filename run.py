#!/usr/bin/env python3
"""claude-bili-scroll: let your AI agent scroll Bilibili for you and keep you company.

Commands:
  install   set up .venv, log in, check everything, then run schedule (one command for a new machine)
  login     scan a QR code with the Bilibili app to log in the bot account
  doctor    check Python, login, the agent CLI, and one real agent call
  once      run one daily round: pick videos, write the report, maybe comment
  inbox     answer new @ mentions, replies and private messages (exits early when there is nothing new)
  browse    browse for a while, keep a journal, maybe share a video with the owner
  serve     stay running: browse and check messages on a daily routine, and serve the web page
  schedule  start serve at logon and keep it alive (Task Scheduler on Windows, crontab elsewhere)
"""
import argparse
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

if sys.version_info < (3, 11):
    sys.exit(f"需要 Python 3.11 以上，当前是 {sys.version.split()[0]}")
import tomllib  # noqa: E402

import life  # noqa: E402

ROOT = Path(__file__).resolve().parent
SERVER = ROOT / "bili_mcp" / "server.py"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
      "Referer": "https://www.bilibili.com/"}

DEFAULTS = {
    "agent": {"name": "claude", "model": "", "effort": "medium", "custom_command": []},
    "scroll": {"max_picks": 5, "min_play": 100000, "days": 30, "weekly_hot": True,
               "keywords": ["AI工具", "编程", "数码评测", "知识科普", "生活技巧", "纪录片"],
               "niche_keywords": [], "niche_min_play": 10000},
    "comment": {"enabled": False, "at": "", "max_per_run": 1},
    "inbox": {"enabled": False, "owner_uid": 0, "max_stranger_replies_per_day": 10},
    "persona": {"file": "personas/neutral.md"},
    "paths": {"data": "data"},
    "life": {"enabled": False, "wake": "09:30", "sleep": "01:00", "weekend_shift": 60, "owner_quiet": ["01:00", "09:00"],
             "max_contacts_per_day": 10, "min_gap_minutes": 45, "favorites": "给主号的", "daily_report": False},
    "web": {"host": "127.0.0.1", "port": 8788, "password": ""},
}
SCROLL_TOOLS = ["bili_search", "bili_weekly_hot", "bili_subtitle", "bili_comments", "bili_video_info", "bili_check_credential"]
INBOX_TOOLS = ["bili_search", "bili_subtitle", "bili_danmaku", "bili_frames", "bili_comments", "bili_video_info",
               "bili_check_credential", "bili_favorite_add"]
BROWSE_TOOLS = SCROLL_TOOLS + ["bili_danmaku", "bili_frames", "bili_favorite_add"]
# Path rules hold only while the user's own settings stay out: one bare "Edit" there allows every path.
# So every Claude Code job runs with --setting-sources "". It also keeps out every CLAUDE.md, this repo's too.
CLAUDE_FILE_TOOLS = ["Read(./**)", "Edit(./**)"]
# Built-in tools that a bot round never needs. Some of them reach other sessions or the desktop.
CLAUDE_LOCKED = ("Bash PowerShell WebFetch WebSearch Agent SendMessage PushNotification CronCreate CronDelete Monitor "
                 "TaskStop EnterWorktree DesignSync NotebookEdit")
# The agent works in the data folder. It must not read the login or the tokens, nor rewrite the files that the
# limits are counted from. Read rules also cover Grep and Glob; Edit rules cover every tool that writes.
PROTECTED = " ".join([f"Read(./{f})" for f in ("credential.json", "agent.env")] +
                     [f"Edit(./{f})" for f in ("credential.json", "agent.env", "chat.jsonl", "inbox-state.json",
                                               "life.json")])


def load_config(path):
    cfg = {k: dict(v) for k, v in DEFAULTS.items()}
    p = Path(path)
    if p.exists():
        with open(p, "rb") as f:
            for section, values in tomllib.load(f).items():
                cfg.setdefault(section, {}).update(values)
    return cfg


def resolve(p):
    p = Path(p).expanduser()
    return p if p.is_absolute() else ROOT / p


def cred_file(cfg):
    return resolve(cfg["paths"]["data"]) / "credential.json"


def load_cred(cfg):
    f = cred_file(cfg)
    if not f.exists():
        sys.exit(f"还没登录。先运行：python run.py login（凭证会存到 {f}）")
    return json.loads(f.read_text(encoding="utf-8"))


def read_md(p):
    text = Path(p).read_text(encoding="utf-8")
    if text.startswith("---"):
        text = text.split("---", 2)[2]
    return text.strip()


def owner_name(cfg):
    return cfg["comment"]["at"] or "主人"


def play_rules(s):
    rules = [f"播放量门槛：{s['min_play']}，只看近 {s['days']} 天发布的"]
    if s["niche_keywords"]:
        rules.append(f"冷门题材的播放量门槛：{s['niche_min_play']}（{'、'.join(s['niche_keywords'])}）")
    return rules


def build_prompt(cfg, task, dry_run, messages=None, ctx=None):
    """Return (prompt, tools). The persona and the voice skill are appended to every task.

    ctx can add "params" (lines for the parameter list), "parts" (whole sections) and "tools".
    """
    ctx = ctx or {}
    persona = read_md(resolve(cfg["persona"]["file"])).replace("{owner}", owner_name(cfg))
    parts = [read_md(ROOT / "prompts" / f"{task}.md"), persona,
             read_md(ROOT / "skills" / "bili-comment-voice" / "SKILL.md")]
    params = [f"今天：{date.today().isoformat()}，星期{'一二三四五六日'[date.today().weekday()]}"]
    tools = []
    if task == "scroll":
        s, c = cfg["scroll"], cfg["comment"]
        tools = list(SCROLL_TOOLS)
        comment_on = c["enabled"] and c["at"] and not dry_run
        params += [f"关键词：{'、'.join(s['keywords'])}",
                   f"每周必看：{'开' if s['weekly_hot'] else '关'}",
                   *play_rules(s),
                   f"每天最多挑 {s['max_picks']} 条",
                   f"评论：{'开' if comment_on else '关'}，主号昵称 {c['at'] or '未设置'}，每轮最多 {c['max_per_run']} 条"]
        if comment_on:
            tools.append("bili_reply")
    elif task == "inbox":
        channels = {m.get("channel", "comment") for m in messages or []}
        tools = [t for t in INBOX_TOOLS if not (dry_run and t == "bili_favorite_add")]
        if not dry_run:
            tools += [t for ch, t in (("comment", "bili_reply"), ("dm", "bili_send_message")) if ch in channels]
        params.append(f"主号昵称：{owner_name(cfg)}")
        parts.append("## 消息\n\n```json\n" + json.dumps(messages or [], ensure_ascii=False, indent=1) + "\n```")
    tools += [t for t in ctx.get("tools", []) if t not in tools]
    params += ctx.get("params", [])
    parts += ctx.get("parts", [])
    if dry_run:
        params.append("试运行：不发评论，不发私信，不收藏，把拟好的内容写进记录，记忆文件也不要改。")
    params.append("工作目录就是当前目录，所有文件都写在这里。")
    parts.append("## 这一轮的参数\n\n" + "\n".join(f"{i}. {p}" for i, p in enumerate(params, 1)))
    return "\n\n".join(parts) + "\n", tools


MEMORY_FILES = ("owner.md", "topics.md", "interests.md", "mood.txt")


def memory_part(workspace):
    out = []
    for name in MEMORY_FILES:
        p = workspace / "memory" / name
        text = p.read_text(encoding="utf-8").strip() if p.exists() else ""
        # owner.md starts with what the owner likes, so cut its end. The other files add new lines at the end.
        text = text[:6000] if name == "owner.md" else text[-3000:]
        out.append(f"### memory/{name}\n\n{text or '（还是空的）'}")
    return "## 你的记忆（工作目录下的 memory/，按 prompt 里写的规则自己维护）\n\n" + "\n\n".join(out)


def chat_part(chat, cfg, n=20):
    names = {"owner": owner_name(cfg), "bot": "你"}
    lines = [f"{datetime.fromtimestamp(e['t']):%m-%d %H:%M} {names.get(e.get('who')) or e.get('from') or '陌生人'}"
             f"（{'私信' if e.get('channel') == 'dm' else '评论'}）：{str(e.get('text', ''))[:150]}" for e in chat[-n:]]
    return "## 最近的聊天（旧的在上面）\n\n" + ("\n".join(lines) or "（还没有）")


def mcp_server_spec(cfg, tools, workspace, dm_to=(), extra=None):
    return {"command": sys.executable, "args": ["-I", str(SERVER)],
            "env": {"BILI_MCP_TOOLS": ",".join(tools), "BILI_CREDENTIAL_FILE": str(cred_file(cfg)),
                    "BILI_FRAMES_DIR": str(workspace), "BILI_DM_TO": ",".join(map(str, dm_to)),
                    "BILI_DM_OWNER": str(int(cfg["inbox"]["owner_uid"] or 0)), "PYTHONIOENCODING": "utf-8",
                    "BILI_CHAT_LOG": str(workspace / "chat.jsonl"), "BILI_FAV_TITLE": cfg["life"]["favorites"],
                    **(extra or {})}}


def agent_command(cfg, workspace, mcp_json, prompt_file, tools, dm_to=(), extra=None):
    a = cfg["agent"]
    name, model, effort = a["name"], a.get("model", ""), a.get("effort", "")
    if name == "claude":
        allowed = [f"mcp__bili__{t}" for t in tools] + CLAUDE_FILE_TOOLS
        cmd = ["claude", "-p", "--mcp-config", str(mcp_json), "--strict-mcp-config", "--setting-sources", "",
               "--permission-mode", "default", "--allowedTools", " ".join(allowed),
               "--disallowedTools", CLAUDE_LOCKED + " " + PROTECTED]
        cmd += ["--model", model] if model else []
        cmd += ["--effort", effort] if effort else []
        return cmd
    if name == "codex":
        spec = mcp_server_spec(cfg, tools, workspace, dm_to, extra)
        env = "{" + ",".join(f"{k}={json.dumps(v)}" for k, v in spec["env"].items()) + "}"
        cmd = ["codex", "exec", "--skip-git-repo-check", "-s", "workspace-write", "-C", str(workspace),
               "-c", f"mcp_servers.bili.command={json.dumps(spec['command'])}",
               "-c", f"mcp_servers.bili.args={json.dumps(spec['args'])}",
               "-c", f"mcp_servers.bili.env={env}",
               "-c", 'mcp_servers.bili.default_tools_approval_mode="approve"']
        cmd += ["-m", model] if model else []
        cmd += ["-c", f"model_reasoning_effort={json.dumps(effort)}"] if effort else []
        return cmd + ["-"]
    if name == "custom":
        if not a.get("custom_command"):
            sys.exit("agent.name = custom 时必须在 config.toml 里写 custom_command")
        fill = {"mcp_config": str(mcp_json), "prompt_file": str(prompt_file), "workspace": str(workspace)}
        return [part.format(**fill) for part in a["custom_command"]]
    sys.exit(f"不认识的 agent：{name}（可选 claude / codex / custom）")


def agent_env(cfg):
    """Claude Code also takes model and proxy settings from the env block of the user's settings.json. Jobs skip
    that file (--setting-sources ""), so copy those variables over. They win, as they do in Claude Code."""
    env = dict(os.environ)
    if cfg["agent"]["name"] == "claude":
        f = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "settings.json"
        try:
            more = json.loads(f.read_text(encoding="utf-8")).get("env") or {}
        except (OSError, ValueError, AttributeError):
            more = {}
        env.update({k: str(v) for k, v in more.items()
                    if (k.startswith(AGENT_ENV_PREFIXES) or k.upper() in AGENT_ENV_NAMES) and k.upper() != "PATH"})
    return env


def run_agent(cfg, workspace, task, dry_run, messages=None, ctx=None, extra=None, dm_to=None):
    prompt, tools = build_prompt(cfg, task, dry_run, messages, ctx)
    if dm_to is None:
        dm_to = sorted({m["mid"] for m in messages or [] if m.get("channel") == "dm"})
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "logs").mkdir(exist_ok=True)
    tag = task + ("-dry" if dry_run else "")
    prompt_file = workspace / f".prompt-{tag}.md"
    prompt_file.write_text(prompt, encoding="utf-8")
    # Each task gets its own file: a browse round and an inbox check can run at the same time.
    mcp_json = workspace / f".mcp-{tag}.json"
    spec = mcp_server_spec(cfg, tools, workspace, dm_to, extra)
    mcp_json.write_text(json.dumps({"mcpServers": {"bili": spec}}, indent=2), encoding="utf-8")
    cmd = agent_command(cfg, workspace, mcp_json, prompt_file, tools, dm_to, extra)
    exe = shutil.which(cmd[0])
    if not exe:
        sys.exit(f"找不到 {cmd[0]}。先装好这个 agent 的命令行工具，并确认它在 PATH 里。")
    log = workspace / "logs" / f"{date.today().isoformat()}.log"
    with open(log, "a", encoding="utf-8") as f:
        f.write(f"\n=== {datetime.now():%H:%M:%S} {task}{' dry-run' if dry_run else ''} via {cfg['agent']['name']}\n")
        p = subprocess.Popen([exe] + cmd[1:], cwd=workspace, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", env=agent_env(cfg))
        p.stdin.write(prompt)
        p.stdin.close()
        for line in p.stdout:
            print(line, end="")
            f.write(line)
        rc = p.wait()
        f.write(f"=== exit {rc}\n")
    return rc


def http_json(url, cookie=None):
    headers = dict(UA, **({"Cookie": cookie} if cookie else {}))
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=15) as r:
        return json.loads(r.read().decode("utf-8")), r.headers.get_all("Set-Cookie") or []


def guest_cookie():
    # Anonymous requests to the reply API get -352 (risk control). A fresh guest buvid3 passes and carries no login.
    return "buvid3=" + http_json("https://api.bilibili.com/x/frontend/finger/spi")[0]["data"]["b_3"]


QR_API = "https://passport.bilibili.com/x/passport-login/web/qrcode/"


def login_start():
    """Return (url to put in the QR code, key to poll with)."""
    d = http_json(QR_API + "generate?source=main-fe-header")[0]["data"]
    return d["url"], d["qrcode_key"]


def login_poll(cfg, key):
    """Return "ok" (credential saved), "expired" or "wait"."""
    from http.cookies import SimpleCookie
    body, cookies = http_json(QR_API + f"poll?qrcode_key={key}&source=main-fe-header")
    code = body["data"]["code"]
    if code == 86038:
        return "expired"
    if code != 0:
        return "wait"
    # bilibili_api's QrCodeLogin reads SESSDATA from data.url, which is empty now. It is in Set-Cookie.
    jar = SimpleCookie()
    for c in cookies:
        jar.load(c)
    cred = {"sessdata": jar["SESSDATA"].value, "bili_jct": jar["bili_jct"].value,
            "dedeuserid": jar["DedeUserID"].value, "buvid3": guest_cookie().split("=", 1)[1]}
    cred_file(cfg).parent.mkdir(parents=True, exist_ok=True)
    tmp = cred_file(cfg).with_suffix(".tmp")
    tmp.write_text(json.dumps(cred), encoding="utf-8")
    os.replace(tmp, cred_file(cfg))
    return "ok"


def cmd_login(cfg):
    import qrcode
    url, key = login_start()
    qr = qrcode.QRCode(border=1)
    qr.add_data(url)
    qr.print_ascii(invert=True)
    png = cred_file(cfg).with_name("login-qrcode.png")
    png.parent.mkdir(parents=True, exist_ok=True)
    qrcode.make(url).save(png)
    if sys.platform == "win32":
        os.startfile(png)
    elif sys.platform == "darwin":
        subprocess.run(["open", png])
    print(f"用小号的 B 站 App 扫上面的码（图片也存在 {png}），确认时选“长期”。180 秒内有效。")
    try:
        for _ in range(90):
            time.sleep(2)
            got = login_poll(cfg, key)
            if got == "expired":
                sys.exit("二维码过期了，重新运行 python run.py login")
            if got == "ok":
                print(f"登录成功，UID {load_cred(cfg)['dedeuserid']}。凭证只存在本机：{cred_file(cfg)}")
                return 0
        sys.exit("等太久了，重新运行 python run.py login")
    finally:
        png.unlink(missing_ok=True)


def comment_rows(seen_text, day):
    return re.findall(rf"评论 {day} (BV\w{{10}}) rpid=(\d+)", seen_text)


def today_comments(workspace, day):
    seen = workspace / "seen.md"
    return comment_rows(seen.read_text(encoding="utf-8"), day) if seen.exists() else []


def verify_comments(rows, target):
    """A shadow-hidden comment is visible only to its author and sends no @ notification. Check as a guest."""
    lines = []
    for bv, rpid in rows:
        try:
            aid = http_json(f"https://api.bilibili.com/x/web-interface/view?bvid={bv}")[0]["data"]["aid"]
            j = http_json(f"https://api.bilibili.com/x/v2/reply/main?type=1&oid={aid}&mode=2&next=0&ps=20", guest_cookie())[0]
            if j.get("code") != 0:
                raise RuntimeError(f"code {j.get('code')}")
            found = any(str(r.get("rpid")) == rpid for r in ((j.get("data") or {}).get("replies") or []))
            lines.append(f"- {bv} rpid={rpid}：" + ("未登录也能看到，@ 通知应该已送达" if found else
                                                   "未登录时在最新 20 条里没查到，可能被折叠或在审核，@ 通知可能没送达"))
        except Exception as e:
            lines.append(f"- {bv} rpid={rpid}：检查失败（{type(e).__name__}: {e}）")
    if lines:
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "a", encoding="utf-8") as f:
            f.write("\n\n## 评论可见性检查\n\n" + "\n".join(lines) + "\n")
        print("\n".join(lines))


def parse_notice(n):
    """Turn one @ or reply notification into a message for the agent, or None if it is not a video comment."""
    it = n.get("item") or {}
    if it.get("business_id") != 1 or not it.get("source_id"):
        return None
    m = re.search(r"BV\w{10}", it.get("uri", "") + " " + it.get("native_uri", ""))
    if not m:
        return None
    user = n.get("user") or {}
    rpid = int(it["source_id"])
    return {"id": rpid, "channel": "comment", "rpid": rpid, "root": int(it.get("root_id") or rpid),
            "bvid": m.group(0), "title": it.get("title", ""), "mid": int(user.get("mid") or 0),
            "from": user.get("nickname", ""), "content": it.get("source_content", ""),
            "context": it.get("target_reply_content", ""), "time": int(n.get("at_time") or n.get("reply_time") or 0)}


# msg_source of private messages that Bilibili sends by itself: pushes and notices (5, 6), the UP-side
# auto replies on follow, on message and on keyword (7 to 9), and the fan-club and system prompts after that.
# A message that arrives within 3 seconds after one of ours is also treated as an auto reply, in case of new codes.
AUTO_SOURCES = {5, 6, 7, 8, 9, 10, 11, 12, 13, 16, 17, 18, 19}


def parse_dm(m, self_mid, bot_times=()):
    """Turn one private message into a message for the agent, or None for ours, automatic ones and notices."""
    sender, t = int(m.get("sender_uid") or 0), int(m.get("timestamp") or 0)
    if sender in (0, self_mid) or m.get("msg_type") not in (1, 7) or m.get("msg_source") in AUTO_SOURCES:
        return None
    if any(0 <= t - b <= 3 for b in bot_times):
        return None
    try:
        body = json.loads(m.get("content") or "{}")
    except ValueError:
        body = {}
    body = body if isinstance(body, dict) else {}
    card = m["msg_type"] == 7
    # Articles, live rooms and posts are shared as cards too. Only source 5 is a video.
    video = not card or body.get("source") in (None, 5)
    title = str(body.get("title", "")) if card else ""
    text = (f"（分享了视频《{title}》）" if video else f"（分享了《{title}》）") if card else str(body.get("content", ""))
    found = re.search(r"BV[0-9A-Za-z]{10}", json.dumps(body, ensure_ascii=False))
    av = re.search(r"(?<![a-z])av(\d{2,16})(?!\d)", text, re.I)
    aid = int(body["id"]) if card and str(body.get("id", "")).isdigit() else (int(av.group(1)) if av else 0)
    if not found and video and 0 < aid < 1 << 51:
        from bilibili_api import aid2bvid
        bvid = aid2bvid(aid)
    else:
        bvid = found.group(0) if found else ""
    return {"id": f"dm{m.get('msg_key')}", "channel": "dm", "bvid": bvid, "title": title, "mid": sender,
            "from": f"UID {sender}", "content": text, "context": "", "time": t}


def short_link_bvid(text):
    """The app's "copy link" gives a b23.tv short link. Follow the redirect to find the BV id."""
    m = re.search(r"https?://b23\.tv/[0-9A-Za-z]+", text)
    if not m:
        return ""
    try:
        with urllib.request.urlopen(urllib.request.Request(m.group(0), headers=UA), timeout=10) as r:
            url = r.geturl()
    except urllib.error.HTTPError as e:
        url = e.geturl()  # the video page can refuse a script (412), but its address already has the BV id
    except Exception:
        return ""
    found = re.search(r"BV[0-9A-Za-z]{10}", url)
    return found.group(0) if found else ""


def select_messages(notices, state, self_mid, owner_uid, stranger_limit, today, since):
    """Pick what the agent should answer. Mutates state. The owner is matched by UID, never by nickname."""
    if state.get("day") != today:
        state.update(day=today, strangers=[])
    handled = dict.fromkeys(state.get("handled", []))
    todo = []
    for msg in notices:
        if not msg or msg["id"] in handled or msg["mid"] == self_mid or msg["time"] < since:
            continue
        handled[msg["id"]] = None
        if msg["mid"] == owner_uid:
            todo.append(dict(msg, kind="owner"))
        elif msg["mid"] not in state["strangers"] and len(state["strangers"]) < stranger_limit:
            state["strangers"].append(msg["mid"])
            todo.append(dict(msg, kind="stranger"))
    state["handled"] = list(handled)[-1000:]
    return todo


async def fetch_dms(c, state, self_mid):
    from bilibili_api import session
    if "dm_ts" not in state:
        # First run on this machine: start from now, so old private messages are not answered again.
        state["dm_ts"] = int(time.time() * 1_000_000)
        return []
    since_s, out = state["dm_ts"] // 1_000_000, []
    for s in ((await session.new_sessions(c, state["dm_ts"])) or {}).get("session_list") or []:
        state["dm_ts"] = max(state["dm_ts"], int(s.get("session_ts") or 0))
        if (s.get("session_type") or 1) != 1:
            continue  # 2 is a fan-club group chat
        msgs = ((await session.fetch_session_msgs(s["talker_id"], c, 1)) or {}).get("messages") or []
        bot_times = [int(m.get("timestamp") or 0) for m in msgs if int(m.get("sender_uid") or 0) == self_mid]
        for m in reversed(msgs):  # the API gives the newest first
            try:
                dm = parse_dm(m, self_mid, bot_times) if int(m.get("timestamp") or 0) >= since_s else None
            except Exception as e:  # one odd message must not stop the inbox on every round
                print(f"跳过一条读不懂的私信：{type(e).__name__}: {e}")
                dm = None
            if dm and not dm["bvid"]:
                dm["bvid"] = short_link_bvid(dm["content"])
            out.append(dm)
    return out


async def fetch_notices(cred, state, self_mid):
    from bilibili_api import Credential, session
    c = Credential(**cred)
    out = []
    for fn in (session.get_at, session.get_replies):
        out += [parse_notice(n) for n in ((await fn(credential=c)).get("items") or [])]
    return out + await fetch_dms(c, state, self_mid)


def cmd_inbox(cfg, workspace, dry_run, note=""):
    owner = int(cfg["inbox"]["owner_uid"] or 0)
    if not owner:
        sys.exit("先在 config.toml 的 [inbox] 里填 owner_uid（主号 UID）")
    cred = load_cred(cfg)
    lock = single_instance(workspace / "inbox.lock")
    if not lock:
        print("另一个 inbox 正在处理消息，这次先不查。")
        return 0
    state_file = workspace / "inbox-state.json"
    state = json.loads(state_file.read_text(encoding="utf-8")) if state_file.exists() else {}
    since, self_mid = int(time.time()) - 2 * 86400, int(cred["dedeuserid"])
    todo = select_messages(asyncio.run(fetch_notices(cred, state, self_mid)), state, self_mid, owner,
                           cfg["inbox"]["max_stranger_replies_per_day"], date.today().isoformat(), since)
    if not todo:
        print("没有新的 @、回复或私信。")
        write_json(state_file, state)
        return 0
    for m in todo:
        if m["kind"] == "owner" and m["channel"] == "dm":
            m["from"] = owner_name(cfg)
    print(f"有 {len(todo)} 条要处理：" + "、".join(
        f"{m['from']}（{m['kind']}，{'私信' if m['channel'] == 'dm' else '评论'}）" for m in todo))
    chat_file = workspace / "chat.jsonl"
    ctx = {"params": [f"你现在的状态：{note}"] if note else [],
           "parts": [memory_part(workspace), chat_part(life.read_chat(chat_file), cfg)]}
    # Save before the agent runs, so a kill halfway cannot make it answer the same messages again.
    # A failed run also counts as handled: retrying every few minutes would look like spam.
    if not dry_run:
        write_json(state_file, state)
        for m in todo:
            # Local time, like the bot's own entries: Bilibili's clock and ours can differ by minutes.
            life.append_chat(chat_file, {"t": int(time.time()), "sent": m["time"], "who": m["kind"], "mid": m["mid"],
                                         "from": m["from"], "channel": m["channel"], "text": m["content"],
                                         "bvid": m["bvid"], "title": m["title"]})
    extra = {"BILI_DM_KIND": "reply", "BILI_REPLY_MAX": "0", "BILI_SESSION": f"inbox-{int(time.time())}",
             "BILI_REPLY_TO": ",".join(str(m["rpid"]) for m in todo if m["channel"] == "comment")}
    return run_agent(cfg, workspace, "inbox", dry_run, todo, ctx, extra)


def write_json(path, data):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def cmd_once(cfg, workspace, dry_run):
    load_cred(cfg)
    day = date.today().isoformat()
    extra = {"BILI_REPLY_MAX": str(int(cfg["comment"]["max_per_run"])), "BILI_REPLY_TO": "",
             "BILI_SESSION": f"once-{int(time.time())}"}
    rc = run_agent(cfg, workspace, "scroll", dry_run, extra=extra)
    report = workspace / "out" / f"{day}.md"
    # serve treats an existing report as done, so do not create one just for the check
    verify_comments(today_comments(workspace, day), report if report.exists() else workspace / "journal" / f"{day}.md")
    return rc


STYLES = {"short": "随手刷几条，十分钟上下，看三到六个视频，没意思就早点停",
          "long": "今天兴致好，可以连着刷半小时到一小时，看到想停就停，最多一小时"}


def browse_context(cfg, workspace, style, dry_run, now):
    """Everything one browse round needs to know: how long, may it message the owner, may it comment."""
    owner, c, s = int(cfg["inbox"]["owner_uid"] or 0), cfg["comment"], cfg["scroll"]
    # 60 days, so the "wait for the owner after a nudge" rule does not run out after two weeks of silence
    chat = life.read_chat(workspace / "chat.jsonl", days=60)
    # Owner answers reach chat.jsonl only through the inbox. Without it every share would look unanswered.
    mode, why = (life.proactive(chat, cfg["life"], now) if owner and cfg["inbox"]["enabled"]
                 else (None, "收件箱没开或者没填主号 UID"))
    day0 = datetime.combine(date.fromtimestamp(now), datetime.min.time()).timestamp()
    posted = sum(e["t"] >= day0 and e.get("who") == "bot" and e.get("kind") == "comment" and not e.get("reply_to")
                 for e in chat)
    comment_ok = bool(c["enabled"] and c["at"]) and posted < int(c["max_per_run"])
    t = datetime.fromtimestamp(now)
    params = [f"现在是 {t:%H:%M}", f"这次怎么刷：{STYLES[style]}",
              {"share": "私信主号：可以。有想分享的视频或者想接着聊的话才发，最多 2 条，没有就不发",
               "nudge": "私信主号：轻轻的问候。主号连着两次没回你，可以发一条软一点的问候（60 字以内），也可以不发",
               None: f"私信主号：这一轮不发（{why}）"}[mode],
              f"评论：{'可以在最值得的一条下面发 1 条 @ 主号' if comment_ok else '这一轮不发'}，主号昵称 {c['at'] or '未设置'}",
              f"感兴趣的方向（只是参考，你自己的兴趣在记忆里）：{'、'.join(s['keywords'])}",
              *play_rules(s)]
    if mode:
        params.append(f"主号 UID：{owner}")
    week = f"{t.isocalendar().year}-W{t.isocalendar().week:02d}"
    if t.weekday() == 6 and t.hour >= 18 and not dry_run and not (workspace / "journal" / f"week-{week}.md").exists():
        params.append(f"今天是周日晚上，顺便写本周回顾 journal/week-{week}.md")
    feedback = life.share_feedback(chat)
    parts = [memory_part(workspace), chat_part([e for e in chat if e.get("who") in ("owner", "bot")], cfg),
             "## 最近几次主动找主号的结果\n\n" + ("\n".join(
                 f"{datetime.fromtimestamp(f['t']):%m-%d %H:%M} {'回了' if f['answered'] else '没回'}：{f['text']}"
                 for f in feedback) or "（还没有）")]
    tools = [x for x in BROWSE_TOOLS if not (dry_run and x == "bili_favorite_add")]
    if not dry_run:
        tools += (["bili_send_message"] if mode else []) + (["bili_reply"] if comment_ok else [])
    extra = {"BILI_DM_KIND": "proactive" if mode == "share" else "nudge", "BILI_DM_MAX": "2" if mode == "share" else "1",
             "BILI_REPLY_MAX": "1" if comment_ok else "0", "BILI_REPLY_TO": "", "BILI_SESSION": f"browse-{int(now)}",
             "BILI_DM_UNTIL": str(int(life.quiet_start(now, cfg["life"]["owner_quiet"])))}
    return {"params": params, "parts": parts, "tools": tools}, extra, [owner] if mode else []


def cmd_browse(cfg, workspace, style, dry_run):
    load_cred(cfg)
    day = date.today().isoformat()
    ctx, extra, dm_to = browse_context(cfg, workspace, style, dry_run, time.time())
    before = today_comments(workspace, day)
    rc = run_agent(cfg, workspace, "browse", dry_run, ctx=ctx, extra=extra, dm_to=dm_to)
    verify_comments([r for r in today_comments(workspace, day) if r not in before], workspace / "journal" / f"{day}.md")
    return rc


def single_instance(path):
    """Lock path for the life of this process. Return the open file, or None when another process holds it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    f = open(path, "a+")
    try:
        if sys.platform == "win32":
            import msvcrt
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return None
    return f


def log_line(workspace, text):
    line = f"--- {datetime.now():%Y-%m-%d %H:%M:%S} {text}"
    print(line, flush=True)
    (workspace / "logs").mkdir(parents=True, exist_ok=True)
    with open(workspace / "logs" / f"{date.today().isoformat()}.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")


# Background jobs do not see variables that were set only in the shell that ran install. Keep the ones the
# agent needs to reach its model. CLAUDE_CODE_* is not taken as a prefix: inside Claude Code it holds session ids.
AGENT_ENV_PREFIXES = ("ANTHROPIC_", "OPENAI_", "AWS_", "CLOUD_ML_")
AGENT_ENV_NAMES = {"CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX",
                   "CLAUDE_CODE_MAX_OUTPUT_TOKENS", "CLAUDE_CONFIG_DIR", "CODEX_API_KEY", "CODEX_HOME",
                   "GOOGLE_APPLICATION_CREDENTIALS", "NODE_EXTRA_CA_CERTS", "SSL_CERT_FILE",
                   "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "ALL_PROXY", "PATH"}


def save_agent_env(workspace):
    env = {k: v for k, v in os.environ.items() if k.startswith(AGENT_ENV_PREFIXES) or k.upper() in AGENT_ENV_NAMES}
    f = workspace / "agent.env"
    f.write_text(json.dumps(env, indent=1), encoding="utf-8")
    if sys.platform != "win32":
        os.chmod(f, 0o600)


def load_agent_env(workspace):
    f = workspace / "agent.env"
    if f.exists():
        for k, v in json.loads(f.read_text(encoding="utf-8")).items():
            if k == "PATH":  # a background job gets the PATH saved in the system, which can miss where claude is
                have = os.environ.get("PATH", "").split(os.pathsep)
                os.environ["PATH"] = os.pathsep.join(have + [d for d in v.split(os.pathsep) if d and d not in have])
            else:
                os.environ.setdefault(k, v)


def start_job(argv):
    return subprocess.Popen([sys.executable, str(ROOT / "run.py")] + argv, cwd=ROOT,
                            start_new_session=sys.platform != "win32")


def kill_job(p):
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True)
    else:
        import signal
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        p.wait(timeout=30)
    except subprocess.TimeoutExpired:
        pass  # reap tries again next minute; never block the loop that holds the lock


NOTES = {"awake": "有空", "busy": "在忙", "browsing": "正在刷站"}
JOB_LIMITS = {"inbox": 20 * 60, "daily": 3600, "short": 25 * 60, "long": 75 * 60, "dryrun": 25 * 60}


class Serve:
    """The long-running loop. Each job is a new process: it reads config.toml again, and whatever it leaks
    or hangs on ends with it. The web page only reads the state and queues actions; the loop does the work."""

    def __init__(self, config, workspace, at, every):
        self.config, self.ws, self.at, self.every = config, workspace, at, max(1, every)
        self.base = ["--config", config, "--data", str(workspace)]
        self.life_file = workspace / "life.json"
        self.life = life.load(self.life_file)
        self.rng = life.new_rng()
        self.lock = threading.RLock()  # loop holds it around tick, and tick takes it again for the actions
        self.wake = threading.Event()
        self.jobs, self.actions, self.tries = {}, [], {}
        self.daily_started, self.doctor_out, self.force_inbox = 0.0, "", False
        self.web, self.web_error = None, ""

    def running(self, name):
        j = self.jobs.get(name)
        return bool(j) and j[0].poll() is None

    def start(self, name, argv, limit, now):
        self.jobs[name] = (start_job(self.base + argv), now, limit)
        log_line(self.ws, "开始 " + " ".join(argv))

    def reap(self, now):
        for name, (p, t0, limit) in list(self.jobs.items()):
            if p.poll() is None and now - t0 > limit:
                kill_job(p)
                log_line(self.ws, f"{name} 跑了 {int(limit / 60)} 分钟还没完，已停掉")
            if p.poll() is not None:
                del self.jobs[name]
                if name == "browse":
                    life.after_session(self.life, now, self.rng)

    def state(self, cfg, now):
        if self.life.get("paused"):
            return "paused", ""
        if self.running("browse") or self.running("daily"):
            return "browsing", ""
        if not cfg["life"]["enabled"]:
            return "awake", ""
        return life.state(life.current_plan(self.life, cfg["life"], now, self.rng), now)

    def tick(self, cfg, now):
        self.reap(now)
        with self.lock:
            actions, self.actions = self.actions, []
        for a in actions:
            self.act(a, now)
        if self.life.get("paused"):
            return
        st, why = self.state(cfg, now)
        if cfg["life"]["enabled"]:
            if st == "asleep":
                self.life["next_inbox"] = max(self.life.get("next_inbox", 0), self.life["plan"]["wake"])
            elif st == "awake" and "browse" not in self.jobs and now >= self.life.get("next_session", 0):
                style = life.session_style(self.rng)
                self.start("browse", ["browse", "--style", style], JOB_LIMITS[style], now)
                st = "browsing"
        else:  # a wake time left over from the routine must not hold up the plain every-N-minutes checks
            self.life["next_inbox"] = min(self.life.get("next_inbox", 0), now + self.every * 60)
        if not cfg["life"]["enabled"] or cfg["life"].get("daily_report"):
            self.daily(now)
        if (cfg["inbox"]["enabled"] and int(cfg["inbox"]["owner_uid"] or 0) and "inbox" not in self.jobs
                and (self.force_inbox or (st != "asleep" and now >= self.life.get("next_inbox", 0)))):
            self.force_inbox = False
            st = "awake" if st == "asleep" else st
            self.start("inbox", ["inbox", "--note", NOTES[st] + (f"（{why}）" if why else "")], JOB_LIMITS["inbox"], now)
            delay = life.inbox_delay(st, self.every, self.rng) if cfg["life"]["enabled"] else self.every * 60
            self.life["next_inbox"] = now + delay

    def daily(self, now):
        t = datetime.fromtimestamp(now)
        today, (hh, mm) = t.date().isoformat(), (int(x) for x in self.at.split(":"))
        if (not self.running("daily") and (t.hour, t.minute) >= (hh, mm) and self.tries.get(today, 0) < 3
                and now - self.daily_started >= 3600 and not (self.ws / "out" / f"{today}.md").exists()):
            self.tries[today] = self.tries.get(today, 0) + 1  # no report yet: try again an hour later, 3 times a day
            self.daily_started = now
            self.start("daily", ["once"], JOB_LIMITS["daily"], now)

    def act(self, action, now):
        if action == "pause":
            self.life["paused"] = True
        elif action == "resume":
            self.life["paused"] = False
        elif action == "inbox":
            self.force_inbox = True
        elif action == "browse" and "browse" not in self.jobs:
            self.start("browse", ["browse", "--style", "short"], JOB_LIMITS["short"], now)
        elif action == "dryrun" and "dryrun" not in self.jobs:
            self.start("dryrun", ["browse", "--style", "short", "--dry-run"], JOB_LIMITS["dryrun"], now)
        elif action == "daily" and "daily" not in self.jobs:
            self.start("daily", ["once"], JOB_LIMITS["daily"], now)
        elif action == "doctor" and self.doctor_out != "检查中…":
            threading.Thread(target=self.doctor, daemon=True).start()

    def doctor(self):
        self.doctor_out = "检查中…"
        try:
            p = subprocess.run([sys.executable, str(ROOT / "run.py"), "--config", self.config, "doctor"], cwd=ROOT,
                               capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
            self.doctor_out = (p.stdout + p.stderr).strip()
        except Exception as e:
            self.doctor_out = f"体检没跑完：{type(e).__name__}: {e}"

    def request(self, action):
        with self.lock:
            self.actions.append(action)
        self.wake.set()

    def snapshot(self):
        cfg, now = load_config(self.config), time.time()
        with self.lock:
            st, why = self.state(cfg, now)
            chat = life.read_chat(self.ws / "chat.jsonl")
            mode, reason = life.proactive(chat, cfg["life"], now)
            day0 = datetime.combine(date.today(), datetime.min.time()).timestamp()
            mood = self.ws / "memory" / "mood.txt"
            return {"state": st, "why": why, "now": now, "plan": self.life.get("plan"), "life_on": cfg["life"]["enabled"],
                    "next_session": self.life.get("next_session"), "next_inbox": self.life.get("next_inbox"),
                    "jobs": sorted(n for n in self.jobs if self.running(n)), "paused": bool(self.life.get("paused")),
                    "contacts_today": len({e.get("session") for e in chat if e["t"] >= day0 and e.get("who") == "bot"
                                           and e.get("kind") in ("proactive", "nudge")}),
                    "max_contacts": cfg["life"]["max_contacts_per_day"], "can_contact": mode, "contact_note": reason,
                    "mood": mood.read_text(encoding="utf-8", errors="replace").strip() if mood.exists() else "",
                    "logged_in": cred_file(cfg).exists(), "owner": owner_name(cfg), "doctor": self.doctor_out}

    def start_web(self, cfg):
        """Try every minute: at boot the Tailscale address can come up later than serve."""
        if self.web or not cfg["web"]["password"]:
            return
        import web
        try:
            self.web = web.start(self, sys.modules[__name__], cfg["web"])
            log_line(self.ws, f"后台网页在 http://{cfg['web']['host']}:{cfg['web']['port']}")
        except Exception as e:
            if str(e) != self.web_error:
                self.web_error = str(e)
                log_line(self.ws, f"后台网页没起来，每分钟再试：{type(e).__name__}: {e}")

    def stop(self, *_):
        for p, _, _ in list(self.jobs.values()):
            kill_job(p)
        sys.exit(0)

    def loop(self):
        while True:
            try:
                cfg = load_config(self.config)
                self.start_web(cfg)
                with self.lock:
                    self.tick(cfg, time.time())
                    write_json(self.life_file, self.life)
            except Exception as e:
                log_line(self.ws, f"出错，下一轮再试：{type(e).__name__}: {e}")
            self.wake.wait(60)
            self.wake.clear()


def cmd_serve(config, workspace, at, every):
    lock = single_instance(workspace / "serve.lock")
    if not lock:
        return 0  # schedule starts serve every 10 minutes to keep one alive. The extra ones end here.
    (workspace / "serve.pid").write_text(str(os.getpid()), encoding="utf-8")
    load_agent_env(workspace)
    srv = Serve(config, workspace, at, every)
    cfg = load_config(config)
    log_line(workspace, "serve 启动，" + ("按作息刷站和查消息" if cfg["life"]["enabled"] else
                                        f"开了收件箱就每 {every} 分钟查一次消息，每天 {at} 以后刷一轮"))
    if sys.platform != "win32":
        import signal
        signal.signal(signal.SIGTERM, srv.stop)  # jobs run in their own sessions, so take them down with serve
    srv.loop()


def stop_serve(workspace):
    probe = single_instance(workspace / "serve.lock")
    if probe:
        probe.close()
    if probe or not (workspace / "serve.pid").exists():
        return
    pid = int((workspace / "serve.pid").read_text(encoding="utf-8"))
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    else:
        import signal
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return
    for _ in range(20):
        probe = single_instance(workspace / "serve.lock")
        if probe:
            probe.close()
            return
        time.sleep(0.5)


def agent_smoke(cfg):
    """Make one tiny real call, so a missing login or a wrong model shows up now and not in a background log."""
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        (ws / ".mcp.json").write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")
        cmd = agent_command(cfg, ws, ws / ".mcp.json", ws / "p.md", ["bili_check_credential"])
        try:
            p = subprocess.run([shutil.which(cmd[0])] + cmd[1:], input="只回复两个字母 ok", cwd=ws, capture_output=True,
                               text=True, encoding="utf-8", errors="replace", timeout=300, env=agent_env(cfg))
        except subprocess.TimeoutExpired:
            return False, "试调用 agent：5 分钟没有回应"
    if p.returncode == 0 and "ok" in p.stdout.lower():
        return True, "试调用 agent：能正常回复"
    return False, "试调用 agent 失败：" + (p.stdout + p.stderr).strip()[-300:]


def cmd_doctor(cfg):
    ok = True

    def report(good, text):
        nonlocal ok
        ok &= good
        print(("[ok]   " if good else "[fail] ") + text)

    report(sys.version_info >= (3, 11), f"Python {sys.version.split()[0]}（需要 3.11 以上）")
    try:
        import bilibili_api, mcp, qrcode  # noqa: F401
        report(True, "依赖已装好")
    except ImportError as e:
        report(False, f"缺依赖：{e.name}。运行 pip install -r requirements.txt")
    if cred_file(cfg).exists():
        try:
            from bilibili_api import Credential, user
            info = asyncio.run(user.get_self_info(Credential(**load_cred(cfg))))
            report(True, f"已登录：{info.get('name')}（{info.get('level')} 级）")
        except Exception as e:
            report(False, f"凭证失效，重新运行 python run.py login（{type(e).__name__}）")
    else:
        report(False, "还没登录，运行 python run.py login")
    name = cfg["agent"]["name"]
    exe = name if name != "custom" else (cfg["agent"].get("custom_command") or ["?"])[0]
    report(bool(shutil.which(exe)), f"agent 命令行：{exe} {'在' if shutil.which(exe) else '不在'} PATH 里")
    if shutil.which(exe) and name != "custom":
        report(*agent_smoke(cfg))
    if cfg["comment"]["enabled"] and not cfg["comment"]["at"]:
        report(False, "开了评论，但 [comment] 里的 at（主号昵称）没填")
    if cfg["inbox"]["enabled"] and not cfg["inbox"]["owner_uid"]:
        report(False, "开了收件箱，但 [inbox] 里的 owner_uid 没填")
    return 0 if ok else 1


# One task starts serve at boot, at logon and again every 10 minutes. serve holds a lock, so the repeats only
# restart it after a crash. No time limit: serve is meant to run for days. S4U runs the task with nobody
# logged on and stores no password. Registering it needs an admin terminal, so a normal one gets exit code 3
# and a task that runs only while the user is logged on.
WINDOWS_SCHEDULE = r"""
$ErrorActionPreference = 'Stop'
$s = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries `
  -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
Get-ScheduledTask -TaskName 'claude-bili-scroll*' -ErrorAction SilentlyContinue | Unregister-ScheduledTask -Confirm:$false
if ($env:CBS_REMOVE -eq '1') { exit }
$me = [Security.Principal.WindowsIdentity]::GetCurrent().Name  # USERDOMAIN is WORKGROUP in an SSH session
$arg = '"{0}" "{1}" "{2}" --config "{3}" serve --at {4} --every {5}' -f `
  $env:CBS_VBS, $env:CBS_PY, $env:CBS_RUN, $env:CBS_CFG, $env:CBS_AT, $env:CBS_EVERY
$act = New-ScheduledTaskAction -Execute 'wscript.exe' -Argument $arg -WorkingDirectory $env:CBS_ROOT
$logon = New-ScheduledTaskTrigger -AtLogOn -User $me
$keep = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 10)
$code = 0
try {
  $p = New-ScheduledTaskPrincipal -UserId $me -LogonType S4U
  $boot = New-ScheduledTaskTrigger -AtStartup
  Register-ScheduledTask -TaskName 'claude-bili-scroll' -Settings $s -Action $act -Principal $p -Trigger $boot, $logon, $keep | Out-Null
} catch {
  Register-ScheduledTask -TaskName 'claude-bili-scroll' -Settings $s -Action $act -Trigger $logon, $keep | Out-Null
  $code = 3
}
Start-ScheduledTask -TaskName 'claude-bili-scroll'
exit $code
"""
# Task Scheduler flashes a console window for python.exe. WScript.Run with window style 0 starts it hidden.
RUN_HIDDEN_VBS = "\r\n".join([
    'Set a = WScript.Arguments',
    'cmd = ""',
    'For i = 0 To a.Count - 1',
    '  cmd = cmd & " """ & a(i) & """"',
    'Next',
    'WScript.Quit CreateObject("WScript.Shell").Run(Mid(cmd, 2), 0, True)', ''])


def cmd_schedule(cfg, args):
    py, script, remove = sys.executable, str(ROOT / "run.py"), getattr(args, "remove", False)
    config = str(Path(args.config).resolve())
    workspace = resolve(cfg["paths"]["data"])
    (workspace / "logs").mkdir(parents=True, exist_ok=True)
    stop_serve(workspace)
    if not remove:
        save_agent_env(workspace)
    serve = [py, script, "--config", config, "serve", "--at", args.at, "--every", str(args.every)]
    if sys.platform == "win32":
        vbs = workspace / "run-hidden.vbs"
        vbs.write_text(RUN_HIDDEN_VBS, encoding="utf-8")
        env = dict(os.environ, CBS_ROOT=str(ROOT), CBS_VBS=str(vbs), CBS_PY=py, CBS_RUN=script, CBS_CFG=config,
                   CBS_AT=args.at, CBS_EVERY=str(args.every), CBS_REMOVE="1" if remove else "0")
        shell = shutil.which("pwsh") or "powershell"
        rc = subprocess.run([shell, "-NoProfile", "-Command", WINDOWS_SCHEDULE], env=env).returncode
        if rc == 3:
            rc = 0
            print("这个终端不是管理员，后台任务只在你登录以后运行。想开机就跑、不用登录，用管理员终端再运行一次 schedule。")
    else:
        tag = "# claude-bili-scroll"
        old = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
        lines = [line for line in old.splitlines() if tag not in line]
        log = workspace / "logs" / "serve.log"
        if not remove:
            run_it = f'cd "{ROOT}" && PATH="{os.environ.get("PATH", "")}" ' + " ".join(f'"{a}"' for a in serve)
            lines += [f'@reboot {run_it} >> "{log}" 2>&1 {tag}', f'*/10 * * * * {run_it} >> "{log}" 2>&1 {tag}']
        rc = subprocess.run(["crontab", "-"], input="\n".join(lines) + "\n", text=True).returncode
        if rc == 0 and not remove:
            with open(log, "a") as f:
                subprocess.Popen(serve, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=f, stderr=subprocess.STDOUT,
                                 start_new_session=True)
    inbox = cfg["inbox"]["enabled"] and cfg["inbox"]["owner_uid"]
    if rc == 0:
        plan = "按作息刷站，" if cfg["life"]["enabled"] else f"每天 {args.at} 以后刷一轮，"
        print("后台任务已停掉并删除。" if remove else f"已在后台常驻运行。{plan}" +
              (f"每 {args.every} 分钟上下查一次消息" if inbox else "收件箱没开，不查消息") + f"。日志在 {workspace / 'logs'}")
    return rc


def cmd_install(args):
    venv = ROOT / ".venv"
    vpy = venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    if Path(sys.prefix).resolve() != venv.resolve():
        if not vpy.exists():
            print("创建虚拟环境 .venv")
            subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
        if subprocess.run([str(vpy), "-m", "pip", "--version"], capture_output=True).returncode:
            subprocess.run([str(vpy), "-m", "ensurepip", "--upgrade"], check=True)  # uv makes a .venv without pip
        print("安装依赖")
        subprocess.run([str(vpy), "-m", "pip", "install", "-q", "-r", str(ROOT / "requirements.txt")], check=True)
        return subprocess.run([str(vpy), str(ROOT / "run.py")] + sys.argv[1:]).returncode
    config = Path(args.config)
    if not config.exists():
        shutil.copy(ROOT / "config.example.toml", config)
        print(f"已生成 {config}。照里面的注释改好，再运行一次 install")
        return 1
    cfg = load_config(config)
    if not cred_file(cfg).exists():
        cmd_login(cfg)
    if cmd_doctor(cfg):
        print("上面有 [fail] 的项，修好以后再运行一次 install")
        return 1
    return cmd_schedule(cfg, args)


def hhmm(text):
    h, m = (int(x) for x in text.split(":"))
    if not (0 <= h < 24 and 0 <= m < 60):
        raise ValueError(text)
    return f"{h:02d}:{m:02d}"


def main(argv=None):
    # A Windows console with a non-UTF-8 code page cannot print Chinese and would crash the run.
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(errors="replace")
    ap = argparse.ArgumentParser(prog="run.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=str(ROOT / "config.toml"), help="配置文件，默认是仓库里的 config.toml")
    ap.add_argument("--data", help="临时换一个数据目录（凭证仍从配置里的目录读），试运行时用")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("login", help="扫码登录小号")
    sub.add_parser("doctor", help="检查环境，并试调用一次 agent")
    for name, text in (("once", "跑一轮每日任务"), ("inbox", "处理新的 @、回复和私信"), ("browse", "按作息刷一会儿 B 站")):
        sp = sub.add_parser(name, help=text)
        sp.add_argument("--dry-run", action="store_true", help="只拟稿，不发评论和回复")
        if name == "inbox":
            sp.add_argument("--note", default="", help="告诉 agent 它现在在干什么，serve 会自动填")
        if name == "browse":
            sp.add_argument("--style", choices=sorted(STYLES), default="short", help="short 随手看几条，long 连着刷一阵")
    for name, text in (("install", "新机器一条命令装好：虚拟环境、依赖、登录、检查，最后在后台常驻运行"),
                       ("serve", "常驻运行：定时查消息，每天刷一轮"), ("schedule", "设成登录后自动在后台常驻运行")):
        sp = sub.add_parser(name, help=text)
        sp.add_argument("--at", type=hhmm, default="12:00", help="每天几点以后刷一轮，默认 12:00")
        sp.add_argument("--every", type=int, default=5, help="每隔几分钟查一次 @、回复和私信，默认 5")
        if name == "schedule":
            sp.add_argument("--remove", action="store_true", help="停掉并删掉后台任务")
    args = ap.parse_args(argv)
    if args.cmd == "install":
        return cmd_install(args)
    cfg = load_config(args.config)
    workspace = resolve(args.data or cfg["paths"]["data"])
    if args.cmd == "login":
        return cmd_login(cfg)
    if args.cmd == "doctor":
        return cmd_doctor(cfg)
    if args.cmd == "schedule":
        return cmd_schedule(cfg, args)
    if args.cmd == "serve":
        return cmd_serve(str(Path(args.config).resolve()), workspace, args.at, args.every)
    load_agent_env(resolve(cfg["paths"]["data"]))  # a run by hand reaches the model the same way as a job of serve
    if args.cmd == "inbox":
        return cmd_inbox(cfg, workspace, args.dry_run, args.note)
    if args.cmd == "browse":
        return cmd_browse(cfg, workspace, args.style, args.dry_run)
    return cmd_once(cfg, workspace, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
