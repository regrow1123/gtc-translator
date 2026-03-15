"""
GTC 키노트 실시간 번역기
YouTube 오디오 스트림 → faster-whisper STT → OpenClaw 번역 → 웹 뷰어
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

    if not OPENCLAW_TOKEN:
        print("[경고] OPENCLAW_TOKEN 미설정 — 번역 기능 사용 불가 (STT만 동작)")

    # Whisper 모델 로딩
    print("[STT] faster-whisper 모델 로딩...")
    model = WhisperModel("large-v3", device="cuda", compute_type="float16")
    print("[STT] 로딩 완료")

    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    # 로그 파일 초기화
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        f.write(f"# 실시간 번역 로그\n시작: {now}\nURL: {youtube_url}\n\n---\n")

    # 메타데이터 + 포맷 확인
    print("[포맷] 확인 중...")

    # 스트림 시작 시간 가져오기
    stream_start_ts = 0
    meta_result = subprocess.run(
        ["yt-dlp", "--dump-json", "--no-warnings", youtube_url],
        capture_output=True, text=True
    )
    try:
        meta = json.loads(meta_result.stdout)
        stream_start_ts = meta.get("release_timestamp", 0) or meta.get("timestamp", 0) or 0
        if stream_start_ts:
            print(f"[스트림 시작] {datetime.fromtimestamp(stream_start_ts).strftime('%Y-%m-%d %H:%M:%S')}")
    except Exception:
        pass

    fmt_result = subprocess.run(
        ["yt-dlp", "--list-formats", "--no-warnings", youtube_url],
        capture_output=True, text=True
    )
    fmt_output = fmt_result.stdout
    if "audio only" in fmt_output:
        audio_format = "bestaudio"
        print("[포맷] 오디오 전용 포맷 사용")
    else:
        audio_format = "worst"  # 가장 작은 영상+오디오
        print("[포맷] 최저화질 포맷 사용 (오디오 추출)")

    # yt-dlp → ffmpeg → PCM 스트림
    print("[스트림] 오디오 추출 시작...")
    yt_cmd = [
        "yt-dlp", "-f", audio_format,
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

    print("[실행] 실시간 번역 시작 (Ctrl+C로 종료)")

    try:
        while True:
            data = ff_proc.stdout.read(CHUNK_SIZE)
            if not data:
                print("[종료] 스트림 끝")
                break

            audio = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
            segments, _ = model.transcribe(
                audio, language="en", beam_size=3,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 500},
            )
            text = " ".join([s.text.strip() for s in segments])

            if text and len(text) >= 5:
                # 이전 청크와 중복 제거
                if text_buffer and text_buffer[-1] == text:
                    continue
                text_buffer.append(text)
                print(f"[STT] {text}")

                # 원문 즉시 웹에 표시
                now_stt = datetime.now().strftime('%H:%M:%S')
                stt_data = []
                if TRANSLATIONS_JSON.exists():
                    try:
                        stt_data = json.loads(TRANSLATIONS_JSON.read_text())
                    except Exception:
                        stt_data = []
                stt_data.append({"time": now_stt, "en": text, "live": True})
                TRANSLATIONS_JSON.write_text(json.dumps(stt_data, ensure_ascii=False))

            time_since_send = time.time() - last_send
            combined = " ".join(text_buffer)

            # 30초 경과 + 문장 끝에서 끊기, 최대 45초 대기
            ends_with_sentence = combined and combined.rstrip()[-1:] in (".","?","!")
            time_ok = time_since_send >= BUFFER_SECONDS
            force_send = time_since_send >= BUFFER_SECONDS + 15  # 최대 45초
            if combined and len(combined) >= MIN_CHARS and ((time_ok and ends_with_sentence) or force_send):
                segment_count += 1
                # 서버 시간 + 영상 내 경과 시간 (24시간 이내만)
                now_str = datetime.now().strftime('%H:%M:%S')
                if stream_start_ts:
                    stream_elapsed = int(time.time() - stream_start_ts)
                    if stream_elapsed < 86400:  # 24시간 미만
                        h, m, s = stream_elapsed // 3600, (stream_elapsed % 3600) // 60, stream_elapsed % 60
                        timestamp = f"{now_str} ({int(h):02d}:{int(m):02d}:{int(s):02d})"
                    else:
                        timestamp = now_str  # 상시 라이브 → 서버 시간만
                else:
                    timestamp = now_str

                # 번역 활성화 여부 확인
                translate_enabled = False
                state_file = Path(__file__).parent / "state.json"
                if state_file.exists():
                    try:
                        state = json.loads(state_file.read_text())
                        translate_enabled = state.get("translate", False)
                    except Exception:
                        pass

                # live 청크 제거 → 확정 세그먼트로 교체
                confirmed_data = []
                if TRANSLATIONS_JSON.exists():
                    try:
                        confirmed_data = json.loads(TRANSLATIONS_JSON.read_text())
                    except Exception:
                        confirmed_data = []
                confirmed_data = [d for d in confirmed_data if not d.get("live")]

                if translate_enabled:
                    print(f"[번역 중] ({len(combined)} chars)...")
                    translated = translate_openclaw(combined)
                    if translated:
                        translation_history.append(translated)
                        confirmed_data.append({"time": timestamp, "en": combined, "kr": translated})
                        log_translation(combined, translated, timestamp)
                        print(f"[번역] {translated[:80]}...")
                    else:
                        confirmed_data.append({"time": timestamp, "en": combined})
                        log_translation(combined, "", timestamp)
                else:
                    confirmed_data.append({"time": timestamp, "en": combined})
                    log_translation(combined, "", timestamp)
                    print(f"[원문] {combined[:80]}...")

                TRANSLATIONS_JSON.write_text(json.dumps(confirmed_data, ensure_ascii=False, indent=2))

                text_buffer = []
                last_send = time.time()

    except KeyboardInterrupt:
        print("\n[중단] 사용자 중단")
        ff_proc.terminate()
        yt_proc.terminate()
        return segment_count, False
    
    ff_proc.terminate()
    yt_proc.terminate()

    # 스트림이 아직 라이브인지 확인
    print("[확인] 스트림 상태 확인 중...")
    check = subprocess.run(
        ["yt-dlp", "--dump-json", "--no-warnings", youtube_url],
        capture_output=True, text=True
    )
    try:
        meta = json.loads(check.stdout)
        still_live = meta.get("is_live", False)
    except Exception:
        still_live = False

    if still_live:
        print(f"[재연결] 스트림 아직 라이브 — 5초 후 재시작 (세그먼트: {segment_count}개)")
        time.sleep(5)
        return segment_count, True
    else:
        print(f"[완료] 스트림 종료 확인 — 총 {segment_count}개 세그먼트")
        return segment_count, False


def cleanup(total_segments):
    """종료 시 정리: state 업데이트 + DONE 파일 + 이메일"""
    state_file = Path(__file__).parent / "state.json"
    if state_file.exists():
        try:
            state = json.loads(state_file.read_text())
            state["running"] = False
            state_file.write_text(json.dumps(state))
        except Exception:
            pass

    done_file = Path(__file__).parent / "DONE"
    done_file.write_text(f"completed: {datetime.now().isoformat()}\nsegments: {total_segments}\n")

    log_file = Path(__file__).parent / "translation_log.md"
    if log_file.exists() and total_segments > 0:
        gog_env = os.environ.copy()
        gog_env["GOG_KEYRING_PASSWORD"] = "openclaw"
        subprocess.run([
            "gog", "gmail", "send",
            "--to", "sund4y1123@gmail.com",
            "--subject", f"번역 완료 ({total_segments}개 세그먼트, {datetime.now().strftime('%Y-%m-%d %H:%M')})",
            "--body", "스트림 종료. 번역 로그 첨부.",
            "--attach", str(log_file),
            "--account", "sundaibot0@gmail.com",
        ], capture_output=True, env=gog_env)


if __name__ == "__main__":
    total = 0
    while True:
        count, should_restart = main()
        total += count
        if should_restart:
            continue
        break
    cleanup(total)
