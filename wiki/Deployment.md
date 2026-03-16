# 배포

현재 Bloggent는 Docker 중심의 로컬 실행 환경에 가장 잘 맞도록 구성되어 있습니다.

## 주요 서비스

- `web`
- `api`
- `worker`
- `scheduler`
- `postgres`
- `redis`
- `minio`

## 기본 실행 명령

```bash
docker compose up --build -d
```

## 앱 변경 후 재빌드

```bash
docker compose up --build -d api worker scheduler web
```

## 확인 방법

```bash
curl http://localhost:8000/healthz
```

```bash
cd apps/web
npm run build
```

## 현재 배포 메모

지금 로컬 `web` 컨테이너는 Next.js 개발 서버로 실행됩니다.
로컬 작업에는 충분하지만, 이후 프로덕션 스타일 실행 프로파일은 별도로 정리하는 것이 좋습니다.
