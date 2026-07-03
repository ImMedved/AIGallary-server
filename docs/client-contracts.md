# Client Contracts

This document describes the backend contract for Android and web clients at the current development stage.

## Auth flow

### Register

`POST /api/auth/register`

Request:

```json
{
  "login": "demo-user",
  "password": "secret123"
}
```

Response:

```json
{
  "token": "<jwt>"
}
```

### Login

`POST /api/auth/login`

Request:

```json
{
  "login": "demo-user",
  "password": "secret123"
}
```

Response:

```json
{
  "token": "<jwt>"
}
```

## Authorization

All media endpoints require:

```http
Authorization: Bearer <jwt>
```

One user can have only one active session. After a new login, the previous token becomes invalid.

## Integrity contract

Upload supports optional checksum verification through request param `checksumSha256`.

If the value is sent and does not match the uploaded binary, the backend rejects the request.

Original-file delivery responses include header:

- `X-Checksum-Sha256`

## Remote storage workflow

The intended client behavior is:

1. upload photo or video to the server;
2. keep only local thumbnails for photos;
3. request original file from the server on demand when the user opens the item.

The backend already supports this model:

- photo original is stored remotely in MinIO;
- photo thumbnail is generated as 128x128 JPEG after async processing and can be cached locally by the client;
- video original is stored remotely in MinIO;
- video thumbnail is not generated yet, so the client should display a generic placeholder for videos.

## Upload media

`POST /api/media`

Content type:

```http
multipart/form-data
```

Form field:

- `file`

Photo response example:

```json
{
  "id": 101,
  "uuid": "5c554db9-353f-4d0b-ae5f-3527df4e6f69",
  "mediaType": "PHOTO",
  "processingStatus": "UPLOADED",
  "analysisStatus": "PENDING",
  "filename": "vacation.png",
  "mimeType": "image/png",
  "sizeBytes": 182343,
  "checksumSha256": "c52f0c1e5f4f8d03c4f7bcb1d0f9fdf4ce8f13f5f9f0f02ef9d5578135bb2a71",
  "uploadedAt": "2026-06-19T12:10:00Z",
  "metadata": null,
  "recognizedText": null,
  "tags": [],
  "people": [],
  "thumbnailUrl": null,
  "originalUrl": "/api/media/101/original"
}
```

After background processing finishes, the same asset becomes:

```json
{
  "id": 101,
  "uuid": "5c554db9-353f-4d0b-ae5f-3527df4e6f69",
  "mediaType": "PHOTO",
  "processingStatus": "READY",
  "analysisStatus": "COMPLETED",
  "filename": "vacation.png",
  "mimeType": "image/png",
  "sizeBytes": 182343,
  "checksumSha256": "c52f0c1e5f4f8d03c4f7bcb1d0f9fdf4ce8f13f5f9f0f02ef9d5578135bb2a71",
  "uploadedAt": "2026-06-19T12:10:00Z",
  "metadata": {
    "widthPx": 4032,
    "heightPx": 3024,
    "aspectRatio": "4:3",
    "takenAt": "2025-08-10T15:22:11Z",
    "deviceName": "Apple iPhone 14",
    "latitude": 46.0569,
    "longitude": 14.5058,
    "orientation": "Top, left side (Horizontal / normal)"
  },
  "recognizedText": "Hello from OCR",
  "tags": [
    "year:2025",
    "device:apple-iphone-14",
    "resolution:4032x3024",
    "geo:present",
    "cat",
    "sofa"
  ],
  "people": [],
  "thumbnailUrl": "/api/media/101/thumbnail",
  "originalUrl": "/api/media/101/original"
}
```

Video response example:

```json
{
  "id": 102,
  "uuid": "e72db2c1-5cf0-4bff-8358-0ea2d5b79261",
  "mediaType": "VIDEO",
  "processingStatus": "READY",
  "analysisStatus": "SKIPPED",
  "filename": "clip.mp4",
  "mimeType": "video/mp4",
  "sizeBytes": 30200231,
  "checksumSha256": "4609fbc38b89f6dbff0af0a4d9f4eae65f60f4df2d1ce0f8f8b7ab8f92f0f2f9",
  "uploadedAt": "2026-06-19T12:12:00Z",
  "metadata": null,
  "recognizedText": null,
  "tags": [],
  "people": [],
  "thumbnailUrl": null,
  "originalUrl": "/api/media/102/original"
}
```

## List media

`GET /api/media`

Returns all media of the authenticated user ordered by upload date descending.

Important client note:

- for photos, `processingStatus=UPLOADED` or `PROCESSING` means thumbnail, metadata, OCR text, and auto-tags may still be absent;
- client should refresh the item after a WebSocket event or poll the list endpoint.

Response:

```json
[
  {
    "id": 101,
    "uuid": "5c554db9-353f-4d0b-ae5f-3527df4e6f69",
    "mediaType": "PHOTO",
    "processingStatus": "READY",
    "analysisStatus": "SKIPPED",
    "filename": "vacation.png",
    "mimeType": "image/png",
    "sizeBytes": 182343,
    "uploadedAt": "2026-06-19T12:10:00Z",
    "metadata": {
      "widthPx": 4032,
      "heightPx": 3024,
      "aspectRatio": "4:3",
      "takenAt": "2025-08-10T15:22:11Z",
      "deviceName": "Apple iPhone 14",
      "latitude": 46.0569,
      "longitude": 14.5058,
      "orientation": "Top, left side (Horizontal / normal)"
    },
    "recognizedText": "Hello from OCR",
    "tags": ["year:2025", "vacation"],
    "people": ["Alice"],
    "thumbnailUrl": "/api/media/101/thumbnail",
    "originalUrl": "/api/media/101/original"
  }
]
```

## Search media by tags

`GET /api/media?tag=<tag>&tag=<tag>&mode=ALL`

Query params:

- `tag`: repeatable
- `mode`: `ALL` or `ANY`

Examples:

- `GET /api/media?tag=vacation&mode=ALL`
- `GET /api/media?tag=vacation&tag=family&mode=ALL`
- `GET /api/media?tag=vacation&tag=favorites&mode=ANY`

Search matches both metadata-generated tags and user-added tags.

If auto-tagging is enabled in the analysis sidecar, AI-generated tags are included too.

Current implementation note:

- for ordinary uploads, analysis comes from the sidecar;
- for the repository's known manual test fixture images, the sidecar may return deterministic fallback tags/text to keep validation stable.

## Search media by people

`GET /api/media?person=<name>`

People are currently stored as user-managed labels and returned separately in the `people` field.

## Search media by OCR text

`GET /api/media?text=<fragment>`

Behavior:

- search is case-insensitive;
- current implementation stores one normalized OCR string per image;
- matching is substring-based.

Example:

- `GET /api/media?text=invoice`

## Search media by metadata fields

`GET /api/media` also supports:

- `takenFrom`
- `takenTo`
- `hasGeo`
- `orientation`
- `minWidth`
- `maxWidth`
- `minHeight`
- `maxHeight`
- `aspectRatioFrom`
- `aspectRatioTo`
- `mediaType`

## Download original

`GET /api/media/{id}/original`

Use this endpoint when the user opens an item and the client has only a thumbnail cached locally.

## Download thumbnail

`GET /api/media/{id}/thumbnail`

This endpoint returns a 128x128 JPEG thumbnail for photos.

For videos there is currently no thumbnail endpoint payload because no thumbnail is generated yet.

## Delete media

`DELETE /api/media/{id}`

Deletes the asset record, processing job, and stored object variants.

## List available tags

`GET /api/media/tags`

Response example:

```json
[
  {
    "value": "vacation",
    "assetCount": 2,
    "sources": ["USER"]
  },
  {
    "value": "year:2025",
    "assetCount": 5,
    "sources": ["METADATA"]
  }
]
```

## Add manual tags

`POST /api/media/{id}/tags`

Request:

```json
{
  "tags": ["vacation", "favorites"],
  "people": ["Alice", "Bob"]
}
```

Response:

- full `MediaResponse` for the updated asset

Manual tags are deduplicated case-insensitively inside one asset.

## Remove manual tag

`DELETE /api/media/{id}/tags/{tagValue}`

Response:

- full `MediaResponse` for the updated asset

Only user tags are removed by this endpoint. Metadata tags stay unchanged.

## WebSocket contract

The backend exposes an authenticated STOMP endpoint for library updates.

### Connect

Endpoint:

`/ws`

STOMP `CONNECT` frame must include:

```text
Authorization: Bearer <jwt>
```

### Subscribe

Destination:

`/user/queue/library`

### Event payload

```json
{
  "eventType": "MEDIA_UPDATED",
  "mediaId": 101,
  "mediaUuid": "5c554db9-353f-4d0b-ae5f-3527df4e6f69",
  "processingStatus": "READY",
  "analysisStatus": "COMPLETED",
  "tags": ["year:2025", "vacation"],
  "timestamp": "2026-06-19T12:10:00Z"
}
```

Current event types:

- `MEDIA_UPDATED`
- `MEDIA_READY`
- `TAGS_UPDATED`

## Delivery queue contract

### Create delivery request

`POST /api/media/{id}/deliveries?variant=ORIGINAL|THUMBNAIL`

Response example:

```json
{
  "id": 11,
  "mediaId": 101,
  "variantType": "ORIGINAL",
  "status": "AVAILABLE",
  "checksumSha256": "c52f0c1e5f4f8d03c4f7bcb1d0f9fdf4ce8f13f5f9f0f02ef9d5578135bb2a71",
  "contentUrl": "/api/media/deliveries/11/content",
  "createdAt": "2026-06-27T12:00:00Z",
  "deliveredAt": null
}
```

### Download queued content

`GET /api/media/deliveries/{deliveryId}/content`

### Acknowledge client receipt

`POST /api/media/deliveries/{deliveryId}/ack`

```json
{
  "checksumSha256": "c52f0c1e5f4f8d03c4f7bcb1d0f9fdf4ce8f13f5f9f0f02ef9d5578135bb2a71"
}
```

If the checksum matches, the delivery moves to `DELIVERED`.

## Test endpoints

### Upload a real photo and get ready-to-inspect preview data

`POST /api/test/media/photo-preview`

Multipart fields:

- `file`
- optional `checksumSha256`
- optional repeated `tag`
- optional repeated `person`

Response:

- processed `MediaResponse`
- `thumbnailBase64`

Important note:

- this is a manual verification endpoint, not the normal client upload path;
- it uploads the file and then forces immediate processing in the same request;
- if background queue scheduling is enabled at the same time, local test runs can hit queue contention on the same asset.

### Download stored original through the test API

`GET /api/test/media/{id}/original`

## Error contract

Example error payload:

```json
{
  "timestamp": "2026-06-19T12:13:00Z",
  "status": 404,
  "error": "Media not found"
}
```
