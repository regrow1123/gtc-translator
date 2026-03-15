"""
GTC 번역 뷰어 — YouTube 영상 + 실시간 번역 동시 표시
"""
import json
import os
import time
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.parse

PORT = 8091
TRANSLATIONS_FILE = Path(__file__).parent / "translations.json"
STATE_FILE = Path(__file__).parent / "state.json"


def get_translations(limit=50):
    if TRANSLATIONS_FILE.exists():
        data = json.loads(TRANSLATIONS_FILE.read_text())
        return data[-limit:]
    return []


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)

        if parsed.path == "/api/toggle-translate":
            auth = self.headers.get("X-Admin-Key", "")
            if auth != "1123":
                self.send_response(403)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"ok": false}')
                return
            # 상태 토글
            state = {}
            if STATE_FILE.exists():
                try:
                    state = json.loads(STATE_FILE.read_text())
                except Exception:
                    pass
            current = state.get("translate", False)
            state["translate"] = not current
            STATE_FILE.write_text(json.dumps(state))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True, "enabled": not current}).encode())
            return

        if parsed.path == "/api/start":
            import subprocess
            # 관리자 인증
            auth = self.headers.get("X-Admin-Key", "")
            if auth != "1123":
                self.send_response(403)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"ok": false, "message": "forbidden"}')
                return
            content_length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(content_length)) if content_length else {}
            url = body.get("url", "")
            if not url:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"ok": false, "message": "URL required"}')
                return
            # 기존 프로세스 종료
            subprocess.run(["pkill", "-f", "translate.py"], capture_output=True)
            time.sleep(1)
            # translations.json 초기화
            Path(__file__).parent.joinpath("translations.json").write_text("[]")
            # 새 프로세스 시작
            env = os.environ.copy()
            env["LD_LIBRARY_PATH"] = "/home/sund4y/stable-diffusion-webui/venv/lib/python3.11/site-packages/torch/lib"
            env["PYTHONUNBUFFERED"] = "1"
            env["PATH"] = f"{os.environ['HOME']}/.deno/bin:{env['PATH']}"
            env["OPENCLAW_TOKEN"] = os.environ.get("OPENCLAW_TOKEN", "")
            subprocess.Popen(
                ["python3", str(Path(__file__).parent / "translate.py"), url],
                env=env,
                stdout=open("/tmp/gtc_translate.log", "w"),
                stderr=subprocess.STDOUT,
            )
            # YouTube 영상 ID 추출
            video_id = ""
            if "v=" in url:
                video_id = url.split("v=")[1].split("&")[0]
            elif "youtu.be/" in url:
                video_id = url.split("youtu.be/")[1].split("?")[0]
            # 상태 저장
            STATE_FILE.write_text(json.dumps({"video_id": video_id, "running": True}))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True, "video_id": video_id}).encode())
            return

        if parsed.path == "/api/stop":
            import subprocess
            auth = self.headers.get("X-Admin-Key", "")
            if auth != "1123":
                self.send_response(403)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"ok": false, "message": "forbidden"}')
                return
            subprocess.run(["pkill", "-f", "translate.py"], capture_output=True)
            # state 업데이트
            if STATE_FILE.exists():
                try:
                    state = json.loads(STATE_FILE.read_text())
                    state["running"] = False
                    STATE_FILE.write_text(json.dumps(state))
                except Exception:
                    pass
            # 웹에서 다운로드 가능하므로 별도 전송 불필요
            # MD/TXT 버튼으로 다운로드
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok": true, "message": "stopped"}')
            return

        if parsed.path == "/api/state":
            state = {}
            if STATE_FILE.exists():
                try:
                    state = json.loads(STATE_FILE.read_text())
                except Exception:
                    pass
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(state).encode())
            return

        if parsed.path == "/api/translations":
            # JSON API — 번역 데이터
            data = get_translations()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode())
            return

        if parsed.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return

        # 메인 페이지
        params = urllib.parse.parse_qs(parsed.query)
        video_id = params.get("v", [""])[0]

        # v 파라미터 없으면 state에서 가져오기
        if not video_id and STATE_FILE.exists():
            try:
                state = json.loads(STATE_FILE.read_text())
                video_id = state.get("video_id", "")
            except Exception:
                pass

        html = build_html(video_id)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode())

    def do_POST(self):
        return self.do_GET()

    def log_message(self, fmt, *args):
        pass


def build_html(video_id=""):
    youtube_embed = ""
    if video_id:
        youtube_embed = f'<iframe src="https://www.youtube.com/embed/{video_id}?autoplay=1" frameborder="0" allowfullscreen allow="autoplay"></iframe>'
    else:
        youtube_embed = '<div class="no-video">URL에 ?v=VIDEO_ID 추가</div>'

    return f"""<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>GTC Live Translator</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&display=swap');
  @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;700&display=swap');

  :root {{
    --bg: #0a0a12;
    --surface: #12121e;
    --border: #1e1e30;
    --accent: #76b900;
    --text: #e0e0e0;
    --text-dim: #6b7280;
    --kr: #76b900;
    --en: #888;
  }}

  * {{ margin: 0; padding: 0; box-sizing: border-box; }}

  body {{
    background: var(--bg);
    color: var(--text);
    font-family: 'Noto Sans KR', 'JetBrains Mono', sans-serif;
    height: 100vh;
    overflow: hidden;
  }}

  .container {{
    display: flex;
    height: 100vh;
  }}

  .video-panel {{
    flex: 1;
    min-width: 200px;
  }}

  .divider {{
    width: 6px;
    background: var(--border);
    cursor: col-resize;
    transition: background 0.2s;
    flex-shrink: 0;
  }}

  .divider:hover, .divider.active {{
    background: var(--accent);
  }}

  .translation-panel {{
    flex: 1;
    min-width: 200px;
  }}

  /* 왼쪽: 영상 */
  .video-panel {{
    background: #000;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }}

  .video-panel iframe {{
    width: 100%;
    flex: 1;
  }}

  .no-video {{
    display: flex;
    align-items: center;
    justify-content: center;
    height: 100%;
    color: var(--text-dim);
    font-size: 18px;
  }}

  /* 오른쪽: 번역 */
  .translation-panel {{
    display: flex;
    flex-direction: column;
    height: 100vh;
    min-height: 0;
  }}

  .panel-header {{
    padding: 12px 20px;
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    display: flex;
    align-items: center;
    justify-content: space-between;
  }}

  .panel-title {{
    font-size: 14px;
    font-weight: 700;
    color: var(--accent);
    font-family: 'JetBrains Mono', monospace;
  }}

  .live-badge {{
    background: #e53e3e;
    color: #fff;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 11px;
    font-weight: 700;
    animation: pulse 2s infinite;
  }}

  @keyframes pulse {{
    0%, 100% {{ opacity: 1; }}
    50% {{ opacity: 0.5; }}
  }}

  .save-btn {{
    background: var(--surface);
    border: 1px solid var(--border);
    color: var(--text-dim);
    padding: 2px 10px;
    border-radius: 4px;
    cursor: pointer;
    font-size: 11px;
    font-family: 'JetBrains Mono', monospace;
    margin-right: 6px;
    transition: all 0.2s;
  }}

  .save-btn:hover {{
    background: var(--accent);
    color: #000;
    border-color: var(--accent);
  }}

  .url-input {{
    background: var(--bg);
    border: 1px solid var(--border);
    color: var(--text);
    padding: 3px 10px;
    border-radius: 4px;
    font-size: 11px;
    font-family: 'JetBrains Mono', monospace;
    width: 220px;
    outline: none;
  }}

  .url-input:focus {{
    border-color: var(--accent);
  }}

  .start-btn {{
    border-color: var(--accent);
    color: var(--accent);
  }}

  .start-btn:hover {{
    background: var(--accent);
    color: #000;
    border-color: var(--accent);
  }}

  .stop-btn {{
    border-color: #e53e3e;
    color: #e53e3e;
  }}

  .stop-btn:hover {{
    background: #e53e3e;
    color: #fff;
    border-color: #e53e3e;
  }}

  .translate-btn {{
    border-color: #f59e0b;
    color: #f59e0b;
  }}

  .translate-btn:hover {{
    background: #f59e0b;
    color: #000;
    border-color: #f59e0b;
  }}

  .translate-btn.active {{
    background: #f59e0b;
    color: #000;
    border-color: #f59e0b;
  }}

  .admin-only {{
    opacity: 0.3;
    pointer-events: none;
  }}

  .admin-only.unlocked {{
    opacity: 1;
    pointer-events: auto;
  }}

  .admin-login-btn {{
    border-color: #8b5cf6;
    color: #8b5cf6;
  }}

  .admin-login-btn:hover {{
    background: #8b5cf6;
    color: #fff;
  }}

  .admin-login-btn.active {{
    background: #8b5cf6;
    color: #fff;
    border-color: #8b5cf6;
  }}

  .translations {{
    flex: 1;
    overflow-y: auto;
    padding: 16px;
    scroll-behavior: smooth;
    min-height: 0;
  }}

  .segment {{
    margin-bottom: 20px;
    padding: 14px 16px;
    background: var(--surface);
    border-radius: 10px;
    border-left: 3px solid var(--accent);
    animation: slideIn 0.3s ease;
  }}

  @keyframes slideIn {{
    from {{ opacity: 0; transform: translateX(20px); }}
    to {{ opacity: 1; transform: translateX(0); }}
  }}

  .seg-time {{
    font-size: 11px;
    color: var(--text-dim);
    font-family: 'JetBrains Mono', monospace;
    margin-bottom: 8px;
  }}

  .seg-kr {{
    font-size: 15px;
    line-height: 1.7;
    color: var(--text);
    margin-bottom: 10px;
  }}

  .seg-en {{
    font-size: 12px;
    line-height: 1.5;
    color: var(--en);
    font-style: italic;
    border-top: 1px solid var(--border);
    padding-top: 8px;
  }}

  .seg-live {{
    opacity: 0.6;
    border-left-color: var(--text-dim);
    border-left-style: dashed;
  }}

  .seg-en-only {{
    font-size: 14px;
    color: var(--text);
    font-style: normal;
    border-top: none;
    padding-top: 0;
  }}

  .status-bar {{
    padding: 8px 20px;
    background: var(--surface);
    border-top: 1px solid var(--border);
    font-size: 11px;
    color: var(--text-dim);
    font-family: 'JetBrains Mono', monospace;
    display: flex;
    justify-content: space-between;
  }}

  .status-dot {{
    display: inline-block;
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--accent);
    margin-right: 6px;
    animation: pulse 2s infinite;
  }}

  /* 스크롤바 */
  .translations::-webkit-scrollbar {{ width: 4px; }}
  .translations::-webkit-scrollbar-track {{ background: var(--bg); }}
  .translations::-webkit-scrollbar-thumb {{ background: var(--border); border-radius: 2px; }}

  /* 모바일 */
  @media (max-width: 768px) {{
    .container {{
      flex-direction: column;
    }}
    .video-panel {{
      height: 40vh;
      flex: none;
      min-width: 0;
    }}
    .divider {{
      display: none;
    }}
    .translation-panel {{
      flex: 1;
      min-width: 0;
      height: auto;
    }}
  }}
</style>
</head><body>

<div class="container">
  <div class="video-panel" id="videoPanel">
    {youtube_embed}
  </div>

  <div class="divider" id="divider"></div>

  <div class="translation-panel" id="transPanel">
    <div class="panel-header">
      <span class="panel-title">LIVE TRANSLATION</span>
      <div>
        <input type="text" id="urlInput" class="url-input admin-only" placeholder="YouTube URL..." disabled />
        <button class="save-btn start-btn admin-only" onclick="startTranslation()" disabled>START</button>
        <button class="save-btn stop-btn admin-only" onclick="stopTranslation()" disabled>STOP</button>
        <button class="save-btn translate-btn admin-only" id="translateBtn" onclick="toggleTranslate()" disabled>TRANSLATE: OFF</button>
        <button class="save-btn" onclick="saveTxt()">SAVE</button>
        <button class="save-btn admin-login-btn" id="adminBtn" onclick="toggleAdmin()">ADMIN</button>
        <span class="live-badge" id="liveBadge">READY</span>
      </div>
    </div>

    <div class="translations" id="translations"></div>

    <div class="status-bar">
      <div><span class="status-dot"></span>Connected</div>
      <div id="count">0 segments</div>
    </div>
  </div>
</div>

<script>
  let lastCount = 0;

  async function fetchTranslations() {{
    try {{
      const r = await fetch('/api/translations');
      const data = await r.json();

      // 상태 업데이트
      const badge = document.getElementById('liveBadge');
      try {{
        const sr = await fetch('/api/state');
        const st = await sr.json();
        if (st.running) {{
          badge.textContent = 'LIVE';
          badge.style.background = '#e53e3e';
        }} else if (data.length > 0) {{
          badge.textContent = 'ENDED';
          badge.style.background = '#6b7280';
        }} else {{
          badge.textContent = 'READY';
          badge.style.background = '#6b7280';
        }}
      }} catch(e) {{}}

      if (data.length !== lastCount) {{
        allData = data;
        const container = document.getElementById('translations');
        container.innerHTML = data.map(d => `
          <div class="segment ${{d.live ? 'seg-live' : ''}}">
            <div class="seg-time">${{d.time}}</div>
            ${{d.kr ? `<div class="seg-kr">${{d.kr}}</div>` : ''}}
            <div class="seg-en ${{d.kr ? '' : 'seg-en-only'}}">${{d.en}}</div>
          </div>
        `).join('');

        container.scrollTop = container.scrollHeight;
        document.getElementById('count').textContent = data.length + ' segments';
        lastCount = data.length;
      }}
    }} catch(e) {{}}
  }}

  let allData = [];

  function saveFile(content, filename) {{
    const blob = new Blob([content], {{ type: 'text/plain;charset=utf-8' }});
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    a.click();
  }}

  function saveMarkdown() {{
    let md = '# Live Translation\\n\\n';
    allData.forEach(d => {{
      md += `### ${{d.time}}\\n\\n`;
      md += `**KR:** ${{d.kr}}\\n\\n`;
      md += `**EN:** ${{d.en}}\\n\\n---\\n\\n`;
    }});
    saveFile(md, 'translation_' + new Date().toISOString().slice(0,10) + '.md');
  }}

  function saveTxt() {{
    let txt = '';
    allData.forEach(d => {{
      if (d.live) return;
      if (d.kr) txt += `${{d.kr}}\\n`;
      txt += `${{d.en}}\\n\\n`;
    }});
    saveFile(txt, 'translation_' + new Date().toISOString().slice(0,10) + '.txt');
  }}

  let isAdmin = false;

  function toggleAdmin() {{
    if (isAdmin) {{
      isAdmin = false;
      document.querySelectorAll('.admin-only').forEach(el => {{
        el.classList.remove('unlocked');
        el.disabled = true;
      }});
      document.getElementById('adminBtn').classList.remove('active');
      document.getElementById('adminBtn').textContent = 'ADMIN';
      return;
    }}
    const pw = prompt('관리자 암호:');
    if (pw === '1123') {{
      isAdmin = true;
      document.querySelectorAll('.admin-only').forEach(el => {{
        el.classList.add('unlocked');
        el.disabled = false;
      }});
      document.getElementById('adminBtn').classList.add('active');
      document.getElementById('adminBtn').textContent = 'ADMIN ON';
    }} else if (pw !== null) {{
      alert('잘못된 암호');
    }}
  }}

  async function toggleTranslate() {{
    try {{
      const r = await fetch('/api/toggle-translate', {{
        method: 'POST',
        headers: {{ 'X-Admin-Key': '1123' }}
      }});
      const data = await r.json();
      const btn = document.getElementById('translateBtn');
      if (data.enabled) {{
        btn.textContent = 'TRANSLATE: ON';
        btn.classList.add('active');
      }} else {{
        btn.textContent = 'TRANSLATE: OFF';
        btn.classList.remove('active');
      }}
    }} catch(e) {{}}
  }}

  async function startTranslation() {{
    const url = document.getElementById('urlInput').value.trim();
    if (!url) {{ alert('YouTube URL을 입력하세요'); return; }}
    if (!confirm('번역을 시작할까요?')) return;

    try {{
      const r = await fetch('/api/start', {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json', 'X-Admin-Key': '1123' }},
        body: JSON.stringify({{ url }})
      }});
      const data = await r.json();
      if (data.ok) {{
        document.getElementById('liveBadge').textContent = 'LIVE';
        document.getElementById('liveBadge').style.background = '#e53e3e';
        // 영상 업데이트
        if (data.video_id) {{
          const vp = document.getElementById('videoPanel');
          vp.innerHTML = '<iframe src="https://www.youtube.com/embed/' + data.video_id + '?autoplay=1" frameborder="0" allowfullscreen allow="autoplay"></iframe>';
        }}
        lastCount = 0;
      }}
    }} catch(e) {{ alert('시작 실패: ' + e); }}
  }}

  async function stopTranslation() {{
    if (!confirm('번역을 종료할까요?')) return;
    try {{
      await fetch('/api/stop', {{ headers: {{ 'X-Admin-Key': '1123' }} }});
      document.getElementById('liveBadge').textContent = 'STOPPED';
      document.getElementById('liveBadge').style.background = '#6b7280';
    }} catch(e) {{}}
  }}

  // 초기 상태 확인
  async function checkState() {{
    try {{
      const r = await fetch('/api/state');
      const state = await r.json();
      const badge = document.getElementById('liveBadge');
      if (state.running) {{
        badge.textContent = 'LIVE';
        badge.style.background = '#e53e3e';
      }}
    }} catch(e) {{}}
  }}

  checkState();
  fetchTranslations();
  setInterval(fetchTranslations, 3000);

  // 리사이즈 드래그
  const divider = document.getElementById('divider');
  const videoPanel = document.getElementById('videoPanel');
  const transPanel = document.getElementById('transPanel');
  let isDragging = false;

  divider.addEventListener('mousedown', (e) => {{
    isDragging = true;
    divider.classList.add('active');
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
    e.preventDefault();
  }});

  document.addEventListener('mousemove', (e) => {{
    if (!isDragging) return;
    const containerWidth = document.querySelector('.container').offsetWidth;
    const ratio = e.clientX / containerWidth;
    const clamped = Math.max(0.2, Math.min(0.8, ratio));
    videoPanel.style.flex = 'none';
    videoPanel.style.width = (clamped * 100) + '%';
    transPanel.style.flex = '1';
  }});

  document.addEventListener('mouseup', () => {{
    if (isDragging) {{
      isDragging = false;
      divider.classList.remove('active');
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    }}
  }});
</script>
</body></html>"""


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"GTC Viewer: http://localhost:{PORT}?v=VIDEO_ID")
    server.serve_forever()
