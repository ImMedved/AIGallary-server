# Smart Gallery analysis module fix

Замените файлы в модуле анализа:

- `app_fixed.py` -> `app.py`
- `requirements_fixed.txt` -> `requirements.txt`
- `requirements-ml_fixed.txt` -> `requirements-ml.txt`
- `Dockerfile_fixed` -> `Dockerfile`

## Что изменено

1. OCR больше не выбирает результат только по длине. Добавлена оценка качества текста: confidence, доля нормальных символов, доля смешанных латиница/кириллица токенов, повторяющийся шум, подозрительные символы.
2. Добавлен EasyOCR как основной OCR для `ru,en`, PaddleOCR оставлен как fallback или второй движок в `best` режиме.
3. Добавлены режимы `fast`, `quality`, `best` и `ocrPolicy`: `auto`, `always`, `skip`.
4. Для скриншотов/документов/мемов YOLO по умолчанию пропускается, потому что COCO-детектор дает бедные и часто бесполезные теги.
5. CLIP больше не использует глобальный softmax по всем prompt. Теперь используется относительная оценка cosine similarity, поэтому теги меньше зависят от длины списка тегов.
6. Добавлены системные теги по типу изображения: `photo`, `screenshot`, `document`, `meme`, а также теги по OCR: `text`, `cyrillic text`, `latin text`, `code screenshot`, `web page`.
7. Добавлен `/warmup`, чтобы загрузить модели заранее.
8. Добавлен `/analyze-batch` для пачки файлов в одном запросе.

## Рекомендуемый запуск

```powershell
docker build --build-arg INSTALL_ML=true -t smart-gallery-analysis .
docker run --rm -p 8090:8090 smart-gallery-analysis
```

Для более быстрого, но менее полного режима:

```powershell
docker run --rm -p 8090:8090 -e ANALYSIS_MODE=fast -e OCR_RUN_ON_PHOTOS_FAST=false smart-gallery-analysis
```

Для более качественного OCR, но медленнее:

```powershell
docker run --rm -p 8090:8090 -e ANALYSIS_MODE=best -e OCR_ENGINE=both smart-gallery-analysis
```

## Важные переменные

- `OCR_ENGINE=easyocr|paddle|auto|both`
- `OCR_LANGUAGES=ru,en`
- `ANALYSIS_MODE=fast|quality|best`
- `OCR_POLICY=auto|always|skip`
- `YOLO_RUN_ON_TEXT_IMAGES=false`
- `ENABLE_CLIP=true`
- `ENABLE_VLM=false`
- `OLLAMA_URL=http://host.docker.internal:11434`
- `VLM_MODEL=llava:7b`

## Следующий этап

Для качественных смысловых тегов лучше добавить отдельный VLM/BLIP/Qwen2.5-VL этап, который будет запускаться не на каждый файл, а по кнопке, ночью или для файлов с низкой уверенностью. YOLO COCO не предназначен для богатой семантической разметки личной галереи.
