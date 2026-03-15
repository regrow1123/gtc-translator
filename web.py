"""
GTC 번역 뷰어 — YouTube 영상 + 실시간 번역 동시 표시
"""
import json
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.parse

PORT = 8091
TRANSLATIONS_FILE = Path(__file__).parent / "translations.json"


def get_translations(limit=50):
    if TRANSLATIONS_FILE.exists():
        data = json.loads(TRANSLATIONS_FILE.read_text())
        return data[-limit:]
    return []


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)

        if parsed.path == "/api/stop":
            # 번역 프로세스 종료
            import subprocess
            subprocess.run(["pkill", "-f", "translate.py"], capture_output=True)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok": true, "message": "stopped"}')
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

        html = build_html(video_id)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode())

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

  .stop-btn {{
    border-color: #e53e3e;
    color: #e53e3e;
  }}

  .stop-btn:hover {{
    background: #e53e3e;
    color: #fff;
    border-color: #e53e3e;
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
        <button class="save-btn" onclick="saveMarkdown()">MD</button>
        <button class="save-btn" onclick="saveTxt()">TXT</button>
        <button class="save-btn stop-btn" onclick="stopTranslation()">STOP</button>
        <span class="live-badge" id="liveBadge">LIVE</span>
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

      if (data.length !== lastCount) {{
        allData = data;
        const container = document.getElementById('translations');
        container.innerHTML = data.map(d => `
          <div class="segment">
            <div class="seg-time">${{d.time}}</div>
            <div class="seg-kr">${{d.kr}}</div>
            <div class="seg-en">${{d.en}}</div>
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
      txt += `[${{d.time}}]\\n${{d.kr}}\\n${{d.en}}\\n\\n`;
    }});
    saveFile(txt, 'translation_' + new Date().toISOString().slice(0,10) + '.txt');
  }}

  async function stopTranslation() {{
    if (!confirm('번역을 종료할까요?')) return;
    try {{
      await fetch('/api/stop');
      document.getElementById('liveBadge').textContent = 'STOPPED';
      document.getElementById('liveBadge').style.background = '#6b7280';
    }} catch(e) {{}}
  }}

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
