#!/usr/bin/env python3
"""claude-bili-scroll: let your AI agent scroll Bilibili for you once a day.

Commands:
  login     scan a QR code with the Bilibili app to log in the bot account
  doctor    check Python, login, agent CLI and the MCP server
  once      run one daily round: pick videos, write the report, maybe comment
  inbox     answer new @ mentions and replies (exits early when there is nothing new)
  schedule  install the daily round and the inbox check as scheduled jobs
"""
import argparse
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import time
import tomllib
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

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
INBOX_TOOLS = ["bili_subtitle", "bili_danmaku", "bili_comments", "bili_video_info", "bili_check_credential"]
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
        tools = list(INBOX_TOOLS) + ([] if dry_run else ["bili_reply"])
        params.append(f"2. 主号昵称：{owner_name(cfg)}")
        parts.append("## 消息\n\n```json\n" + json.dumps(messages or [], ensure_ascii=False, indent=1) + "\n```")
    if dry_run:
        params.append(f"{len(params) + 1}. 试运行：不发评论，不发回复，把拟好的内容写进记录。")
    params.append(f"{len(params) + 1}. 工作目录就是当前目录，所有文件都写在这里。")
    parts.append("## 这一轮的参数\n\n" + "\n".join(params))
    return "\n\n".join(parts) + "\n", tools


def mcp_server_spec(cfg, tools):
    return {"command": sys.executable, "args": ["-I", str(SERVER)],
            "env": {"BILI_MCP_TOOLS": ",".join(tools), "BILI_CREDENTIAL_FILE": str(cred_file(cfg)),
                    "PYTHONIOENCODING": "utf-8"}}


def agent_command(cfg, workspace, mcp_json, prompt_file, tools):
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
        spec = mcp_server_spec(cfg, tools)
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
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "logs").mkdir(exist_ok=True)
    prompt_file = workspace / f".prompt-{task}.md"
    prompt_file.write_text(prompt, encoding="utf-8")
    mcp_json = workspace / ".mcp.json"
    mcp_json.write_text(json.dumps({"mcpServers": {"bili": mcp_server_spec(cfg, tools)}}, indent=2), encoding="utf-8")
    cmd = agent_command(cfg, workspace, mcp_json, prompt_file, tools)
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
    return {"rpid": int(it["source_id"]), "root": int(it.get("root_id") or it["source_id"]),
            "bvid": m.group(0), "title": it.get("title", ""), "mid": int(user.get("mid") or 0),
            "from": user.get("nickname", ""), "content": it.get("source_content", ""),
            "context": it.get("target_reply_content", ""), "time": int(n.get("at_time") or n.get("reply_time") or 0)}


def select_messages(notices, state, self_mid, owner_uid, stranger_limit, today, since):
    """Pick what the agent should answer. Mutates state. The owner is matched by UID, never by nickname."""
    if state.get("day") != today:
        state.update(day=today, strangers=[])
    handled = set(state.setdefault("handled", []))
    todo = []
    for msg in notices:
        if not msg or msg["rpid"] in handled or msg["mid"] == self_mid or msg["time"] < since:
            continue
        handled.add(msg["rpid"])
        if msg["mid"] == owner_uid:
            todo.append(dict(msg, kind="owner"))
        elif msg["mid"] not in state["strangers"] and len(state["strangers"]) < stranger_limit:
            state["strangers"].append(msg["mid"])
            todo.append(dict(msg, kind="stranger"))
    state["handled"] = sorted(handled)[-1000:]
    return todo


async def fetch_notices(cred):
    from bilibili_api import Credential, session
    c = Credential(**cred)
    out = []
    for fn in (session.get_at, session.get_replies):
        out += [parse_notice(n) for n in ((await fn(credential=c)).get("items") or [])]
    return out


def cmd_inbox(cfg, workspace, dry_run):
    owner = int(cfg["inbox"]["owner_uid"] or 0)
    if not owner:
        sys.exit("先在 config.toml 的 [inbox] 里填 owner_uid（主号 UID）")
    cred = load_cred(cfg)
    workspace.mkdir(parents=True, exist_ok=True)
    state_file = workspace / "inbox-state.json"
    state = json.loads(state_file.read_text(encoding="utf-8")) if state_file.exists() else {}
    since = int(time.time()) - 2 * 86400
    todo = select_messages(asyncio.run(fetch_notices(cred)), state, int(cred["dedeuserid"]), owner,
                           cfg["inbox"]["max_stranger_replies_per_day"], date.today().isoformat(), since)
    if not todo:
        print("没有新的 @ 或回复。")
        state_file.write_text(json.dumps(state), encoding="utf-8")
        return 0
    print(f"有 {len(todo)} 条要处理：" + "、".join(f"{m['from']}（{m['kind']}）" for m in todo))
    rc = run_agent(cfg, workspace, "inbox", dry_run, todo)
    # Mark as handled even when the agent failed: retrying every 10 minutes would look like spam.
    if not dry_run:
        state_file.write_text(json.dumps(state), encoding="utf-8")
    return rc


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
    if cfg["comment"]["enabled"] and not cfg["comment"]["at"]:
        report(False, "开了评论，但 [comment] 里的 at（主号昵称）没填")
    if cfg["inbox"]["enabled"] and not cfg["inbox"]["owner_uid"]:
        report(False, "开了收件箱，但 [inbox] 里的 owner_uid 没填")
    return 0 if ok else 1


WINDOWS_SCHEDULE = r"""
$s = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries `
  -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -MultipleInstances IgnoreNew
function Act($c) {
  $a = '"{0}" "{1}" "{2}" --config "{3}" {4}' -f $env:CBS_VBS, $env:CBS_PY, $env:CBS_RUN, $env:CBS_CFG, $c
  New-ScheduledTaskAction -Execute 'wscript.exe' -Argument $a -WorkingDirectory $env:CBS_ROOT
}
Get-ScheduledTask -TaskName 'claude-bili-scroll*' -ErrorAction SilentlyContinue | Unregister-ScheduledTask -Confirm:$false
if ($env:CBS_REMOVE -eq '1') { 'removed'; exit }
Register-ScheduledTask -TaskName 'claude-bili-scroll daily' -Settings $s -Action (Act 'once') `
  -Trigger (New-ScheduledTaskTrigger -Daily -At $env:CBS_AT) | Out-Null
if ($env:CBS_EVERY -ne '0') {
  $t = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes ([int]$env:CBS_EVERY))
  Register-ScheduledTask -TaskName 'claude-bili-scroll inbox' -Settings $s -Action (Act 'inbox') -Trigger $t | Out-Null
}
Get-ScheduledTask -TaskName 'claude-bili-scroll*' | ForEach-Object { '{0}  next run: {1}' -f $_.TaskName, (Get-ScheduledTaskInfo $_).NextRunTime }
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
    py, script = sys.executable, str(ROOT / "run.py")
    config = str(Path(args.config).resolve())
    every = args.every if cfg["inbox"]["enabled"] else 0
    hh, mm = args.at.split(":")
    if sys.platform == "win32":
        vbs = resolve(cfg["paths"]["data"]) / "run-hidden.vbs"
        vbs.parent.mkdir(parents=True, exist_ok=True)
        vbs.write_text(RUN_HIDDEN_VBS, encoding="utf-8")
        env = dict(os.environ, CBS_ROOT=str(ROOT), CBS_VBS=str(vbs), CBS_PY=py, CBS_RUN=script, CBS_CFG=config,
                   CBS_AT=args.at, CBS_EVERY=str(every), CBS_REMOVE="1" if args.remove else "0")
        shell = shutil.which("pwsh") or "powershell"
        return subprocess.run([shell, "-NoProfile", "-Command", WINDOWS_SCHEDULE], env=env).returncode
    tag = "# claude-bili-scroll"
    old = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
    lines = [line for line in old.splitlines() if tag not in line]
    if not args.remove:
        log = resolve(cfg["paths"]["data"]) / "logs" / "cron.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        base = f'cd "{ROOT}" && PATH="{os.environ.get("PATH", "")}" "{py}" "{script}" --config "{config}"'
        lines.append(f'{int(mm)} {int(hh)} * * * {base} once >> "{log}" 2>&1 {tag}')
        if every:
            lines.append(f'*/{every} * * * * {base} inbox >> "{log}" 2>&1 {tag}')
    subprocess.run(["crontab", "-"], input="\n".join(lines) + "\n", text=True, check=True)
    print("\n".join(line for line in lines if tag in line) or "removed")
    return 0


def main(argv=None):
    # A Windows console with a non-UTF-8 code page cannot print Chinese and would crash the run.
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(errors="replace")
    ap = argparse.ArgumentParser(prog="run.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=str(ROOT / "config.toml"), help="配置文件，默认是仓库里的 config.toml")
    ap.add_argument("--data", help="临时换一个数据目录（凭证仍从配置里的目录读），试运行时用")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("login", help="扫码登录小号")
    sub.add_parser("doctor", help="检查环境")
    for name, text in (("once", "跑一轮每日任务"), ("inbox", "处理新的 @ 和回复")):
        sub.add_parser(name, help=text).add_argument("--dry-run", action="store_true", help="只拟稿，不发评论和回复")
    sp = sub.add_parser("schedule", help="安装定时任务")
    sp.add_argument("--at", default="12:00", help="每天几点跑 once，默认 12:00")
    sp.add_argument("--every", type=int, default=10, help="每隔几分钟查一次收件箱，默认 10")
    sp.add_argument("--remove", action="store_true", help="删掉已装的定时任务")
    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    workspace = resolve(args.data or cfg["paths"]["data"])
    if args.cmd == "login":
        return cmd_login(cfg)
    if args.cmd == "doctor":
        return cmd_doctor(cfg)
    if args.cmd == "schedule":
        return cmd_schedule(cfg, args)
    if args.cmd == "inbox":
        return cmd_inbox(cfg, workspace, args.dry_run)
    load_cred(cfg)
    rc = run_agent(cfg, workspace, "scroll", args.dry_run)
    verify_comments(workspace, date.today().isoformat())
    return rc


if __name__ == "__main__":
    sys.exit(main())
