# GTC Live Translator

YouTube 라이브 영상의 음성을 실시간으로 한국어 번역하는 도구.

## 구조

```
YouTube Live → yt-dlp → ffmpeg → faster-whisper(STT) → Claude(번역) → 텔레그램 + 웹 뷰어
```

## 필요 환경

- Python 3.12+
- NVIDIA GPU (CUDA)
- faster-whisper, yt-dlp, numpy, requests
- OpenClaw Gateway (번역 API)
- ffmpeg, deno

## 사용법

```bash
# 번역 실행
LD_LIBRARY_PATH=/path/to/torch/lib \
PYTHONUNBUFFERED=1 \
python3 translate.py "YOUTUBE_URL"

# 웹 뷰어
python3 web.py
# → http://localhost:8091?v=VIDEO_ID
```

## 설정

| 항목 | 값 |
|---|---|
| STT 모델 | faster-whisper large-v3 |
| STT 청크 | 10초 |
| 번역 버퍼 | 30초 |
| 컨텍스트 | 이전 3개 번역 |
| 번역 모델 | Claude Opus (OpenClaw Gateway) |

## 웹 뷰어

- 왼쪽: YouTube 영상 임베딩
- 오른쪽: 실시간 번역 패널
- 드래그로 패널 비율 조절
- MD / TXT 다운로드
