"""
GTC 키노트 실시간 번역기
YouTube 오디오 스트림 → faster-whisper STT → OpenClaw 번역 → 텔레그램 전송
"""
import subprocess
import time
import os
import sys
import json
import requests
import numpy as np
from pathlib import Path
from datetime import datetime
from faster_whisper import WhisperModel

# === 설정 ===
OPENCLAW_URL = os.environ.get("OPENCLAW_URL", "http://127.0.0.1:18789/v1/responses")
OPENCLAW_TOKEN = os.environ.get("OPENCLAW_TOKEN", "")
LOG_FILE = Path(__file__).parent / "translation_log.md"

# STT 설정
CHUNK_SECONDS = 10
MIN_CHARS = 15
BUFFER_SECONDS = 30
MAX_CONTEXT_HISTORY = 3  # 이전 번역 컨텍스트 유지 개수

# CUDA
os.environ["LD_LIBRARY_PATH"] = "/home/sund4y/stable-diffusion-webui/venv/lib/python3.11/site-packages/torch/lib"
os.environ["PATH"] = f"{os.environ['HOME']}/.deno/bin:{os.environ['PATH']}"



translation_history = []  # 이전 번역 저장


def translate_openclaw(text):
    """OpenClaw Gateway 경유 번역 (컨텍스트 유지)"""
    context = ""
    if translation_history:
        recent = translation_history[-MAX_CONTEXT_HISTORY:]
        context = "이전 번역 내용 (문맥 참고용):\n"
        context += "\n".join([f"- {t}" for t in recent])
        context += "\n\n"

    headers = {
        "Authorization": f"Bearer {OPENCLAW_TOKEN}",
        "Content-Type": "application/json",
    }
    data = {
        "model": "openclaw:opus-4-6",
        "input": (
            "다음은 실시간 음성 인식된 영어 텍스트야. "
            "자연스러운 한국어로 번역해. "
            "기술 용어는 원문 병기 (예: 블랙웰(Blackwell)). "
            "간결하게. 번역만 출력.\n\n"
            f"{context}"
            f"{text}"
        ),
    }
    try:
        r = requests.post(OPENCLAW_URL, headers=headers, json=data, timeout=30)
        result = r.json()
        output = result.get("output", [])
        for item in output:
            if item.get("type") == "message":
                for content in item.get("content", []):
                    if content.get("type") == "output_text":
                        return content.get("text", "")
        return None
    except Exception as e:
        print(f"[번역 실패] {e}")
        return None


TRANSLATIONS_JSON = Path(__file__).parent / "translations.json"


def log_translation(original, translated, timestamp):
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"\n### {timestamp}\n")
        f.write(f"**EN:** {original}\n\n")
        f.write(f"**KR:** {translated}\n\n---\n")

    # JSON으로도 저장 (웹 뷰어용)
    data = []
    if TRANSLATIONS_JSON.exists():
        try:
            data = json.loads(TRANSLATIONS_JSON.read_text())
        except Exception:
            data = []
    entry = {"time": timestamp, "en": original}
    if translated:
        entry["kr"] = translated
    data.append(entry)
    TRANSLATIONS_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def main():
    if len(sys.argv) < 2:
        print("사용법: python translate.py <YouTube_URL>")
        sys.exit(1)

    youtube_url = sys.argv[1]

    # Whisper 모델 로딩
    print("[STT] faster-whisper 모델 로딩...")
    model = WhisperModel("large-v3", device="cuda", compute_type="float16")
    print("[STT] 로딩 완료")

    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    # 로그 파일 초기화
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        f.write(f"# 실시간 번역 로그\n시작: {now}\nURL: {youtube_url}\n\n---\n")

    # yt-dlp → ffmpeg → PCM 스트림
    print("[스트림] 오디오 추출 시작...")
    yt_cmd = [
        "yt-dlp", "-f", "91",
        "-o", "-", "--no-warnings", youtube_url,
    ]
    ff_cmd = [
        "ffmpeg", "-i", "pipe:0",
        "-f", "s16le", "-acodec", "pcm_s16le",
        "-ar", "16000", "-ac", "1",
        "-loglevel", "quiet", "-",
    ]

    yt_proc = subprocess.Popen(yt_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    ff_proc = subprocess.Popen(ff_cmd, stdin=yt_proc.stdout, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    CHUNK_SIZE = 16000 * 2 * CHUNK_SECONDS
    text_buffer = []
    last_send = time.time()
    segment_count = 0
    stream_start = time.time()
    chunks_read = 0

    print("[실행] 실시간 번역 시작 (Ctrl+C로 종료)")

    try:
        while True:
            data = ff_proc.stdout.read(CHUNK_SIZE)
            if not data:
                print("[종료] 스트림 끝")
                break

            chunks_read += 1
            elapsed_sec = chunks_read * CHUNK_SECONDS
            audio = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
            segments, _ = model.transcribe(audio, language="en", beam_size=3)
            text = " ".join([s.text.strip() for s in segments])

            if text and len(text) >= 5:
                # 이전 청크와 중복 제거
                if text_buffer and text_buffer[-1] == text:
                    continue
                text_buffer.append(text)
                print(f"[STT] {text}")

            elapsed = time.time() - last_send
            combined = " ".join(text_buffer)

            if elapsed >= BUFFER_SECONDS and combined and len(combined) >= MIN_CHARS:
                segment_count += 1
                # 서버 시간 + 영상 경과 시간
                h, m, s = elapsed_sec // 3600, (elapsed_sec % 3600) // 60, elapsed_sec % 60
                timestamp = f"{datetime.now().strftime('%H:%M:%S')} ({int(h):02d}:{int(m):02d}:{int(s):02d})"

                # 번역 활성화 여부 확인
                translate_enabled = False
                state_file = Path(__file__).parent / "state.json"
                if state_file.exists():
                    try:
                        state = json.loads(state_file.read_text())
                        translate_enabled = state.get("translate", False)
                    except Exception:
                        pass

                if translate_enabled:
                    print(f"[번역 중] ({len(combined)} chars)...")
                    translated = translate_openclaw(combined)
                    if translated:
                        translation_history.append(translated)
                        log_translation(combined, translated, timestamp)
                        print(f"[번역] {translated[:80]}...")
                else:
                    # STT 원문만 저장
                    log_translation(combined, "", timestamp)
                    print(f"[원문] {combined[:80]}...")

                text_buffer = []
                last_send = time.time()

    except KeyboardInterrupt:
        print("\n[중단] 사용자 중단")
    finally:
        ff_proc.terminate()
        yt_proc.terminate()
        print(f"[완료] 총 {segment_count}개 세그먼트 번역")

        # state 업데이트
        state_file = Path(__file__).parent / "state.json"
        if state_file.exists():
            try:
                state = json.loads(state_file.read_text())
                state["running"] = False
                state_file.write_text(json.dumps(state))
            except Exception:
                pass

        # 종료 신호 파일 생성
        done_file = Path(__file__).parent / "DONE"
        done_file.write_text(f"completed: {datetime.now().isoformat()}\nsegments: {segment_count}\n")

        # 자동 이메일 전송
        import subprocess as sp
        log_file = Path(__file__).parent / "translation_log.md"
        if log_file.exists() and segment_count > 0:
            sp.run([
                "gog", "gmail", "send",
                "--to", "sund4y1123@gmail.com",
                "--subject", f"번역 완료 ({segment_count}개 세그먼트, {datetime.now().strftime('%Y-%m-%d %H:%M')})",
                "--body", "스트림 종료. 번역 로그 첨부.",
                "--attach", str(log_file),
            ], capture_output=True)


if __name__ == "__main__":
    main()
