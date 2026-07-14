from __future__ import annotations

import base64
import io
import json
import logging
import urllib.error
import urllib.request
from functools import lru_cache

from PIL import Image

from .errors import ModelUnavailableError
from .models.registry import ModelRegistry
from .runtime import elapsed_ms, now_ms, preview_text
from .schemas import AnalysisDebugPayload, ClipCandidateDebug, YoloDetectionDebug
from .settings import Settings
from .tags import TagCandidate
from .tags_data import DEFAULT_CLIP_TAGS

logger = logging.getLogger("smart_gallery_analysis.vision")


def _ensure_model_available(settings: Settings, name: str) -> None:
    statuses = {status.name: status for status in ModelRegistry(settings).collect_statuses(verify_checksum=False)}
    status = statuses.get(name)
    if status is None:
        return
    if status.ready or settings.allow_model_download:
        return
    raise ModelUnavailableError(f"Required model '{name}' is not available in {settings.model_cache_dir}. Run the explicit download command first.")


@lru_cache(maxsize=4)
def _load_yolo_model_cached(model_name: str, classes_key: str, local_model_path: str):
    from ultralytics import YOLO

    logger.info("Loading YOLO model %s", model_name)
    target_model = local_model_path or model_name
    model = YOLO(target_model)
    classes = [item for item in classes_key.split("|") if item]
    if classes and "world" in model_name.lower() and hasattr(model, "set_classes"):
        logger.info("Setting YOLO-World classes: %s", classes)
        model.set_classes(classes)
    return model


def load_yolo_model(settings: Settings):
    _ensure_model_available(settings, "yolo")
    local_candidate = settings.yolo_config_dir / settings.yolo_model
    if settings.allow_model_download:
        local_candidate.parent.mkdir(parents=True, exist_ok=True)
    return _load_yolo_model_cached(settings.yolo_model, "|".join(settings.yolo_world_classes), str(local_candidate) if (local_candidate.exists() or settings.allow_model_download) else "")


@lru_cache(maxsize=4)
def _load_clip_model_cached(model_name: str, pretrained_name: str):
    import open_clip
    import torch

    logger.info("Loading OpenCLIP model=%s pretrained=%s", model_name, pretrained_name)
    model, _, preprocess = open_clip.create_model_and_transforms(model_name, pretrained=pretrained_name)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = model.to(device).eval()
    return model, preprocess, device


def load_clip_model(settings: Settings):
    _ensure_model_available(settings, "clip")
    return _load_clip_model_cached(settings.clip_model, settings.clip_pretrained)


@lru_cache(maxsize=16)
def build_clip_prompt_inputs(model_name: str, image_kind: str, tags_key: str, device: str):
    import open_clip

    tokenizer = open_clip.get_tokenizer(model_name)
    tags = [item for item in tags_key.split("\n") if item]
    prompts: list[tuple[str, str]] = [(tag, clip_prompt(tag, image_kind)) for tag in tags]
    text_input = tokenizer([prompt for _, prompt in prompts]).to(device)
    return prompts, text_input


def yolo_tag_candidates(image: Image.Image, top_tags: int, debug: AnalysisDebugPayload, settings: Settings) -> tuple[list[TagCandidate], dict[str, float], dict[str, int]]:
    raw_scores: dict[str, float] = {}
    raw_counts: dict[str, int] = {}
    candidates: list[TagCandidate] = []
    started = now_ms()

    if not settings.enable_yolo or settings.provider == "mock":
        debug.timingsMs["yolo"] = 0
        return candidates, raw_scores, raw_counts

    if debug.imageKind in {"screenshot", "document", "meme"} and not settings.yolo_run_on_text_images:
        debug.timingsMs["yolo"] = 0
        return candidates, raw_scores, raw_counts

    try:
        model = load_yolo_model(settings)
        results = model.predict(
            source=image,
            verbose=False,
            conf=settings.yolo_confidence,
            imgsz=settings.yolo_image_size,
            iou=0.45,
            max_det=max(12, top_tags * 4),
        )

        for result in results:
            names = result.names
            boxes = getattr(result, "boxes", None)
            if boxes is None:
                continue
            cls_values = boxes.cls.tolist()
            conf_values = boxes.conf.tolist()
            for cls_id, conf in zip(cls_values, conf_values):
                label = names.get(int(cls_id), str(int(cls_id))).strip().lower()
                raw_counts[label] = raw_counts.get(label, 0) + 1
                best = raw_scores.get(label)
                if best is None or conf > best:
                    raw_scores[label] = float(conf)

        ordered = sorted(raw_scores.items(), key=lambda item: (item[1], raw_counts.get(item[0], 0)), reverse=True)
        debug.rawYoloLabels = [
            YoloDetectionDebug(label=label, confidence=round(score, 4), count=raw_counts.get(label, 0))
            for label, score in ordered[:25]
        ]
        candidates.extend(
            TagCandidate(value=label, confidence=round(score, 4), source="YOLO", reason=f"object detector count={raw_counts.get(label, 0)}", priority=0.04)
            for label, score in ordered
        )
        logger.debug("YOLO detections raw=%s counts=%s", {label: round(score, 4) for label, score in ordered[:10]}, raw_counts)
    except Exception as exception:
        debug.errors.append(f"yolo: {exception}")
        logger.exception("YOLO detection unavailable")
    finally:
        debug.timingsMs["yolo"] = elapsed_ms(started)

    return candidates, raw_scores, raw_counts


def clip_prompt(tag: str, image_kind: str) -> str:
    if image_kind == "document":
        return f"a document containing {tag}"
    if image_kind in {"screenshot", "meme"}:
        return f"a screenshot of {tag}"
    return f"a photo of {tag}"


def clip_tag_candidates(image: Image.Image, debug: AnalysisDebugPayload, settings: Settings) -> list[TagCandidate]:
    if not settings.enable_clip or settings.provider == "mock":
        debug.timingsMs["clip"] = 0
        return []
    if debug.imageKind in {"screenshot", "document", "meme"} and not settings.clip_run_on_text_images:
        debug.timingsMs["clip"] = 0
        return []

    started = now_ms()
    candidates: list[TagCandidate] = []
    try:
        import torch

        model, preprocess, device = load_clip_model(settings)
        tags = settings.clip_tags or DEFAULT_CLIP_TAGS
        tags_key = "\n".join(tags)
        prompts, text_input = build_clip_prompt_inputs(settings.clip_model, debug.imageKind, tags_key, device)

        clip_image = image.copy()
        clip_image.thumbnail((768, 768))
        image_input = preprocess(clip_image).unsqueeze(0).to(device)

        with torch.no_grad():
            image_features = model.encode_image(image_input)
            text_features = model.encode_text(text_input)
            image_features = image_features / image_features.norm(dim=-1, keepdim=True)
            text_features = text_features / text_features.norm(dim=-1, keepdim=True)
            raw_scores = (image_features @ text_features.T)[0]

        best_by_tag: dict[str, tuple[float, str]] = {}
        for index, (tag, prompt) in enumerate(prompts):
            raw = float(raw_scores[index].item())
            previous = best_by_tag.get(tag)
            if previous is None or raw > previous[0]:
                best_by_tag[tag] = (raw, prompt)

        values = [score for score, _ in best_by_tag.values()]
        if not values:
            return []
        minimum = min(values)
        maximum = max(values)
        denominator = max(1e-6, maximum - minimum)

        ordered = sorted(best_by_tag.items(), key=lambda item: item[1][0], reverse=True)[: settings.clip_top_k]
        for tag, (raw, prompt) in ordered:
            normalized = (raw - minimum) / denominator
            confidence = round(normalized, 4)
            debug.clipScores.append(ClipCandidateDebug(tag=tag, confidence=confidence, prompt=prompt, rawScore=round(raw, 5)))
            if confidence >= settings.clip_min_confidence:
                candidates.append(TagCandidate(value=tag, confidence=confidence, source="CLIP", reason=f"semantic image/text similarity prompt='{prompt}'"))
        logger.debug("CLIP scores=%s", [(item.tag, item.confidence) for item in debug.clipScores[:10]])
    except Exception as exception:
        debug.errors.append(f"clip: {exception}")
        logger.exception("CLIP tagging unavailable")
    finally:
        debug.timingsMs["clip"] = elapsed_ms(started)

    return candidates


def generate_caption_with_ollama(image: Image.Image, debug: AnalysisDebugPayload, settings: Settings) -> str | None:
    if not settings.enable_vlm or settings.provider == "mock":
        debug.timingsMs["vlm"] = 0
        return None

    started = now_ms()
    try:
        buffer = io.BytesIO()
        image.thumbnail((1280, 1280))
        image.save(buffer, format="JPEG", quality=88)
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        payload = {
            "model": settings.vlm_model,
            "prompt": "Describe this image in one short factual English sentence. Do not invent details.",
            "images": [encoded],
            "stream": False,
        }
        request = urllib.request.Request(
            f"{settings.ollama_url}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=settings.vlm_timeout_seconds) as response:
            raw = response.read().decode("utf-8")
        result = json.loads(raw)
        caption = result.get("response")
        caption = " ".join(str(caption or "").split()) or None
        debug.vlmCaption = caption
        logger.debug("VLM caption='%s'", preview_text(caption))
        return caption
    except (urllib.error.URLError, TimeoutError, Exception) as exception:
        debug.errors.append(f"vlm: {exception}")
        logger.exception("VLM caption unavailable")
        return None
    finally:
        debug.timingsMs["vlm"] = elapsed_ms(started)
