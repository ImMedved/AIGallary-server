# Development Workflow

## Java version

The project is standardized on Java 17 end-to-end:

- Maven build targets Java 17
- Docker build uses Temurin 17
- runtime image uses Temurin 17

## TDD workflow

The repository now follows a test-first development workflow for backend changes:

1. Write or update a failing test for the intended behavior.
2. Implement the smallest code change that makes the test pass.
3. Refactor while keeping the test suite green.
4. Run the full Maven test suite before pushing.

Current automated coverage is focused on:

- auth session behavior
- media upload, async processing, and delivery flow
- remote storage workflow for images and videos
- manual tags and tag search
- OCR text persistence and text search
- thumbnail generation
- metadata-based initial tagging
- delete lifecycle
- delivery acknowledgement flow
- test photo endpoints

## Git hooks

Hooks live in `.githooks/`.

- `pre-commit`: `mvn -q -DskipTests compile`
- `pre-push`: `mvn -q test`

Install them once per local clone:

### PowerShell

```powershell
./scripts/install-hooks.ps1
```

### Bash

```bash
./scripts/install-hooks.sh
```

Or manually:

```bash
git config core.hooksPath .githooks
```

## Local development

### Full stack with Docker Compose

```bash
docker compose up --build
```

This starts:

- PostgreSQL
- MinIO
- `analysis-service` with YOLO + PaddleOCR enabled
- Spring Boot server

### Full stack with mock analysis profile

```bash
docker compose -f docker-compose.yml -f docker-compose.mock.yml up --build
```

Notes:

- base `docker-compose.yml` enables the YOLO + PaddleOCR analysis path;
- first build is heavier because ML dependencies are installed into `analysis-service`;
- `docker-compose.mock.yml` switches analysis back to the deterministic mock provider when you need a lightweight stack.
- current `analysis-service` also contains deterministic fallback outputs for the known test fixture images in `test data/`.

### Split deployment mode

Infra only:

```bash
docker compose -f docker-compose.infra.yml up -d --build
```

App only:

```bash
docker compose -f docker-compose.app.yml up -d --build
```

Split deployment note:

- both compose files attach services to the shared named network `smart-gallery-network`;
- this allows the separately started `server` container to resolve `postgres`, `minio`, and `analysis` by service name;
- start infrastructure first, then the application container.

Services:

- PostgreSQL: `localhost:5432`
- MinIO API: `localhost:9000`
- MinIO console: `localhost:9001`
- analysis service: `localhost:8090`
- backend: `localhost:8080`
- WebSocket STOMP endpoint: `ws://localhost:8080/ws`

Local browser note:

- default CORS allows both `http://localhost:5173` and `http://127.0.0.1:5173`;
- if the frontend is opened from another host or port, set `APP_CORS_ALLOWED_ORIGINS` or `APP_CORS_ALLOWED_ORIGIN_PATTERNS` before starting the server container.

Useful manual verification endpoints:

- `POST /api/test/media/photo-preview`
- `GET /api/test/media/{id}/original`

Important test-endpoint note:

- `POST /api/test/media/photo-preview` forces immediate processing in-request and is intended for manual verification only;
- if the normal background scheduler is enabled at the same time, this endpoint can contend with the queue on the same asset;
- for deterministic local validation, prefer running the test backend with `APP_ANALYSIS_SCHEDULING_ENABLED=false`.

Development MinIO credentials:

- login: `minio`
- password: `minio123`

## Running tests

```bash
mvn -q test
```

Test environment notes:

- H2 is used for integration tests
- Flyway migrations are executed in tests
- filesystem storage adapter is used in tests to avoid external dependencies
- image analysis is mocked in integration tests to keep TDD feedback fast and deterministic

## Storage providers

Config switch:

- `app.storage.provider=filesystem`
- `app.storage.provider=minio`

The application code talks only to `ObjectStorage`, so tests, local runs, and containerized runs can use different adapters without changing business logic.

## Client sync pattern

Recommended client behavior for the current backend stage:

1. Upload originals to the backend.
2. Persist only thumbnails locally for photos.
3. Keep remote ids and URLs for later fetch.
4. Download the original only when the user opens the item.
5. Wait for `MEDIA_UPDATED` or poll the list endpoint until photo processing becomes `READY`.
6. Use `/api/media/tags`, `/api/media?tag=...`, `/api/media?person=...`, `/api/media?text=...`, and metadata filters for browsing.
7. If the client wants delivery acknowledgement semantics, create a delivery request and confirm it with checksum after receipt.
8. Subscribe to `/user/queue/library` over STOMP to react to library updates.
