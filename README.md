# SmartGalleryServer

Backend foundation for the Smart Gallery platform. The project is aligned to Java 17 and now works as a remote media storage backend for photos and videos with MinIO-backed originals, photo thumbnails, JWT auth, manual tags, tag-based search, and asynchronous post-processing for uploaded images.

## What is implemented now

- Java 17 build and runtime alignment
- JWT authentication with persisted sessions
- one active session per user
- Flyway-managed database schema
- object storage abstraction
- MinIO adapter for containerized development
- filesystem adapter for tests and local fallback
- upload and download of original files from object storage
- media deletion from object storage and database
- 128x128 JPEG thumbnail generation for images
- asynchronous image post-processing after upload
- metadata extraction from images
- metadata-based initial tagging
- OCR text extraction pipeline contract
- auto-tagging pipeline contract through analysis sidecar
- manual tag management
- manual people labels
- media search by tags
- media search by people and metadata filters
- media search by recognized text
- checksum verification on upload plus checksum-aware delivery acknowledgement
- persisted delivery requests for retryable file sending
- authenticated WebSocket notifications for library updates
- separate analysis service container with real YOLO + PaddleOCR support
- optional mock analysis override for lightweight local runs
- test endpoints for real-photo validation
- TDD-friendly test suite and git hooks

## Current API

### Auth

- `POST /api/auth/register`
- `POST /api/auth/login`

Payload:

```json
{
  "login": "user",
  "password": "secret123"
}
```

### Media

Requires:

```http
Authorization: Bearer <token>
```

- `POST /api/media` with multipart field `file`
- `GET /api/media`
- `GET /api/media?tag=<tag>&tag=<tag>&mode=ALL|ANY&person=<name>&text=<text>&...`
- `GET /api/media?text=<fragment>`
- `GET /api/media/tags`
- `POST /api/media/{id}/tags`
- `DELETE /api/media/{id}`
- `DELETE /api/media/{id}/tags/{tagValue}`
- `GET /api/media/{id}/original`
- `GET /api/media/{id}/thumbnail`
- `POST /api/media/{id}/deliveries`
- `GET /api/media/deliveries/{deliveryId}/content`
- `POST /api/media/deliveries/{deliveryId}/ack`
- `POST /api/test/media/photo-preview`
- `GET /api/test/media/{id}/original`

### WebSocket

- STOMP endpoint: `/ws`
- user destination: `/user/queue/library`

## Storage model

- originals are stored remotely as object variants
- photo thumbnails are stored as separate 128x128 JPEG variants
- client can keep only thumbnails locally and load originals on demand
- Docker Compose uses MinIO
- image uploads return immediately and are enriched asynchronously
- default Docker Compose runs real PaddleOCR + YOLO analysis
- mock analysis is available through a separate override file
- tests use the filesystem storage adapter

## Documentation

- [Architecture](docs/architecture.md)
- [Database](docs/database.md)
- [Client Contracts](docs/client-contracts.md)
- [Development Workflow](docs/development.md)

## Quick start

```bash
docker compose up --build
```

Optional mock analysis override:

```bash
docker compose -f docker-compose.yml -f docker-compose.mock.yml up --build
```

Available services:

- backend: `http://localhost:8080`
- PostgreSQL: `localhost:5432`
- MinIO API: `http://localhost:9000`
- MinIO console: `http://localhost:9001`
- analysis service: `http://localhost:8090`

## Verification

Current baseline verification command:

```bash
mvn -q test
```
