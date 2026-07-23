from __future__ import annotations

import base64
import io
import json
import logging
import math
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
def _load_clip_model_cached(model_name: str, pretrained_name: str, cache_dir: str):
    import open_clip
    import torch

    logger.info("Loading OpenCLIP model=%s pretrained=%s", model_name, pretrained_name)
    model, _, preprocess = open_clip.create_model_and_transforms(model_name, pretrained=pretrained_name, cache_dir=cache_dir)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = model.to(device).eval()
    return model, preprocess, device


def load_clip_model(settings: Settings):
    _ensure_model_available(settings, "clip")
    cache_dir = settings.xdg_cache_home / "open_clip"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return _load_clip_model_cached(settings.clip_model, settings.clip_pretrained, str(cache_dir))


@lru_cache(maxsize=16)
def build_clip_prompt_inputs(model_name: str, image_kind: str, tags_key: str, device: str):
    import open_clip

    tokenizer = open_clip.get_tokenizer(model_name)
    tags = [item for item in tags_key.split("\n") if item]
    prompts: list[tuple[str, str, str]] = [(tag, clip_prompt(tag, image_kind), negative_clip_prompt(tag, image_kind)) for tag in tags]
    flattened_prompts = [prompt for _, positive, negative in prompts for prompt in (positive, negative)]
    text_input = tokenizer(flattened_prompts).to(device)
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


def negative_clip_prompt(tag: str, image_kind: str) -> str:
    if image_kind in {"screenshot", "chat_screenshot", "code_screenshot"}:
        return f"a screenshot without {tag}"
    if image_kind in {"document", "receipt"}:
        return f"a document that is not {tag}"
    return f"a photo without {tag}"


def clip_thresholds(tag: str) -> tuple[float, float, float]:
    strict_tags = {
        "receipt",
        "invoice",
        "document",
        "chat screenshot",
        "code screenshot",
        "game screenshot",
        "screenshot",
    }
    text_tags = {"text", "printed text", "handwritten text", "paper", "whiteboard", "poster"}
    if tag in strict_tags:
        return 0.225, 0.025, 0.58
    if tag in text_tags:
        return 0.205, 0.020, 0.56
    return 0.190, 0.015, 0.54


def calibrated_clip_confidence(positive_similarity: float, negative_similarity: float, tag: str) -> float:
    positive_threshold, margin_threshold, _ = clip_thresholds(tag)
    margin = positive_similarity - negative_similarity
    positive_score = (positive_similarity - positive_threshold) / 0.16
    margin_score = (margin - margin_threshold) / 0.10
    combined = 0.62 * positive_score + 0.38 * margin_score
    confidence = 1.0 / (1.0 + math.exp(-4.0 * combined))
    return round(max(0.0, min(0.97, confidence)), 4)


def clip_subtype_compatibility(tag: str, debug: AnalysisDebugPayload) -> tuple[float, str | None]:
    subtypes = debug.imageSubtypes or {}
    text_image_score = max(
        subtypes.get("document", 0.0),
        subtypes.get("form", 0.0),
        subtypes.get("receipt", 0.0),
        subtypes.get("invoice", 0.0),
        subtypes.get("chat_screenshot", 0.0),
        subtypes.get("web_screenshot", 0.0),
        subtypes.get("code_screenshot", 0.0),
        subtypes.get("ai_assistant_screenshot", 0.0),
    )
    screenshot_score = max(
        subtypes.get("chat_screenshot", 0.0),
        subtypes.get("web_screenshot", 0.0),
        subtypes.get("code_screenshot", 0.0),
        subtypes.get("ai_assistant_screenshot", 0.0),
        subtypes.get("game_screenshot", 0.0),
    )
    natural_score = max(subtypes.get("natural_photo", 0.0), subtypes.get("photo_with_text", 0.0), subtypes.get("meme", 0.0), subtypes.get("poster", 0.0))

    if tag in {"receipt", "invoice"}:
        document_score = max(subtypes.get("receipt", 0.0), subtypes.get("invoice", 0.0), subtypes.get("document", 0.0), subtypes.get("form", 0.0))
        if document_score < 0.22:
            return 0.35, "receipt/invoice requires document-like subtype evidence"
        return 1.0, None
    if tag in {"chat screenshot", "code screenshot", "game screenshot", "screenshot"}:
        if screenshot_score < 0.18 and natural_score > 0.38:
            return 0.45, "screenshot tag conflicts with natural-photo subtype evidence"
        return 1.0, None
    if tag in {"document", "paper", "printed text", "handwritten text", "text", "whiteboard"}:
        if text_image_score < 0.12 and natural_score > 0.55:
            return 0.70, "text/document tag has weak subtype support"
        return 1.0, None
    return 1.0, None


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

        scored: list[dict[str, object]] = []
        for index, (tag, positive_prompt, negative_prompt) in enumerate(prompts):
            positive_similarity = float(raw_scores[index * 2].item())
            negative_similarity = float(raw_scores[index * 2 + 1].item())
            margin = positive_similarity - negative_similarity
            confidence = calibrated_clip_confidence(positive_similarity, negative_similarity, tag)
            compatibility, compatibility_reason = clip_subtype_compatibility(tag, debug)
            calibrated = round(confidence * compatibility, 4)
            positive_threshold, margin_threshold, confidence_threshold = clip_thresholds(tag)
            rejection_reason = None
            if positive_similarity < positive_threshold:
                rejection_reason = f"positive similarity {positive_similarity:.3f} below threshold {positive_threshold:.3f}"
            elif margin < margin_threshold:
                rejection_reason = f"margin {margin:.3f} below threshold {margin_threshold:.3f}"
            elif compatibility < 1.0:
                rejection_reason = compatibility_reason
            elif calibrated < max(settings.clip_min_confidence, confidence_threshold):
                rejection_reason = f"confidence {calibrated:.3f} below threshold {max(settings.clip_min_confidence, confidence_threshold):.3f}"
            scored.append(
                {
                    "tag": tag,
                    "positive_prompt": positive_prompt,
                    "positive_similarity": positive_similarity,
                    "negative_similarity": negative_similarity,
                    "margin": margin,
                    "confidence": calibrated,
                    "accepted": rejection_reason is None,
                    "rejection_reason": rejection_reason,
                }
            )

        ordered = sorted(scored, key=lambda item: float(item["confidence"]), reverse=True)[: settings.clip_top_k]
        for item in ordered:
            tag = str(item["tag"])
            confidence = float(item["confidence"])
            positive_prompt = str(item["positive_prompt"])
            positive_similarity = float(item["positive_similarity"])
            negative_similarity = float(item["negative_similarity"])
            margin = float(item["margin"])
            accepted = bool(item["accepted"])
            rejection_reason = item["rejection_reason"]
            debug.clipScores.append(
                ClipCandidateDebug(
                    tag=tag,
                    confidence=round(confidence, 4),
                    prompt=positive_prompt,
                    rawScore=round(positive_similarity, 5),
                    rawSimilarity=round(positive_similarity, 5),
                    positiveSimilarity=round(positive_similarity, 5),
                    negativeSimilarity=round(negative_similarity, 5),
                    margin=round(margin, 5),
                    calibratedConfidence=round(confidence, 4),
                    accepted=accepted,
                    rejectionReason=str(rejection_reason) if rejection_reason else None,
                )
            )
            if accepted:
                candidates.append(
                    TagCandidate(
                        value=tag,
                        confidence=round(confidence, 4),
                        source="CLIP",
                        reason=f"calibrated semantic match margin={margin:.3f} prompt='{positive_prompt}'",
                    )
                )
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
