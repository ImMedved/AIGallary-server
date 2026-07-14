# Smart Gallery Analysis Service — строгий план улучшения

## 1. Цель документа

Этот документ задаёт обязательный план развития `analysis-service` для Smart Gallery.

Цель изменений:

- повысить качество OCR для кириллицы и латиницы;
- повысить качество тегов и семантического описания изображений;
- добавить основу для распознавания и группировки лиц;
- исключить блокировку API и зависание контейнера при тяжёлой ML-обработке;
- разделить быстрый анализ и тяжёлое фоновое обогащение;
- сохранить работу сервиса при отказе отдельных моделей;
- не допустить бесконтрольного добавления моделей, зависимостей и архитектурных обходов.

Этот документ является техническим контрактом. Агент не должен менять архитектуру, добавлять новые модели, менять API или порядок этапов без явного указания.

## 2. Жёсткие ограничения

### 2.1. Запрещено

Агенту запрещено:

1. Возвращать тяжёлую ML-обработку внутрь основного event loop FastAPI.
2. Запускать несколько `uvicorn` workers для масштабирования ML.
3. Загружать отдельную копию моделей в каждый API-процесс.
4. Запускать OCR, YOLO, CLIP, VLM и face analysis одновременно на каждом изображении.
5. Добавлять новую модель без отдельного адаптера, конфигурации и теста деградации.
6. Использовать свободный текст VLM как готовый набор тегов.
7. Сравнивать confidence разных моделей напрямую.
8. Перезаписывать raw OCR исправленным текстом.
9. Глобально заменять похожие латинские и кириллические символы.
10. Делать один плоский список тегов без категории, источника и версии модели.
11. Блокировать статус готовности изображения до завершения тяжёлого enrichment.
12. Считать отсутствие CLIP, VLM или face model фатальной ошибкой всего анализа.
13. Загружать модели при первом пользовательском запросе без предварительного прогрева.
14. Скачивать модели во время обработки пользовательского изображения.
15. Хранить model cache только внутри файловой системы контейнера.
16. Добавлять PP-Structure, docTR, TrOCR, BLIP-2, Qwen-VL или другие тяжёлые модели одновременно.
17. Менять формат БД, API-контракты или статусы без миграции и обратной совместимости.
18. Делать крупный рефакторинг и смену моделей в одном коммите.
19. Удалять существующую рабочую fallback-логику до прохождения новых тестов.
20. Подменять реальный анализ checksum-fixture результатами вне тестового режима.

### 2.2. Обязательные свойства

После каждого этапа:

- сервис обязан запускаться;
- `/health/live` обязан отвечать независимо от состояния ML workers;
- `/health/ready` обязан показывать реальную готовность моделей и очереди;
- базовый анализ обязан завершаться даже при отказе необязательной модели;
- все ошибки должны попадать в структурированный результат;
- старый API должен продолжать работать до отдельного этапа удаления совместимости;
- Docker image должен собираться с кешем зависимостей;
- модели должны храниться в persistent volume;
- все новые функции должны иметь unit tests и integration tests.

## 3. Целевая архитектура

### 3.1. Общая схема

```text
Spring server
    |
    | POST /v1/analysis/fast
    v
FastAPI API process
    |
    | enqueue
    v
Fast worker pool
    |
    +-- metadata
    +-- image subtype
    +-- fast OCR
    +-- basic object detection
    +-- image embedding
    +-- fast evidence merge
    |
    v
SEARCHABLE
    |
    | enqueue
    v
Enrichment worker pool
    |
    +-- OCR fallback for weak blocks
    +-- structured VLM analysis
    +-- semantic reranking
    +-- face detection
    +-- face embeddings
    +-- final evidence merge
    |
    v
COMPLETED / PARTIALLY_COMPLETED

Separate face clustering job
    |
    +-- collect unnamed face embeddings
    +-- cluster across entire library
    +-- expose largest unknown clusters
    +-- user assigns names
```

### 3.2. Процессы

Должны существовать логически разные роли:

```text
api
fast-worker
enrichment-worker
face-clustering-worker
```

На первом этапе они могут находиться в одном контейнере, но должны быть разделены классами, очередями и конфигурацией.

API-процесс не выполняет тяжёлую ML-работу.

### 3.3. Модули Python

Обязательная структура:

```text
analysis_service/
    api/
        app.py
        dependencies.py
        routes_health.py
        routes_analysis.py
        routes_admin.py

    config/
        settings.py
        logging.py
        profiles.py

    domain/
        enums.py
        schemas.py
        evidence.py
        errors.py
        states.py

    pipeline/
        fast_pipeline.py
        enrichment_pipeline.py
        merge_pipeline.py
        routing.py

    execution/
        executor.py
        process_pool.py
        queue.py
        limits.py
        worker_bootstrap.py

    models/
        registry.py
        lifecycle.py

        ocr/
            base.py
            paddle_adapter.py
            easyocr_adapter.py
            routing.py
            scoring.py
            normalization.py
            reading_order.py

        detection/
            base.py
            yolo_adapter.py

        embedding/
            base.py
            clip_adapter.py

        vlm/
            base.py
            structured_adapter.py
            schema.py

        faces/
            detector.py
            embedder.py
            clustering.py
            identity_store.py

    tagging/
        taxonomy.py
        merger.py
        calibration.py
        rules.py

    cache/
        result_cache.py
        embedding_cache.py
        model_cache.py

    observability/
        metrics.py
        events.py
        timings.py

    storage/
        debug_store.py
        face_store.py

    tests/
```

Запрещено переносить всю логику обратно в `app.py`.

## 4. Доменные контракты

### 4.1. Статусы анализа

Обязательный enum:

```text
UPLOADED
FAST_PENDING
FAST_RUNNING
SEARCHABLE
ENRICHMENT_PENDING
ENRICHMENT_RUNNING
COMPLETED
PARTIALLY_COMPLETED
FAILED
```

Правила:

- `SEARCHABLE` означает, что fast pipeline завершён.
- Ошибка enrichment не должна возвращать объект в `FAILED`.
- `FAILED` используется только если fast pipeline не смог выдать минимальный результат.
- Если fast pipeline успешен, а enrichment частично упал, итог — `PARTIALLY_COMPLETED`.

### 4.2. OCR-результат

Обязательная схема:

```json
{
  "rawText": "сырой текст модели",
  "displayText": "очищенный текст для отображения",
  "searchText": "нормализованный текст для поиска",
  "languageHints": ["ru", "en"],
  "averageConfidence": 0.82,
  "quality": "strong",
  "blocks": [
    {
      "rawText": "строка",
      "displayText": "строка",
      "searchText": "строка",
      "confidence": 0.91,
      "bbox": [10, 20, 400, 80],
      "language": "ru",
      "quality": "strong",
      "engine": "paddle",
      "variant": "base"
    }
  ],
  "warnings": []
}
```

`rawText` запрещено исправлять.

`displayText` может исправлять пробелы, порядок строк и очевидные артефакты.

`searchText` может использовать Unicode NFKC, lowercase, нормализацию пробелов, поисковую версию похожих символов и удаление незначащей пунктуации.

### 4.3. Evidence

Все результаты моделей должны сначала преобразовываться в `Evidence`.

```json
{
  "type": "object",
  "value": "car",
  "category": "objects",
  "source": "yolo",
  "rawConfidence": 0.87,
  "calibratedConfidence": 0.79,
  "quality": "strong",
  "modelName": "yolov8s",
  "modelVersion": "8.3.0",
  "reason": "detected object",
  "bbox": [0.1, 0.2, 0.4, 0.8],
  "metadata": {}
}
```

Модели не должны создавать финальные теги напрямую.

### 4.4. Категории тегов

Разрешённые категории:

```text
objects
scene
activities
media_type
events
ocr_derived
people
location
time
manual
system
```

Каждый тег обязан иметь:

```text
value
category
source
confidence
quality
modelName
modelVersion
reason
validated
```

### 4.5. Quality level

Обязательный enum:

```text
verified
strong
moderate
weak
rejected
```

Пороговые значения задаются отдельно для каждого адаптера.

Запрещено считать `0.8` одной модели равным `0.8` другой модели.

## 5. Этап 0 — фиксация текущего состояния

### Цель

Создать baseline, чтобы дальнейшие изменения измерялись, а не оценивались субъективно.

### Шаги

1. Создать каталог:

```text
analysis-evaluation/
    images/
    expected/
    results/
    reports/
```

2. Подготовить минимум 100 тестовых изображений:

```text
20 screenshots
20 memes
15 documents/scans
15 natural photos with visible text
20 ordinary photos without text
10 difficult/low-quality images
```

3. Для каждого изображения вручную сохранить ожидаемое:

```json
{
  "imageKind": "meme",
  "expectedText": "...",
  "requiredTags": ["meme", "text"],
  "allowedTags": ["person"],
  "forbiddenTags": ["car", "receipt"]
}
```

4. Добавить скрипт `evaluate.py`.

5. Метрики OCR:

```text
CER
WER
accepted garbage rate
empty result rate
average OCR time
p95 OCR time
```

6. Метрики тегов:

```text
precision@5
recall@5
forbidden tag rate
empty tag rate
average tag time
p95 tag time
```

7. Сохранить текущий baseline в JSON и Markdown.

### Критерий готовности

Есть воспроизводимый отчёт для текущего сервиса на одном и том же наборе изображений.

Без baseline запрещено переходить к смене моделей.

## 6. Этап 1 — стабилизация API и выполнения

### Цель

Полностью исключить зависание `/health` и API при тяжёлой обработке.

### Шаги

1. Оставить один uvicorn process.
2. Вынести fast analysis в ограниченный process pool.
3. Добавить отдельный semaphore для pending requests.
4. Ввести профили ресурсов.

Test profile:

```text
container memory: 5 GB
fast workers: 1
enrichment workers: 1
max pending fast: 2
max pending enrichment: 1
intra-op threads: 4
result cache: 512 MB
```

Production profile:

```text
container memory: 20 GB
fast workers: 2
enrichment workers: 1
max pending fast: 4
max pending enrichment: 2
intra-op threads: 4
result cache: 3 GB
```

5. Добавить endpoints:

```text
GET /health/live
GET /health/ready
GET /health/models
GET /metrics
POST /admin/warmup
```

6. `/health/live` не должен обращаться к моделям, очередям или диску.
7. `/health/ready` должен проверять API startup, worker pool, required fast models и queue threshold.
8. При переполнении очереди возвращать HTTP 429, `Retry-After` и `ANALYSIS_QUEUE_FULL`.
9. При timeout прекращать ожидание результата, не блокировать API и помечать job как retryable.
10. Добавить graceful shutdown.

### Тесты

- `/health/live` отвечает менее чем за 200 ms при загруженном worker.
- 10 параллельных запросов не блокируют event loop.
- При переполнении очередь возвращает 429.
- При падении worker он пересоздаётся.
- При ошибке модели API остаётся живым.

### Критерий готовности

Ни один ML-запрос не выполняется в API event loop.

## 7. Этап 2 — persistent model cache и прогрев

### Цель

Исключить скачивание и инициализацию моделей на первом пользовательском запросе.

### Шаги

1. Все модели хранить в volume `analysis_model_cache`.
2. Mount path: `/models`.
3. Обязательные env:

```text
HF_HOME=/models/huggingface
TORCH_HOME=/models/torch
PADDLE_HOME=/models/paddle
EASYOCR_MODULE_PATH=/models/easyocr
YOLO_CONFIG_DIR=/models/ultralytics
```

4. Добавить manifest моделей с `name`, `version`, `path`, `sha256`, `requiredFor`.
5. На startup проверить наличие и checksum, загрузить required fast models, не скачивать автоматически в production.
6. При отсутствии required model выставить `/health/ready = false`.
7. Добавить отдельную команду загрузки:

```powershell
docker compose run --rm analysis python -m analysis_service.models.download
```

8. Автоматическую загрузку разрешать только через `ANALYSIS_ALLOW_MODEL_DOWNLOAD=true`.
9. В production значение по умолчанию — `false`.

### Критерий готовности

Первый запрос не запускает загрузку модели и не выполняет долгую инициализацию.

## 8. Этап 3 — fast pipeline

### Цель

Сделать быстрый, надёжный и ограниченный анализ.

### Состав

```text
metadata
image subtype
fast OCR
basic object detection
image embedding
fast evidence merge
```

### Порядок

1. Validate/decode image.
2. Apply EXIF orientation.
3. Compute checksum.
4. Check result cache.
5. Classify subtype.
6. Route OCR.
7. Run object detector only where useful.
8. Compute image embedding.
9. Build Evidence list.
10. Merge evidence.
11. Return SEARCHABLE result.
12. Enqueue enrichment.

### Ограничения

Fast pipeline не использует VLM, не выполняет face clustering и не делает повторный тяжёлый OCR всего изображения.

### Целевые времена

```text
median <= 10 seconds
p95 <= 30 seconds
```

## 9. Этап 4 — маршрутизация OCR

### Цель

Улучшить OCR без запуска всех движков на каждом изображении.

### Классы изображения

```text
natural_photo
screenshot
meme
document
receipt
code_screenshot
chat_screenshot
unknown
```

### Routing

Screenshot, document, meme:

```text
whole-image OCR
2-3 controlled preprocessing variants
reading order reconstruction
garbage filtering
```

Natural photo:

```text
text detection
crop text regions
recognize each crop
merge by reading order
```

Code screenshot:

```text
preserve punctuation
disable aggressive language correction
preserve case
```

Chat screenshot:

```text
preserve message blocks
sort top-to-bottom
do not flatten sender/time into sentence
```

### Ограничение вариантов

Максимум 3 OCR variants в fast pipeline. Дополнительные variants допускаются только в enrichment и только для слабых блоков.

### Scoring OCR

Оценка кандидата должна учитывать model confidence, valid character ratio, language plausibility, mixed-script penalty, repetition penalty, line consistency, geometry и text length cap.

Длина текста не должна быть главным фактором.

### Mixed-script correction

Разрешено определять dominant script по токену, исправлять похожие символы только при высокой уверенности и хранить correction trace.

Запрещено изменять URL, email, filenames и code tokens, а также удалять raw text.

### Garbage rejection

Блок отклоняется при сочетании low confidence, high mixed-script ratio, low valid-character ratio, high repetition и low language plausibility.

Причина отклонения сохраняется в debug.

### Критерий готовности

На baseline:

- CER лучше исходного минимум на 20%;
- garbage acceptance rate снижен минимум в 2 раза;
- OCR p95 не ухудшен более чем на 50%.

## 10. Этап 5 — image embeddings

### Цель

Создать фундамент для semantic search, similarity, duplicate detection и тегов.

### Шаги

1. Выбрать один embedding adapter.
2. Не менять embedding model без benchmark.
3. Сохранять vector, modelName, modelVersion, dimension, normalization и checksum.
4. Cache embeddings по checksum.
5. Добавить cosine similarity API только после сохранения embeddings.
6. Не использовать softmax по всему списку prompt как абсолютную confidence.
7. Для zero-shot labels использовать raw similarity, per-tag calibration, minimum margin и negative prompts при необходимости.

### Критерий готовности

Одинаковые или почти одинаковые изображения имеют высокую similarity, случайные — заметно меньшую.

## 11. Этап 6 — система evidence и итоговых тегов

### Цель

Перестать объединять теги простым выбором максимального confidence.

### Шаги

1. Все адаптеры возвращают только Evidence.
2. Добавить `ConfidenceCalibrator` для каждого source.
3. Добавить `EvidenceMerger`.
4. Подтверждение тега: один strong source, два independent moderate source или manual/verified source.
5. Отклонение: weak unsupported VLM claim, contradiction with detector, subtype mismatch или source-specific threshold failure.
6. Ввести taxonomy aliases.
7. Сохранять reason для каждого финального тега.
8. Ограничивать число тегов по категориям.

Рекомендуемые лимиты:

```text
objects: 8
scene: 3
activities: 3
media_type: 2
events: 2
ocr_derived: 5
people: unlimited named identities
```

### Критерий готовности

В результате нет тегов без source, reason, category и model version.

## 12. Этап 7 — enrichment pipeline

### Цель

Добавить качественный анализ без блокировки fast pipeline.

### Состав

```text
weak OCR block retry
structured VLM
semantic reranking
face detection
face embeddings
final evidence merge
```

### Правила запуска

Enrichment запускается, если OCR quality weak/moderate, tag evidence недостаточен, subtype требует semantic analysis, вероятны лица или есть manual force request.

Не запускать enrichment повторно при совпадении checksum, model versions и pipeline version.

Ошибка enrichment не меняет `SEARCHABLE` на `FAILED`.

## 13. Этап 8 — structured VLM

### Цель

Получать контекст и события, не превращая hallucination в факты.

### Ограничения

1. Использовать только одну VLM.
2. VLM работает только в enrichment.
3. VLM возвращает JSON по фиксированной schema.
4. Свободный caption хранится отдельно.
5. Invalid JSON считается ошибкой адаптера.
6. Запрещено извлекать теги регулярками из caption.

### Схема результата

```json
{
  "caption": "A group of people sitting at a restaurant table.",
  "scene": ["restaurant", "indoor"],
  "activities": ["eating", "social gathering"],
  "events": [],
  "objects": ["person", "table", "food"],
  "textHints": [],
  "uncertain": ["birthday"],
  "warnings": []
}
```

### Merger rules

- `objects` не считаются verified без detector или embedding evidence.
- `events` требуют дополнительного evidence.
- `uncertain` никогда не превращаются в финальные теги автоматически.
- Caption не является источником OCR text.

### Выбор модели

До выбора модели выполнить benchmark по quality, CPU latency, RAM usage, model size, offline availability и JSON compliance.

Запрещено выбирать модель только по популярности.

### Критерий готовности

VLM можно полностью отключить env-переменной, а fast pipeline продолжает работать.

## 14. Этап 9 — лица

### Цель

Выделять лица, строить embeddings, группировать часто встречающихся людей и давать пользователю назвать группы.

### Per-image face analysis

```text
detect faces
align faces
compute embedding
estimate quality
store face record
```

Схема:

```json
{
  "faceId": "...",
  "assetId": 123,
  "bbox": [0, 0, 100, 100],
  "embeddingModel": "arcface",
  "embeddingVersion": "...",
  "quality": 0.88,
  "identityId": null,
  "clusterId": null
}
```

### Clustering

Кластеризация не выполняется внутри `/analyze`.

Отдельный job:

```text
load unnamed high-quality embeddings
remove duplicates from same burst/image
cluster
merge with existing stable clusters
rank clusters by occurrence count
```

### Правила

1. Использовать cosine distance.
2. Не назначать имя автоматически.
3. Не объединять кластеры при низкой уверенности.
4. Хранить centroid и representative faces.
5. После пользовательского имени сохранять identity отдельно от cluster.
6. Новые лица сравнивать сначала с named identities, затем с unknown clusters.
7. Поддержать name, merge, split, reject и hide operations.

### Порог показа

```text
cluster size >= 3
average quality above threshold
at least 2 different assets
```

### Критерий готовности

Кластеризация может быть перезапущена без повторного анализа исходных изображений.

## 15. Этап 10 — API-контракты

### Fast analysis

```text
POST /v1/analysis/fast
```

Ответ:

```json
{
  "analysisId": "...",
  "status": "SEARCHABLE",
  "result": {},
  "enrichmentScheduled": true,
  "errors": []
}
```

### Enrichment

```text
POST /v1/analysis/{analysisId}/enrichment
GET /v1/analysis/{analysisId}
```

### Backward compatibility

Старый `POST /analyze` временно вызывает fast pipeline и возвращает совместимый response.

Удаление допускается только после миграции Spring server.

### Error schema

```json
{
  "code": "OCR_ENGINE_FAILED",
  "message": "PaddleOCR failed",
  "retryable": true,
  "component": "ocr",
  "details": {}
}
```

## 16. Этап 11 — интеграция со Spring server

### Цель

Не блокировать всю очередь одним sidecar request.

### Обязательные изменения

1. Разделить fast и enrichment jobs.
2. Обрабатывать несколько fast jobs параллельно с ограничением.
3. Не использовать бесконечное последовательное ожидание одного asset.
4. Разделить fast timeout и enrichment timeout.
5. После fast success выставлять asset `SEARCHABLE`.
6. Enrichment failure не удаляет thumbnail и metadata.
7. Retry должен быть idempotent.
8. FAILED job должен иметь ручной retry endpoint.
9. После восстановления sidecar PENDING jobs должны продолжаться автоматически.
10. Unsupported thumbnail format должен быть отдельной ошибкой от analysis failure.

### Retry policy

```text
connect errors: retry
read timeout: retry
429 queue full: retry with Retry-After
4xx invalid image: no automatic retry
model unavailable: delayed retry
invalid VLM JSON: enrichment-only retry
```

### Критерий готовности

Один долгий asset не останавливает обработку остальных файлов.

## 17. Этап 12 — Docker и ресурсы

Переменные:

```text
ANALYSIS_RAM_PROFILE
ANALYSIS_CONTAINER_MEMORY_LIMIT
ANALYSIS_WORKERS
ANALYSIS_ENRICHMENT_WORKERS
ANALYSIS_INTRAOP_THREADS
ANALYSIS_MAX_PENDING_REQUESTS
ANALYSIS_RESULT_CACHE_MB
ANALYSIS_LOG_MODE
ANALYSIS_ALLOW_MODEL_DOWNLOAD
```

Compose:

```yaml
analysis:
  mem_limit: ${ANALYSIS_CONTAINER_MEMORY_LIMIT:-5g}
  environment:
    ANALYSIS_RAM_PROFILE: ${ANALYSIS_RAM_PROFILE:-test}
    ANALYSIS_WORKERS: ${ANALYSIS_WORKERS:-1}
    ANALYSIS_ENRICHMENT_WORKERS: ${ANALYSIS_ENRICHMENT_WORKERS:-1}
    ANALYSIS_INTRAOP_THREADS: ${ANALYSIS_INTRAOP_THREADS:-4}
    ANALYSIS_MAX_PENDING_REQUESTS: ${ANALYSIS_MAX_PENDING_REQUESTS:-2}
    ANALYSIS_RESULT_CACHE_MB: ${ANALYSIS_RESULT_CACHE_MB:-512}
    ANALYSIS_LOG_MODE: ${ANALYSIS_LOG_MODE:-debug}
    ANALYSIS_ALLOW_MODEL_DOWNLOAD: ${ANALYSIS_ALLOW_MODEL_DOWNLOAD:-false}
  volumes:
    - analysis_model_cache:/models
    - analysis_debug:/debug
```

Не использовать `deploy.resources` как единственный memory limit для обычного `docker compose`, если он не работает в текущем режиме Docker.

## 18. Этап 13 — логирование и метрики

### Debug mode

Пишет job lifecycle, routing decisions, model load events, OCR candidate scores, rejected blocks, raw evidence, calibration results, final tag reasons, timings, cache hit/miss, queue depth и exceptions.

### Production mode

Пишет service startup summary, model readiness, job start/end, aggregate timings, aggregate result counts, errors, worker restart и queue saturation.

Полный OCR text в production logs не писать.

### Метрики

```text
analysis_jobs_total
analysis_jobs_failed_total
analysis_stage_duration_seconds
analysis_queue_depth
analysis_queue_rejected_total
analysis_cache_hit_total
analysis_worker_restart_total
analysis_model_ready
analysis_ocr_rejected_blocks_total
analysis_tags_by_source_total
analysis_memory_estimate_bytes
```

## 19. Этап 14 — кеширование

### Result cache key

```text
checksum
pipeline version
model versions
request options
```

Нельзя кешировать только по checksum.

Cache должен иметь byte budget, использовать LRU, не хранить исходные изображения и PIL/numpy buffers после job, очищаться при смене model version.

### Критерий готовности

Повторный запрос того же изображения не запускает модели при совпадении версий и параметров.

## 20. Этап 15 — тестирование

### Unit tests

```text
OCR normalization
mixed-script correction
garbage scoring
reading order
evidence calibration
evidence merge
tag taxonomy
cache keys
state transitions
retry classification
VLM JSON validation
face cluster merge rules
```

### Integration tests

1. Fast analysis без CLIP.
2. Fast analysis без YOLO.
3. OCR engine exception.
4. Model cache unavailable.
5. Worker crash.
6. Queue full.
7. Invalid image.
8. Unsupported image.
9. Repeated request cache hit.
10. Enrichment failure after fast success.
11. Healthcheck under CPU load.
12. No network during startup.
13. Missing optional model.
14. Restart with persistent model volume.

### Load test

Минимальный сценарий:

```text
34 images uploaded within 15 seconds
```

Проверить:

```text
API remains healthy
all accepted jobs eventually leave PENDING
one timeout does not block rest
memory remains within profile limit
no model redownload
no duplicate processing
```

## 21. Порядок реализации

Агент обязан выполнять шаги только в таком порядке:

```text
0. Baseline and evaluation
1. API/execution stabilization
2. Persistent model cache and warmup
3. Fast pipeline
4. OCR routing
5. Image embeddings
6. Evidence/tag merger
7. Enrichment pipeline
8. Structured VLM
9. Face detection and embeddings
10. Face clustering
11. Spring server integration
12. Load testing and tuning
```

Запрещено переходить к следующему этапу, пока текущий этап не собирается, тесты не проходят, не создан отчёт, не перечислены изменённые файлы и известные ограничения.

## 22. Формат работы Codex на каждом этапе

Перед изменениями агент должен вывести:

```text
Goal
Files to inspect
Files to modify
Files to create
Public contracts affected
Risks
Tests to add
```

После изменений агент должен вывести:

```text
Implemented
Not implemented
Changed files
Architecture compliance
Tests executed
Test results
Resource impact
Known limitations
Next allowed step
```

Агент не должен писать «готово», если не запускал тесты.

Если тест нельзя запустить, агент обязан указать точную причину.

## 23. Правила коммитов

Один логический этап — один или несколько малых коммитов.

Рекомендуемый формат:

```text
analysis: add baseline evaluation harness
analysis: move heavy inference out of API loop
analysis: add persistent model registry
analysis: add routed OCR pipeline
analysis: add evidence-based tag merger
analysis: add enrichment queue
analysis: add structured VLM adapter
analysis: add face embeddings
analysis: add library-level face clustering
```

Запрещено без необходимости смешивать Docker changes, database migration, model replacement, API redesign и large formatting changes в одном коммите.

## 24. Acceptance criteria всей работы

Работа считается завершённой, когда одновременно выполнено:

1. API health отвечает при полной загрузке workers.
2. 34 изображения не блокируют очередь.
3. Один timeout не останавливает остальные jobs.
4. Fast result появляется до завершения enrichment.
5. OCR raw/display/search хранятся отдельно.
6. OCR garbage rate снижен минимум в 2 раза относительно baseline.
7. Tag precision@5 улучшен минимум на 25% относительно baseline.
8. Все финальные теги имеют category/source/reason/model version.
9. VLM можно отключить без отказа сервиса.
10. CLIP можно отключить без отказа сервиса.
11. Face clustering не выполняется внутри image analysis request.
12. Модели не скачиваются при пользовательском запросе.
13. После пересоздания контейнера model cache сохраняется.
14. Test profile укладывается в 5 GB.
15. Production profile укладывается в 20 GB.
16. Повторный анализ идентичного файла использует cache.
17. Enrichment failure даёт `PARTIALLY_COMPLETED`, а не уничтожает fast result.
18. Есть baseline report и итоговый comparison report.
19. Все миграции обратимы или имеют документированный rollback.
20. Старый endpoint удалён только после миграции Spring server.

## 25. Первый разрешённый шаг

Начать только с этапа 0.

Не менять модели.

Не менять публичный API.

Не добавлять VLM.

Не добавлять лица.

Сначала создать baseline evaluation harness, expected-result schema, скрипт оценки и отчёт текущего качества.

После этого остановиться и предоставить отчёт на проверку.
