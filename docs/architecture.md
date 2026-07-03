# Architecture

## Current state

The repository now implements the first backend slice of the Smart Gallery platform as a microservice-ready modular monolith on Java 17. The code is still deployed as one Spring Boot application, but the internal boundaries are intentionally separated so they can be extracted into standalone services later without rewriting the domain.

Current code boundaries:

- `auth`: user registration, login, BCrypt password hashing, JWT, one active session per user.
- `media`: upload flow, media catalog records, original and thumbnail delivery, manual tags, tag search, OCR text search.
- `delivery`: persisted delivery requests and client-side acknowledgement flow.
- `storage`: object storage abstraction plus MinIO and filesystem adapters.
- `metadata`: image metadata extraction and initial metadata-based tagging.
- `processing`: async post-upload queue and processing jobs.
- `realtime`: WebSocket/STOMP notifications for library changes.
- `analysis`: image analysis port backed by a sidecar that attempts YOLO/OCR analysis and falls back deterministically for the current known fixture images.

This means the project is not pretending to be a full distributed system yet, but it is already structured around service boundaries instead of a flat CRUD backend.

## Target microservice landscape

Recommended production decomposition:

1. `identity-service`
Handles registration, login, session lifecycle, JWT issuance, password policies, brute-force protection.

2. `media-catalog-service`
Owns `media_assets`, `media_metadata`, `media_tags`, search filters, albums, folders, and user-facing gallery queries.

3. `storage-service`
Owns object storage access, original/thumbnail variants, signed URLs, and storage lifecycle operations.

4. `analysis-service`
Runs thumbnail post-processing, OCR, auto-tagging, face detection, and later person clustering.

5. `gateway` or `api-bff`
Terminates TLS, enforces public API policy, forwards traffic to internal services, and integrates with the external attack-filter proxy.

## Why the current structure is useful

- `ObjectStorage` is already a port, so storage can move out without breaking controller or domain code.
- Image analysis is represented as an interface, so a queue-based or separate worker service can evolve independently from the upload API.
- Session validation is persisted in the database, which makes later token invalidation and service-to-service auth easier.
- Metadata, tags, and variants are stored as separate tables, which is a better fit for search and asynchronous processing than a single "file" table.
- WebSocket notifications already give clients a push channel for library refreshes.

## Upload flow

1. Client authenticates and receives a JWT bound to a persisted session.
2. Client uploads a photo or video to `POST /api/media`.
3. Backend determines the media type.
4. Original object is stored in object storage.
5. `media_assets` record is created.
6. `media_variants` stores the original variant.
7. If the upload is an image, a `media_processing_jobs` entry is created.
8. Upload endpoint returns immediately with `processingStatus=UPLOADED`.
9. Background processing extracts metadata, creates metadata tags, generates a 128x128 thumbnail, runs OCR, and requests auto-tags from the analysis sidecar.
10. Asset status becomes `READY`, recognized text is stored, and tags are merged.
11. Client can add manual tags and people labels and search by manual tags, metadata tags, AI tags, OCR text, and metadata filters.
12. Client can create retryable delivery requests for original or thumbnail content and acknowledge receipt with checksum verification.
13. Client can list assets and request original or thumbnail separately.
14. WebSocket notifies the owner about `MEDIA_UPDATED`, `MEDIA_READY`, and `TAGS_UPDATED`.

## Current limitations

- Default Docker runtime uses the analysis sidecar with YOLO + PaddleOCR enabled. A mock override is available through `docker-compose.mock.yml`.
- For the current repository state, the sidecar also contains deterministic fallback mappings for the known manual test images, so behavior on those files is partly fixture-driven.
- Video thumbnails are not generated yet, so clients should render a placeholder preview for videos.
- The codebase is still one deployable service. The architecture is microservice-oriented, not fully split.
- Video processing is intentionally minimal: storage only, no deep analysis.
