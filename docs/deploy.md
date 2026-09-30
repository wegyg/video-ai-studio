# 배포 (Vercel + Render)

| 구성 | 서비스 | 플랜 |
|---|---|---|
| 화면 (Next.js) | Vercel | Hobby (무료) |
| 서버 (FastAPI + ffmpeg) | Render | Free |

브라우저는 Vercel 주소만 호출하고, Vercel이 `/api/*` 요청을 Render로 넘깁니다
(`frontend/next.config.mjs`). 같은 출처로 요청이 나가므로 **CORS 설정이 따로 필요하지
않습니다.**

## 무료 플랜의 한계

- **잠들기** — 15분간 아무도 쓰지 않으면 서버가 잠들고, 다음 접속 때 깨어나는 데 약 1분이 걸립니다.
- **렌더 속도** — CPU가 0.1개뿐이라 15초 영상 한 편에 대략 3~6분 걸립니다.
- **저장 공간** — 영구 디스크가 없어 서버가 잠들거나 재시작되면 만든 영상이 사라지므로, 완성되면 바로 내려받아야 합니다.
- **해상도** — 메모리 512MB 한계로 432x768까지만 가능합니다 (1080p는 메모리 초과로 렌더가 죽습니다).
- **월 사용량** — 워크스페이스당 월 750시간이며, 다 쓰면 다음 달까지 중지됩니다.

출처: [Render 무료 플랜 문서](https://render.com/docs/free),
[무료 인스턴스 사양](https://render.com/articles/from-side-project-to-production-scaling-your-first-app).
내용은 라이선스 준수를 위해 요약·재작성했습니다.

## 해상도를 왜 432로 두는가

무료 인스턴스는 512MB입니다. 이 이미지에서 5장면 9:16 영상 한 편을 렌더할 때 측정한
최대 메모리(앱 + ffmpeg):

| 설정 | 최대 메모리 | 512MB 기준 |
|---|---|---|
| 1080 | 700MB 이상 | 초과 |
| 540 | 566MB | 초과 |
| 480 | 474MB | 여유 38MB (위험) |
| **432** | **435MB** | 여유 77MB |

`MOTION_UPSCALE`을 낮추는 방법은 효과가 거의 없습니다. 1080에서 4배 → 2배로 줄여도
747MB → 709MB였습니다. 메모리를 결정하는 것은 **출력 해상도**입니다.

메모리가 2GB 이상인 유료 인스턴스로 옮기면 `VIDEO_BASE_HEIGHT`를 720이나 1080으로
올리세요. 화질 차이가 큽니다.

## 환경변수

Render (서버):

| 이름 | 값 | 필수 |
|---|---|---|
| `PEXELS_API_KEY` | 발급받은 키 | 스톡 영상을 쓸 때만 |
| `VIDEO_BASE_HEIGHT` | `432` | 예 (render.yaml에 있음) |
| `OUTPUT_DIR` | `/tmp/output` | 예 (render.yaml에 있음) |
| `CORS_ORIGINS` | `https://내주소.vercel.app` | Vercel 프록시를 쓰면 불필요 |

Vercel (화면):

| 이름 | 값 |
|---|---|
| `BACKEND_URL` | `https://내서버.onrender.com` |

`BACKEND_URL`을 빠뜨리면 빌드가 실패하면서 이유를 알려줍니다. 예전처럼 localhost로
조용히 되돌아가 모든 API 호출이 실패하는 일은 없습니다.

키는 코드나 `render.yaml`에 쓰지 마세요. `render.yaml`의 `sync: false`는 "값은
대시보드에서 입력받고 파일에 저장하지 않는다"는 뜻입니다.

## 내 컴퓨터에서 실행 (Windows)

`start.bat`을 두 번 누르면 됩니다. Python, Node.js, ffmpeg가 있는지 확인하고, 없으면
무엇을 어디서 설치해야 하는지 알려주고 멈춥니다. 자동으로 설치하지는 않습니다.

로컬은 메모리가 넉넉하므로 해상도 기본값 1080을 그대로 씁니다.

## 이미지 직접 확인

```bash
cd backend
docker build -t vas-api .
docker run --rm -p 8000:8000 -e TTS_PROVIDER=silent vas-api
curl localhost:8000/api/health
```

`/api/health`는 비율별 실제 출력 크기를 보여주므로, 해상도 설정이 적용됐는지 여기서
확인할 수 있습니다.
