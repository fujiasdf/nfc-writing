from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from typing import Literal

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from .csv_queue import WriteItem, load_csv
from .nfc_backends.mock import MockWriter
from .nfc_backends.springcore_pcsc import PcscConfig, SpringCorePcscWriter
from .sound import beep_error, beep_ok


Mode = Literal["mock", "pcsc"]
RunMode = Literal["single", "csv"]


@dataclass
class RunState:
    items: list[WriteItem] = field(default_factory=list)
    statuses: list[str] = field(default_factory=list)  # pending/writing/ok/ng/error
    cursor: int = 0
    running: bool = False
    mode: Mode = "mock"
    run_mode: RunMode = "csv"
    single_url: str = ""
    reader_contains: str = ""
    last_ok_tag_id: str = ""
    last_ok_row: int = -1
    rewind_active: bool = False
    last_event_id: int = 0
    events: list[dict] = field(default_factory=list)
    stop_flag: threading.Event = field(default_factory=threading.Event)
    worker: threading.Thread | None = None

    def push(self, typ: str, data: dict) -> None:
        self.last_event_id += 1
        # "type" is also used inside row data (uri/text). Avoid key collisions by using "event".
        evt = {"id": self.last_event_id, "event": typ, "ts": time.time(), **data}
        if "type" not in evt:
            evt["type"] = typ  # backward compatibility for older frontend logic
        self.events.append(evt)
        # cap memory
        if len(self.events) > 5000:
            self.events = self.events[-2000:]


STATE = RunState()
APP = FastAPI()

TAP_LOCK = threading.Lock()
TAP_COUNTER = 0

def _escape_html(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _done_count() -> int:
    return sum(1 for s in STATE.statuses if s == "ok")


def _render_table() -> str:
    if not STATE.items:
        return "<p class='muted'>CSV未アップロード</p>"

    body_rows: list[str] = []
    for it in STATE.items:
        st = STATE.statuses[it.index] if it.index < len(STATE.statuses) else "pending"
        cls = "ok" if st == "ok" else ("ng" if st in ("error", "ng") else ("wait" if st == "waiting" else "muted"))
        body_rows.append(
            f"<tr id='row-{it.index}'>"
            f"<td class='muted'>{it.index + 1}</td>"
            f"<td><code>{_escape_html(it.type)}</code></td>"
            f"<td style='word-break:break-all; max-width:400px;'>{_escape_html(it.payload)}</td>"
            f"<td id='status-{it.index}'><span class='status {cls}'>{_escape_html(st)}</span></td>"
            "</tr>"
        )

    return (
        "<div class='card' style='width:100%;'>"
        "<h3><span class='icon'>&#128220;</span> CSV一覧</h3>"
        "<div class='muted' style='margin-bottom:12px;'>pending → waiting → ok / ng</div>"
        "<div id='tableScroll' class='table-wrap'>"
        "<table>"
        "<thead>"
        "<tr>"
        "<th>#</th>"
        "<th>type</th>"
        "<th>payload</th>"
        "<th>status</th>"
        "</tr>"
        "</thead>"
        "<tbody>"
        + "".join(body_rows)
        + "</tbody></table></div></div>"
    )


def _html_page(body: str) -> HTMLResponse:
    return HTMLResponse(
        f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>NFC Writer</title>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
    :root {{
      --bg: #0a0a0f;
      --bg2: #12121a;
      --card: #16161f;
      --card-hover: #1c1c28;
      --border: rgba(255,255,255,0.06);
      --border-light: rgba(255,255,255,0.1);
      --muted: #6b7280;
      --text: #e4e4e7;
      --text-bright: #fafafa;
      --primary: #6366f1;
      --primary-glow: rgba(99,102,241,0.25);
      --primary-light: #818cf8;
      --success: #22c55e;
      --success-bg: rgba(34,197,94,0.1);
      --danger: #ef4444;
      --danger-bg: rgba(239,68,68,0.1);
      --warning: #3b82f6;
      --warning-bg: rgba(59,130,246,0.1);
      --accent: #a78bfa;
    }}
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans JP", sans-serif;
      background: var(--bg);
      color: var(--text);
      min-height: 100vh;
      overflow-x: hidden;
    }}
    .page-bg {{
      position: fixed; top: 0; left: 0; right: 0; bottom: 0; z-index: 0; pointer-events: none;
      background:
        radial-gradient(ellipse 80% 60% at 50% -20%, rgba(99,102,241,0.12) 0%, transparent 60%),
        radial-gradient(ellipse 50% 40% at 80% 50%, rgba(167,139,250,0.06) 0%, transparent 50%);
    }}
    .container {{
      position: relative; z-index: 1;
      max-width: 1100px; margin: 0 auto; padding: 32px 24px;
    }}
    .header {{
      display: flex; align-items: center; gap: 14px; margin-bottom: 32px;
    }}
    .header-icon {{
      width: 44px; height: 44px; border-radius: 14px;
      background: linear-gradient(135deg, var(--primary), var(--accent));
      display: flex; align-items: center; justify-content: center;
      font-size: 22px; box-shadow: 0 0 24px var(--primary-glow);
    }}
    .header h1 {{
      font-size: 22px; font-weight: 700; color: var(--text-bright);
      letter-spacing: -0.02em;
    }}
    .header .subtitle {{
      font-size: 13px; color: var(--muted); font-weight: 400; margin-top: 2px;
    }}
    .row {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
    @media (max-width: 768px) {{ .row {{ grid-template-columns: 1fr; }} }}
    .card {{
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 24px;
      background: var(--card);
      backdrop-filter: blur(12px);
      transition: border-color 0.2s;
    }}
    .card:hover {{ border-color: var(--border-light); }}
    .card h3 {{
      font-size: 15px; font-weight: 600; color: var(--text-bright);
      margin-bottom: 16px; display: flex; align-items: center; gap: 8px;
    }}
    .card h3 .icon {{ font-size: 16px; opacity: 0.7; }}
    .btnRow {{ display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }}
    button {{
      padding: 10px 18px; border-radius: 10px;
      border: 1px solid var(--border-light);
      background: var(--bg2); color: var(--text);
      cursor: pointer; font-weight: 600; font-size: 13px;
      font-family: 'Inter', sans-serif;
      transition: all 0.15s ease;
    }}
    button:hover {{ background: var(--card-hover); border-color: rgba(255,255,255,0.15); }}
    button:active {{ transform: scale(0.97); }}
    button:disabled {{ opacity: .35; cursor: not-allowed; }}
    button.primary {{
      background: var(--primary); color: #fff; border-color: var(--primary);
      box-shadow: 0 0 20px var(--primary-glow);
    }}
    button.primary:hover {{ background: var(--primary-light); }}
    button.danger {{
      background: var(--danger-bg); color: var(--danger); border-color: rgba(239,68,68,0.2);
    }}
    button.danger:hover {{ background: rgba(239,68,68,0.15); }}
    input, select {{
      padding: 10px 14px; border-radius: 10px;
      border: 1px solid var(--border-light);
      background: var(--bg2); color: var(--text);
      font-family: 'Inter', sans-serif; font-size: 13px;
      transition: border-color 0.2s;
    }}
    input:focus, select:focus {{ outline: none; border-color: var(--primary); box-shadow: 0 0 0 3px var(--primary-glow); }}
    code {{ font-family: 'JetBrains Mono', monospace; background: var(--bg2); padding: 2px 8px; border-radius: 6px; font-size: 12px; color: var(--accent); }}
    pre {{
      font-family: 'JetBrains Mono', monospace; font-size: 12px;
      padding: 16px; overflow: auto;
      border: 1px solid var(--border); border-radius: 12px;
      background: var(--bg); color: var(--muted);
      line-height: 1.6;
    }}
    table td, table th {{ border: 0; }}
    .status {{
      display: inline-flex; align-items: center; gap: 6px;
      padding: 4px 12px; border-radius: 999px;
      font-size: 12px; font-weight: 600;
      background: var(--bg2); color: var(--muted);
    }}
    .status.ok {{ background: var(--success-bg); color: var(--success); }}
    .status.ng {{ background: var(--danger-bg); color: var(--danger); }}
    .status.wait {{ background: var(--warning-bg); color: var(--warning); }}
    .muted {{ color: var(--muted); font-size: 13px; }}
    .ok {{ color: var(--success); }}
    .ng {{ color: var(--danger); }}
    .hintBox {{
      margin-top: 14px; padding: 14px 16px; border-radius: 12px;
      border: 1px solid var(--border);
      background: var(--bg2);
    }}
    .hintBox .label {{ font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); margin-bottom: 6px; }}
    .hintBox b {{ color: var(--text-bright); font-size: 14px; }}
    label {{ color: var(--muted); font-size: 13px; }}
    label input[type="radio"] {{ accent-color: var(--primary); margin-right: 6px; }}
    .stat-grid {{
      display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 16px;
    }}
    .stat-item {{
      padding: 12px 14px; border-radius: 10px;
      background: var(--bg2); border: 1px solid var(--border);
    }}
    .stat-item .stat-label {{ font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); margin-bottom: 4px; }}
    .stat-item .stat-value {{ font-size: 18px; font-weight: 700; color: var(--text-bright); font-family: 'JetBrains Mono', monospace; }}
    .stat-item .stat-value.running {{ color: var(--success); }}
    .stat-item .stat-value.stopped {{ color: var(--muted); }}
    .upload-zone {{
      border: 2px dashed var(--border-light); border-radius: 12px;
      padding: 24px; text-align: center; transition: border-color 0.2s;
      cursor: pointer;
    }}
    .upload-zone:hover {{ border-color: var(--primary); }}
    .upload-zone input[type="file"] {{ display: none; }}
    .upload-zone .upload-icon {{ font-size: 28px; margin-bottom: 8px; opacity: 0.5; }}
    .upload-zone .upload-text {{ font-size: 13px; color: var(--muted); }}
    .section-spacer {{ height: 16px; }}

    /* Pulse animation for waiting status */
    @keyframes pulse {{ 0%,100% {{ opacity: 1; }} 50% {{ opacity: 0.5; }} }}
    .status.wait {{ animation: pulse 1.8s ease-in-out infinite; }}

    /* Table styling */
    .table-wrap {{
      max-height: 340px; overflow: auto;
      border: 1px solid var(--border); border-radius: 12px;
      background: var(--bg);
    }}
    .table-wrap::-webkit-scrollbar {{ width: 6px; }}
    .table-wrap::-webkit-scrollbar-track {{ background: transparent; }}
    .table-wrap::-webkit-scrollbar-thumb {{ background: rgba(255,255,255,0.1); border-radius: 3px; }}
    .table-wrap table {{ border-collapse: collapse; width: 100%; }}
    .table-wrap thead tr {{ position: sticky; top: 0; background: var(--card); border-bottom: 1px solid var(--border); }}
    .table-wrap th {{ text-align: left; padding: 12px 14px; font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); font-weight: 600; }}
    .table-wrap td {{ padding: 10px 14px; border-bottom: 1px solid var(--border); font-size: 13px; }}
    .table-wrap tr:last-child td {{ border-bottom: none; }}
    .table-wrap tbody tr {{ transition: background 0.15s; }}
    .table-wrap tbody tr:hover {{ background: rgba(255,255,255,0.02); }}

    /* File input custom */
    .file-label {{
      display: inline-flex; align-items: center; gap: 8px;
      padding: 10px 18px; border-radius: 10px;
      border: 1px solid var(--border-light);
      background: var(--bg2); color: var(--text);
      cursor: pointer; font-weight: 500; font-size: 13px;
      transition: all 0.15s;
    }}
    .file-label:hover {{ border-color: var(--primary); }}
  </style>
  <script>
    let es;
    function setStatus(row, status) {{
      if (row === -1) {{
        const el = document.getElementById("singleStatus");
        if (el) el.textContent = status;
        return;
      }}
      const el = document.getElementById("status-" + row);
      if (!el) return;
      const cls =
        (status === "ok") ? "ok"
        : ((status === "error" || status === "ng") ? "ng"
        : (status === "waiting" ? "wait" : "muted"));
      el.innerHTML = '<span class="status ' + cls + '">' + status + '</span>';
    }}

    function scrollRowIntoView(row) {{
      if (row == null || row < 0) return;
      const container = document.getElementById("tableScroll");
      const tr = document.getElementById("row-" + row);
      if (!container || !tr) return;
      // If the row is below the visible area, scroll down to it.
      const cTop = container.scrollTop;
      const cBottom = cTop + container.clientHeight;
      const rTop = tr.offsetTop;
      const rBottom = rTop + tr.offsetHeight;
      if (rBottom > cBottom - 8) {{
        container.scrollTop = Math.max(0, rBottom - container.clientHeight + 8);
      }}
    }}
    function connectEvents() {{
      if (es) return;
      es = new EventSource("/events");
      es.onmessage = (ev) => {{
        const e = JSON.parse(ev.data);
        const evType = e.event || e.type;
        const log = document.getElementById("log");
        log.textContent += JSON.stringify(e) + "\\n";
        log.scrollTop = log.scrollHeight;
        if (evType === "state") {{
          const runEl = document.getElementById("running");
          runEl.textContent = e.running ? "RUNNING" : "STOPPED";
          runEl.className = "stat-value " + (e.running ? "running" : "stopped");
          document.getElementById("cursor").textContent = e.total ? (Math.min(e.cursor + 1, e.total) + "/" + e.total) : "-";
          const dc = document.getElementById("doneCount");
          if (dc) dc.textContent = (e.done ?? 0) + "/" + e.total;
          const rm = document.getElementById("runModeText");
          if (rm && e.run_mode) rm.textContent = e.run_mode;
          const hint = document.getElementById("hint");
          if (hint) {{
            if (!e.running) hint.textContent = "停止中";
            else hint.textContent = "タグをかざしてください（書き込み後はタグを外して次へ）";
          }}
          if (!e.running) {{ clearInterval(readerPollId); readerPollId = setInterval(checkReader, 3000); }}
        }}
        if (evType === "waiting") {{
          setStatus(e.row, "waiting");
          const hint = document.getElementById("hint");
          if (hint && !hint.textContent.includes("同じタグ")) hint.textContent = "次のタグをかざしてください（前のタグは外す）";
        }}
        // Backward compatibility: older events used "writing" even while waiting for a tag.
        if (evType === "writing") setStatus(e.row, (e.row === -1 ? "writing" : "waiting"));
        if (evType === "ok") {{
          setStatus(e.row, "ok");
          scrollRowIntoView(e.row);
          const hint = document.getElementById("hint");
          if (hint) hint.textContent = "書き込み完了。次のタグをかざしてください";
        }}
        if (evType === "ng") {{
          setStatus(e.row, "ng");
          const hint = document.getElementById("hint");
          if (hint) hint.textContent = "失敗。もう一度かざしてください";
        }}
        if (evType === "error") {{
          setStatus(e.row, "error");
          const hint = document.getElementById("hint");
          if (hint) hint.textContent = "エラー。タグを外してもう一度かざしてください";
        }}
        if (evType === "same_tag") {{
          const hint = document.getElementById("hint");
          if (hint) hint.textContent = "同じタグです。次のタグに替えてください";
        }}
      }};
      es.onerror = () => {{
        // try reconnect
        es.close();
        es = null;
        setTimeout(connectEvents, 1000);
      }};
    }}
    async function post(url, formData) {{
      const r = await fetch(url, {{ method:"POST", body: formData }});
      const ct = (r.headers.get("content-type") || "");
      if (!r.ok) {{
        alert(await r.text());
        return null;
      }}
      if (ct.includes("application/json")) {{
        const j = await r.json();
        if (j && j.ok === false) alert(j.error || "失敗しました");
        return j;
      }}
      return await r.text();
    }}
    // Reader status polling
    async function checkReader() {{
      try {{
        const r = await fetch("/reader_status");
        const j = await r.json();
        const dot = document.getElementById("readerDot");
        const txt = document.getElementById("readerText");
        if (j.connected) {{
          dot.style.background = "var(--success)";
          dot.style.boxShadow = "0 0 8px var(--success)";
          txt.textContent = j.reader_name || "接続中";
          txt.style.color = "var(--success)";
        }} else {{
          dot.style.background = "var(--muted)";
          dot.style.boxShadow = "none";
          txt.textContent = j.mode === "mock" ? "Mock" : "未検出";
          txt.style.color = "var(--muted)";
        }}
      }} catch(e) {{}}
    }}
    let readerPollId = setInterval(checkReader, 10000);
    async function startRun() {{
      const fd = new FormData();
      fd.append("mode", document.getElementById("modeSel").value);
      fd.append("reader_contains", document.getElementById("readerContains").value);
      const rm = document.querySelector('input[name="runMode"]:checked')?.value || "csv";
      fd.append("run_mode", rm);
      fd.append("single_url", document.getElementById("singleUrl")?.value || "");
      clearInterval(readerPollId); // Stop reader polling to avoid PC/SC interference
      await post("/start", fd);
    }}
    async function backOne() {{
      await post("/back", new FormData());
    }}
    async function tapOnce() {{
      await post("/tap", new FormData());
    }}
    async function clearLog() {{
      const log = document.getElementById("log");
      if (log) log.textContent = "";
    }}
    async function stopRun() {{
      await post("/stop", new FormData());
      readerPollId = setInterval(checkReader, 3000); // Resume polling
    }}
    function syncRunModeUI() {{
      const rm = document.querySelector('input[name="runMode"]:checked')?.value || "csv";
      const singleBox = document.getElementById("singleBox");
      const csvBox = document.getElementById("csvBox");
      if (singleBox) singleBox.style.display = (rm === "single") ? "block" : "none";
      if (csvBox) csvBox.style.display = (rm === "csv") ? "block" : "none";
      const t = document.getElementById("runModeText");
      if (t) t.textContent = rm;
    }}
    window.addEventListener("load", () => {{
      connectEvents();
      syncRunModeUI();
      checkReader();
      document.querySelectorAll('input[name="runMode"]').forEach((el) => {{
        el.addEventListener("change", syncRunModeUI);
      }});
    }});
  </script>
</head>
<body>
  <div class="page-bg"></div>
  <div class="container">
    <div class="header">
      <div class="header-icon">&#9889;</div>
      <div>
        <h1>NFC Writer</h1>
        <div class="subtitle">NFC\u30bf\u30b0\u9023\u7d9a\u66f8\u304d\u8fbc\u307f\u30c4\u30fc\u30eb</div>
      </div>
    </div>
    {body}
  </div>
</body>
</html>"""
    )


@APP.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    single_checked = "checked" if STATE.run_mode == "single" else ""
    csv_checked = "checked" if STATE.run_mode == "csv" else ""
    body = f"""
<div class="row">
  <div class="card">
    <h3><span class="icon">&#128196;</span> データ</h3>
    <div style="margin-bottom: 14px;">
      <label style="display:block; margin-bottom:8px;"><input type="radio" name="runMode" value="single" {single_checked} /> 単一URLをずっと書き込む</label>
      <label style="display:block;"><input type="radio" name="runMode" value="csv" {csv_checked} /> CSVを上から順番に書き込む</label>
    </div>
    <div id="singleBox" style="margin-bottom: 14px;">
      <div class="muted" style="margin-bottom:6px;">URL（このURLを毎回書き込み）</div>
      <input id="singleUrl" style="width:100%;"
        placeholder="https://example.com/..." value="{_escape_html(STATE.single_url)}" />
      <div style="height:10px"></div>
      <div class="muted">状態: <b id="singleStatus">-</b></div>
    </div>
    <div id="csvBox">
      <form action="/upload" method="post" enctype="multipart/form-data">
        <div class="upload-zone" onclick="this.querySelector('input').click()">
          <div class="upload-icon">&#128193;</div>
          <div class="upload-text">クリックしてCSVファイルを選択</div>
          <input type="file" name="file" accept=".csv" required onchange="this.closest('form').querySelector('.upload-text').textContent = this.files[0]?.name || 'ファイルを選択'" />
        </div>
        <div style="height:12px"></div>
        <button class="primary" type="submit" style="width:100%;">&#11014; アップロード</button>
      </form>
      <div style="height:8px"></div>
      <div class="muted">CSV列: <code>url</code>（推奨）または <code>payload</code></div>
    </div>
  </div>
  <div class="card">
    <h3><span class="icon">&#9881;</span> コントロール</h3>
    <div class="stat-grid">
      <div class="stat-item">
        <div class="stat-label">ステータス</div>
        <div class="stat-value {"running" if STATE.running else "stopped"}" id="running">{"RUNNING" if STATE.running else "STOPPED"}</div>
      </div>
      <div class="stat-item">
        <div class="stat-label">進捗</div>
        <div class="stat-value" id="cursor">-</div>
      </div>
      <div class="stat-item">
        <div class="stat-label">完了</div>
        <div class="stat-value" id="doneCount">{f"{_done_count()}/{len(STATE.items)}" if STATE.items else "-"}</div>
      </div>
      <div class="stat-item">
        <div class="stat-label">リーダー</div>
        <div class="stat-value" id="readerStatus" style="font-size:13px;">
          <span id="readerDot" style="display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--muted);margin-right:6px;"></span>
          <span id="readerText">未検出</span>
        </div>
      </div>
    </div>
    <div class="hintBox">
      <div class="label">ガイド</div>
      <b id="hint">停止中</b>
    </div>
    <div style="height:14px"></div>
    <div style="display:flex; gap:10px; margin-bottom:10px;">
      <div style="flex:1;">
        <label>モード</label><div style="height:4px"></div>
        <select id="modeSel" style="width:100%;">
          <option value="mock" {"selected" if STATE.mode=="mock" else ""}>Mock（実機なし）</option>
          <option value="pcsc" {"selected" if STATE.mode=="pcsc" else ""}>PC/SC（実機）</option>
        </select>
      </div>
      <div style="flex:1;">
        <label>Reader名</label><div style="height:4px"></div>
        <input id="readerContains" value="{STATE.reader_contains}" style="width:100%;" />
      </div>
    </div>
    <div class="muted" style="margin-bottom:14px;">実行モード: <b id="runModeText" style="color:var(--text-bright);">{STATE.run_mode}</b></div>
    <div class="btnRow">
      <button class="primary" onclick="startRun()" style="flex:1;">&#9654; 開始</button>
      <button class="danger" onclick="stopRun()" style="flex:1;">&#9632; 停止</button>
      <button onclick="backOne()">&#8617; 戻す</button>
      <button onclick="tapOnce()">&#128400; タップ</button>
    </div>
  </div>
</div>
<div class="section-spacer"></div>
{_render_table()}
<div class="section-spacer"></div>
<div class="card" style="width:100%;">
  <h3><span class="icon">&#128203;</span> ログ</h3>
  <div class="btnRow" style="margin-bottom:12px;">
    <button onclick="clearLog()">&#128465; クリア</button>
    <span class="muted" style="margin-left:auto;">ローカルのみ</span>
  </div>
  <pre id="log" style="height: 240px;"></pre>
</div>
"""
    return _html_page(body)


@APP.post("/upload")
async def upload(file: UploadFile = File(...)) -> HTMLResponse:
    raw = await file.read()
    path = f"/tmp/nfc_batch_{int(time.time())}.csv"
    with open(path, "wb") as f:
        f.write(raw)

    items = load_csv(path)
    STATE.items = items
    STATE.cursor = 0
    STATE.statuses = ["pending"] * len(items)
    STATE.push(
        "state",
        {"running": STATE.running, "cursor": STATE.cursor, "total": len(STATE.items), "mode": STATE.mode, "done": 0},
    )
    STATE.push("csv_loaded", {"rows": len(items), "filename": file.filename})
    return _html_page(
        f"<div class='card' style='max-width:480px;'>"
        f"<h3><span class='icon'>&#10004;</span> アップロード完了</h3>"
        f"<p style='color:var(--success); margin-bottom:12px;'>{_escape_html(file.filename or '')}（{len(items)}行）</p>"
        f"<a href='/'><button class='primary'>&#8592; 戻る</button></a>"
        f"</div>"
    )


def _make_writer(mode: Mode, reader_contains: str, forbid_uid_hex: str | None = None):
    if mode == "mock":
        # In web UI, "mock" waits for a manual TAP signal (see _wait_tap).
        return MockWriter(tap_delay_s=0.0)
    return SpringCorePcscWriter(PcscConfig(
        reader_name_contains=reader_contains,
        forbid_uid_hex=forbid_uid_hex,
        stop_check=lambda: STATE.stop_flag.is_set(),
    ))

def _write_one(writer, url: str):
    return writer.write_uri(url, timeout_s=None)

def _wait_tap(stop_flag: threading.Event) -> bool:
    """
    In mock mode, advance only when the operator presses the TAP button.
    Returns False if stopped.
    """
    global TAP_COUNTER
    with TAP_LOCK:
        start = TAP_COUNTER
    while not stop_flag.is_set():
        with TAP_LOCK:
            if TAP_COUNTER > start:
                return True
        time.sleep(0.05)
    return False

def _worker_loop(mode: Mode, reader_contains: str, run_mode: RunMode, single_url: str) -> None:
    writer = _make_writer(mode, reader_contains)
    STATE.push(
        "state",
        {
            "running": True,
            "cursor": STATE.cursor,
            "total": len(STATE.items),
            "mode": mode,
            "done": _done_count(),
            "run_mode": run_mode,
        },
    )

    if run_mode == "single":
        url = (single_url or "").strip()
        while not STATE.stop_flag.is_set():
            STATE.push("writing", {"row": -1, "item_type": "uri", "payload": url})
            STATE.push("waiting", {"row": -1})
            if mode == "mock":
                if not _wait_tap(STATE.stop_flag):
                    break
            import sys
            print(f"[WORKER] calling _write_one url={url[:50]}", file=sys.stderr, flush=True)
            try:
                res = _write_one(writer, url)
            except Exception as e:
                print(f"[WORKER] exception: {e}", file=sys.stderr, flush=True)
                beep_error()
                STATE.push("error", {"row": -1, "message": str(e)})
                time.sleep(0.2)
                continue
            print(f"[WORKER] result: ok={res.ok} msg={res.message}", file=sys.stderr, flush=True)

            if res.ok:
                beep_ok()
                STATE.push("ok", {"row": -1, "message": res.message, "tag_id": res.tag_id})
                # keep looping forever
                STATE.push(
                    "state",
                    {
                        "running": True,
                        "cursor": 0,
                        "total": 0,
                        "mode": mode,
                        "done": 0,
                        "run_mode": run_mode,
                    },
                )
            else:
                beep_error()
                STATE.push("ng", {"row": -1, "message": res.message, "tag_id": res.tag_id})
                time.sleep(0.2)
    else:
        while not STATE.stop_flag.is_set() and STATE.cursor < len(STATE.items):
            it = STATE.items[STATE.cursor]
            if STATE.cursor < len(STATE.statuses):
                STATE.statuses[STATE.cursor] = "waiting"
            STATE.push("waiting", {"row": STATE.cursor, "item_type": it.type, "payload": it.payload})
            if mode == "mock":
                if not _wait_tap(STATE.stop_flag):
                    break
            # Prevent writing the *next* URL onto the same tag as the last success.
            if mode == "pcsc":
                try:
                    writer.cfg.forbid_uid_hex = STATE.last_ok_tag_id if (run_mode == "csv" and STATE.last_ok_tag_id) else None
                except Exception:
                    pass
            try:
                if it.type == "uri":
                    res = writer.write_uri(it.payload, timeout_s=None)
                else:
                    res = writer.write_text(it.payload, timeout_s=None)
            except Exception as e:
                beep_error()
                if STATE.cursor < len(STATE.statuses):
                    STATE.statuses[STATE.cursor] = "error"
                STATE.push("error", {"row": STATE.cursor, "message": str(e)})
                time.sleep(0.2)
                continue

            if res.ok:
                beep_ok()
                if STATE.cursor < len(STATE.statuses):
                    STATE.statuses[STATE.cursor] = "ok"
                STATE.push("ok", {"row": STATE.cursor, "message": res.message, "tag_id": res.tag_id})
                if res.tag_id:
                    STATE.last_ok_tag_id = res.tag_id
                    STATE.last_ok_row = STATE.cursor
                STATE.rewind_active = False
                STATE.cursor += 1
                STATE.push(
                    "state",
                    {
                        "running": True,
                        "cursor": STATE.cursor,
                        "total": len(STATE.items),
                        "mode": mode,
                        "done": _done_count(),
                        "run_mode": run_mode,
                    },
                )
            else:
                if res.message == "SAME_TAG":
                    # Keep waiting on the same row; prompt operator to change tag.
                    if STATE.cursor < len(STATE.statuses):
                        STATE.statuses[STATE.cursor] = "waiting"
                    STATE.push("same_tag", {"row": STATE.cursor, "tag_id": res.tag_id})
                    time.sleep(0.2)
                    continue
                beep_error()
                if STATE.cursor < len(STATE.statuses):
                    STATE.statuses[STATE.cursor] = "ng"
                STATE.push("ng", {"row": STATE.cursor, "message": res.message, "tag_id": res.tag_id})
                time.sleep(0.2)

    STATE.running = False
    STATE.push(
        "state",
        {
            "running": False,
            "cursor": STATE.cursor,
            "total": len(STATE.items),
            "mode": mode,
            "done": _done_count(),
            "run_mode": run_mode,
        },
    )
    if STATE.cursor >= len(STATE.items):
        STATE.push("done", {"total": len(STATE.items)})


@APP.post("/start")
def start(
    mode: Mode = Form("mock"),
    reader_contains: str = Form(""),
    run_mode: RunMode = Form("csv"),
    single_url: str = Form(""),
) -> dict:
    if STATE.running:
        return JSONResponse({"ok": False, "error": "すでに実行中です"}, status_code=400)

    STATE.mode = mode
    STATE.reader_contains = reader_contains
    STATE.run_mode = run_mode
    STATE.single_url = single_url.strip()
    if run_mode == "single":
        if not STATE.single_url:
            return JSONResponse({"ok": False, "error": "単一URLモード: URLを入力してください"}, status_code=400)
    else:
        if not STATE.items:
            return JSONResponse({"ok": False, "error": "CSVモード: CSVをアップロードしてください"}, status_code=400)
        # Always start from top for CSV mode
        STATE.cursor = 0
        STATE.statuses = ["pending"] * len(STATE.items)
        STATE.push(
            "state",
            {
                "running": False,
                "cursor": STATE.cursor,
                "total": len(STATE.items),
                "mode": STATE.mode,
                "done": _done_count(),
                "run_mode": STATE.run_mode,
            },
        )

    STATE.stop_flag.clear()
    STATE.running = True
    STATE.worker = threading.Thread(
        target=_worker_loop,
        args=(mode, reader_contains, run_mode, STATE.single_url),
        daemon=True,
    )
    STATE.worker.start()
    return {"ok": True}


@APP.post("/stop")
def stop() -> dict:
    STATE.stop_flag.set()
    STATE.running = False
    STATE.push("stopped", {})
    STATE.push(
        "state",
        {
            "running": False,
            "cursor": STATE.cursor,
            "total": len(STATE.items),
            "mode": STATE.mode,
            "done": _done_count(),
        },
    )
    return {"ok": True}


@APP.post("/back")
def back() -> dict:
    if STATE.run_mode != "csv":
        return JSONResponse({"ok": False, "error": "CSVモードでのみ使用できます"}, status_code=400)
    if not STATE.items:
        return JSONResponse({"ok": False, "error": "CSVをアップロードしてください"}, status_code=400)
    # Move cursor back by one and mark as pending again.
    STATE.cursor = max(0, STATE.cursor - 1)
    if STATE.cursor < len(STATE.statuses):
        STATE.statuses[STATE.cursor] = "pending"
    STATE.rewind_active = True
    STATE.push("rewind", {"cursor": STATE.cursor})
    STATE.push(
        "state",
        {
            "running": STATE.running,
            "cursor": STATE.cursor,
            "total": len(STATE.items),
            "mode": STATE.mode,
            "done": _done_count(),
            "run_mode": STATE.run_mode,
        },
    )
    return {"ok": True}


@APP.post("/tap")
def tap() -> dict:
    global TAP_COUNTER
    with TAP_LOCK:
        TAP_COUNTER += 1
        cur = TAP_COUNTER
    STATE.push("tap", {"count": cur})
    return {"ok": True, "count": cur}


@APP.get("/reader_status")
def reader_status() -> dict:
    """Return reader status without touching PC/SC (avoids ACR122U interference)."""
    if STATE.running:
        return {"connected": True, "mode": STATE.mode, "reader_name": "書き込み中..."}
    # Never call pyscard readers() from HTTP threads — it corrupts ACR122U state.
    # Just report the selected mode. Actual reader detection happens at write time.
    if STATE.mode == "pcsc":
        return {"connected": True, "mode": "pcsc", "reader_name": "PC/SC"}
    return {"connected": False, "mode": "mock", "reader_name": None}


@APP.get("/events")
def events() -> StreamingResponse:
    def gen():
        last = 0
        # initial snapshot
        yield (
            "data: "
            + json.dumps(
                {
                    "type": "state",
                    "running": STATE.running,
                    "cursor": STATE.cursor,
                    "total": len(STATE.items),
                    "mode": STATE.mode,
                    "done": _done_count(),
                    "run_mode": STATE.run_mode,
                },
                ensure_ascii=False,
            )
            + "\n\n"
        )
        while True:
            if STATE.events and STATE.events[-1]["id"] > last:
                # send all new events
                for e in STATE.events:
                    if e["id"] > last:
                        last = e["id"]
                        yield f"data: {json.dumps(e, ensure_ascii=False)}\n\n"
            time.sleep(0.2)

    return StreamingResponse(gen(), media_type="text/event-stream")

