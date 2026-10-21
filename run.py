#!/usr/bin/env python3
"""claude-bili-scroll: let your AI agent scroll Bilibili for you once a day.

Commands:
  install   set up .venv, log in, check everything, then run schedule (one command for a new machine)
  login     scan a QR code with the Bilibili app to log in the bot account
  doctor    check Python, login, the agent CLI, and one real agent call
  once      run one daily round: pick videos, write the report, maybe comment
  inbox     answer new @ mentions, replies and private messages (exits early when there is nothing new)
  serve     stay running: check the inbox every few minutes, run the daily round once a day
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
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

if sys.version_info < (3, 11):
    sys.exit(f"需要 Python 3.11 以上，当前是 {sys.version.split()[0]}")
import tomllib  # noqa: E402

ROOT = Path(__file__).resolve().parent
SERVER = ROOT / "bili_mcp" / "server.py"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
      "Referer": "https://www.bilibili.com/"}

DEFAULTS = {
    "agent": {"name": "claude", "model": "", "effort": "medium", "custom_command": []},
    "scroll": {"max_picks": 5, "min_play": 100000, "days": 30, "weekly_hot": True,
               "keywords": ["AI工具", "编程", "数码评测", "知识科普", "生活技巧", "纪录片"]},
    "comment": {"enabled": False, "at": "", "max_per_run": 1},
    "inbox": {"enabled": False, "owner_uid": 0, "max_stranger_replies_per_day": 10},
    "persona": {"file": "personas/neutral.md"},
    "paths": {"data": "data"},
}
SCROLL_TOOLS = ["bili_search", "bili_weekly_hot", "bili_subtitle", "bili_comments", "bili_video_info", "bili_check_credential"]
INBOX_TOOLS = ["bili_subtitle", "bili_danmaku", "bili_frames", "bili_comments", "bili_video_info", "bili_check_credential"]
CLAUDE_FILE_TOOLS = ["Read", "Write", "Edit", "Glob", "Grep"]


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


def build_prompt(cfg, task, dry_run, messages=None):
    """Return (prompt, tools). The persona and the voice skill are appended to every task."""
    persona = read_md(resolve(cfg["persona"]["file"])).replace("{owner}", owner_name(cfg))
    parts = [read_md(ROOT / "prompts" / f"{task}.md"), persona,
             read_md(ROOT / "skills" / "bili-comment-voice" / "SKILL.md")]
    today = date.today().isoformat()
    params = [f"1. 今天：{today}"]
    if task == "scroll":
        s, c = cfg["scroll"], cfg["comment"]
        tools = list(SCROLL_TOOLS)
        comment_on = c["enabled"] and c["at"] and not dry_run
        params += [f"2. 关键词：{'、'.join(s['keywords'])}",
                   f"3. 每周必看：{'开' if s['weekly_hot'] else '关'}",
                   f"4. 播放量门槛：{s['min_play']}，只看近 {s['days']} 天发布的",
                   f"5. 每天最多挑 {s['max_picks']} 条",
                   f"6. 评论：{'开' if comment_on else '关'}，主号昵称 {c['at'] or '未设置'}，每轮最多 {c['max_per_run']} 条"]
        if comment_on:
            tools.append("bili_reply")
    else:
        channels = {m.get("channel", "comment") for m in messages or []}
        tools = list(INBOX_TOOLS)
        if not dry_run:
            tools += [t for ch, t in (("comment", "bili_reply"), ("dm", "bili_send_message")) if ch in channels]
        params.append(f"2. 主号昵称：{owner_name(cfg)}")
        parts.append("## 消息\n\n```json\n" + json.dumps(messages or [], ensure_ascii=False, indent=1) + "\n```")
    if dry_run:
        params.append(f"{len(params) + 1}. 试运行：不发评论，不发回复，把拟好的内容写进记录。")
    params.append(f"{len(params) + 1}. 工作目录就是当前目录，所有文件都写在这里。")
    parts.append("## 这一轮的参数\n\n" + "\n".join(params))
    return "\n\n".join(parts) + "\n", tools


def mcp_server_spec(cfg, tools, workspace, dm_to=()):
    return {"command": sys.executable, "args": ["-I", str(SERVER)],
            "env": {"BILI_MCP_TOOLS": ",".join(tools), "BILI_CREDENTIAL_FILE": str(cred_file(cfg)),
                    "BILI_FRAMES_DIR": str(workspace), "BILI_DM_TO": ",".join(map(str, dm_to)),
                    "BILI_DM_OWNER": str(int(cfg["inbox"]["owner_uid"] or 0)), "PYTHONIOENCODING": "utf-8"}}


def agent_command(cfg, workspace, mcp_json, prompt_file, tools, dm_to=()):
    a = cfg["agent"]
    name, model, effort = a["name"], a.get("model", ""), a.get("effort", "")
    if name == "claude":
        allowed = [f"mcp__bili__{t}" for t in tools] + CLAUDE_FILE_TOOLS
        cmd = ["claude", "-p", "--mcp-config", str(mcp_json), "--strict-mcp-config",
               "--permission-mode", "acceptEdits", "--allowedTools", " ".join(allowed),
               "--disallowedTools", "Bash PowerShell WebFetch WebSearch Agent"]
        cmd += ["--model", model] if model else []
        cmd += ["--effort", effort] if effort else []
        return cmd
    if name == "codex":
        spec = mcp_server_spec(cfg, tools, workspace, dm_to)
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


def run_agent(cfg, workspace, task, dry_run, messages=None):
    prompt, tools = build_prompt(cfg, task, dry_run, messages)
    dm_to = sorted({m["mid"] for m in messages or [] if m.get("channel") == "dm"})
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "logs").mkdir(exist_ok=True)
    prompt_file = workspace / f".prompt-{task}.md"
    prompt_file.write_text(prompt, encoding="utf-8")
    mcp_json = workspace / ".mcp.json"
    spec = mcp_server_spec(cfg, tools, workspace, dm_to)
    mcp_json.write_text(json.dumps({"mcpServers": {"bili": spec}}, indent=2), encoding="utf-8")
    cmd = agent_command(cfg, workspace, mcp_json, prompt_file, tools, dm_to)
    exe = shutil.which(cmd[0])
    if not exe:
        sys.exit(f"找不到 {cmd[0]}。先装好这个 agent 的命令行工具，并确认它在 PATH 里。")
    log = workspace / "logs" / f"{date.today().isoformat()}.log"
    with open(log, "a", encoding="utf-8") as f:
        f.write(f"\n=== {datetime.now():%H:%M:%S} {task}{' dry-run' if dry_run else ''} via {cfg['agent']['name']}\n")
        p = subprocess.Popen([exe] + cmd[1:], cwd=workspace, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
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


def cmd_login(cfg):
    import qrcode
    from http.cookies import SimpleCookie
    base = "https://passport.bilibili.com/x/passport-login/web/qrcode/"
    d = http_json(base + "generate?source=main-fe-header")[0]["data"]
    qr = qrcode.QRCode(border=1)
    qr.add_data(d["url"])
    qr.print_ascii(invert=True)
    png = cred_file(cfg).with_name("login-qrcode.png")
    png.parent.mkdir(parents=True, exist_ok=True)
    qrcode.make(d["url"]).save(png)
    if sys.platform == "win32":
        os.startfile(png)
    elif sys.platform == "darwin":
        subprocess.run(["open", png])
    print(f"用小号的 B 站 App 扫上面的码（图片也存在 {png}），确认时选“长期”。180 秒内有效。")
    try:
        for _ in range(90):
            time.sleep(2)
            body, cookies = http_json(base + f"poll?qrcode_key={d['qrcode_key']}&source=main-fe-header")
            code = body["data"]["code"]
            if code == 86038:
                sys.exit("二维码过期了，重新运行 python run.py login")
            if code == 0:
                # bilibili_api's QrCodeLogin reads SESSDATA from data.url, which is empty now. It is in Set-Cookie.
                jar = SimpleCookie()
                for c in cookies:
                    jar.load(c)
                cred = {"sessdata": jar["SESSDATA"].value, "bili_jct": jar["bili_jct"].value,
                        "dedeuserid": jar["DedeUserID"].value, "buvid3": guest_cookie().split("=", 1)[1]}
                tmp = cred_file(cfg).with_suffix(".tmp")
                tmp.write_text(json.dumps(cred), encoding="utf-8")
                os.replace(tmp, cred_file(cfg))
                print(f"登录成功，UID {cred['dedeuserid']}。凭证只存在本机：{cred_file(cfg)}")
                return 0
        sys.exit("等太久了，重新运行 python run.py login")
    finally:
        png.unlink(missing_ok=True)


def comment_rows(seen_text, day):
    return re.findall(rf"评论 {day} (BV\w{{10}}) rpid=(\d+)", seen_text)


def verify_comments(workspace, day):
    """A shadow-hidden comment is visible only to its author and sends no @ notification. Check as a guest."""
    seen = workspace / "seen.md"
    rows = comment_rows(seen.read_text(encoding="utf-8"), day) if seen.exists() else []
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
        (workspace / "out").mkdir(exist_ok=True)
        with open(workspace / "out" / f"{day}.md", "a", encoding="utf-8") as f:
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


def cmd_inbox(cfg, workspace, dry_run):
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
    # Save before the agent runs, so a kill halfway cannot make it answer the same messages again.
    # A failed run also counts as handled: retrying every few minutes would look like spam.
    if not dry_run:
        write_json(state_file, state)
    return run_agent(cfg, workspace, "inbox", dry_run, todo)


def write_json(path, data):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, path)


def cmd_once(cfg, workspace, dry_run):
    load_cred(cfg)
    rc = run_agent(cfg, workspace, "scroll", dry_run)
    verify_comments(workspace, date.today().isoformat())
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
    p.wait()


def cmd_serve(config, workspace, at, every):
    lock = single_instance(workspace / "serve.lock")
    if not lock:
        return 0  # schedule starts serve every 10 minutes to keep one alive. The extra ones end here.
    (workspace / "serve.pid").write_text(str(os.getpid()), encoding="utf-8")
    load_agent_env(workspace)
    hh, mm = (int(x) for x in at.split(":"))
    log_line(workspace, f"serve 启动，开了收件箱就每 {every} 分钟查一次消息，每天 {at} 以后刷一轮")
    base = ["--config", config, "--data", str(workspace)]
    daily, started, tries = None, 0.0, {}
    # Each job is a new process: it reads config.toml again, and whatever it leaks or hangs on ends with it.
    # The daily round runs beside the inbox checks, so a long round does not hold up the replies.
    while True:
        try:
            cfg, now = load_config(config), datetime.now()
            today = now.date().isoformat()
            if daily and daily.poll() is None and time.time() - started > 3600:
                kill_job(daily)
                log_line(workspace, "每日一轮跑了一个小时还没完，已停掉")
            if ((not daily or daily.poll() is not None) and (now.hour, now.minute) >= (hh, mm)
                    and tries.get(today, 0) < 3 and time.time() - started >= 3600
                    and not (workspace / "out" / f"{today}.md").exists()):
                tries[today] = tries.get(today, 0) + 1  # no report yet: try again an hour later, 3 times a day
                daily, started = start_job(base + ["once"]), time.time()
            if cfg["inbox"]["enabled"] and int(cfg["inbox"]["owner_uid"] or 0):
                p = start_job(base + ["inbox"])
                try:
                    p.wait(timeout=20 * 60)
                except subprocess.TimeoutExpired:
                    kill_job(p)
                    log_line(workspace, "收件箱跑了 20 分钟还没完，已停掉")
        except Exception as e:
            log_line(workspace, f"出错，下一轮再试：{type(e).__name__}: {e}")
        time.sleep(max(1, every) * 60)


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
                               text=True, encoding="utf-8", errors="replace", timeout=300)
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
        print("后台任务已停掉并删除。" if remove else
              f"已在后台常驻运行。每天 {args.at} 以后刷一轮，" +
              (f"每 {args.every} 分钟查一次消息" if inbox else "收件箱没开，不查消息") + f"。日志在 {workspace / 'logs'}")
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
    for name, text in (("once", "跑一轮每日任务"), ("inbox", "处理新的 @、回复和私信")):
        sub.add_parser(name, help=text).add_argument("--dry-run", action="store_true", help="只拟稿，不发评论和回复")
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
    if args.cmd == "inbox":
        return cmd_inbox(cfg, workspace, args.dry_run)
    return cmd_once(cfg, workspace, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
