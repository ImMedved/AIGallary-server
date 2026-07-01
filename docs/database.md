# Database

## Migration strategy

The project no longer relies on `hibernate.ddl-auto=update`. Database structure is now defined through Flyway migrations.

Current migration set:

- `V1__initial_schema.sql`
- `V2__tag_search_and_uniqueness.sql`
- `V3__async_media_processing.sql`
- `V4__media_delivery_and_checksum.sql`

This is the database skeleton for the current development stage and covers auth, sessions, media catalog, storage variants, metadata tags, OCR text storage, background processing jobs, checksums, and delivery requests.

## Tables

### `app_users`

- application users
- unique login
- BCrypt password hash

### `user_sessions`

- persisted JWT sessions
- one active session per user is enforced by application logic
- old sessions are invalidated on new login

### `media_assets`

- main gallery object
- owner id
- media type: `PHOTO` or `VIDEO`
- processing status
- analysis status
- SHA-256 checksum of the original file
- recognized OCR text
- normalized OCR text
- original filename, MIME type, size

### `media_variants`

- object storage variants for one asset
- current variants:
  `ORIGINAL`
  `THUMBNAIL`
- stores bucket name, object key, content type, and size

### `media_metadata`

- extracted image metadata
- width and height
- capture timestamp
- camera make/model
- normalized device name
- coordinates if present
- orientation

### `media_tags`

- tag list attached to an asset
- stores both display value and normalized value
- source:
  `METADATA`
  `ANALYSIS`
  `USER`
- confidence is already present for future AI-generated tags
- current uniqueness is enforced by `asset_id + tag_source + normalized_value`

### `media_processing_jobs`

- one async processing job per uploaded image
- state machine:
  `PENDING`
  `RUNNING`
  `COMPLETED`
  `FAILED`
- stores retry counters, availability time, and the last error for diagnostics

### `media_delivery_requests`

- persisted requests for file delivery
- owner id plus asset id
- requested variant
- delivery status and download attempts
- expected checksum and acknowledged checksum
- timestamps for creation and successful acknowledgement

## Why this schema fits the roadmap

- It already supports MinIO or any S3-compatible storage because binary objects are referenced through bucket plus key.
- It separates the asset itself from its delivery variants.
- It supports current metadata tagging, OCR text persistence, manual user tags, async image enrichment, and future face and AI tags without another schema reset.
- It leaves space for stage 3 additions such as folders, albums, search indexes, and richer media analysis.
