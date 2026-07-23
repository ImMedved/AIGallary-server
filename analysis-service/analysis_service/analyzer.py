from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .image_utils import checksum_sha256, classify_image_kind, classify_image_route, image_subtype_distribution, open_image, short_checksum
from .metrics import AnalysisMetrics
from .ocr_runtime import derive_ocr_image_kind, detect_text, should_run_ocr
from .runtime import elapsed_ms, now_ms, preview_text
from .schemas import AnalysisDebugPayload, AnalyzeResponse
from .settings import AnalysisMode, OcrPolicy, Settings, load_settings
from .tags import (
    TagCandidate,
    caption_to_tag_candidates,
    contextual_tag_candidates,
    ensure_minimum_tags,
    fixture_tags,
    merge_evidence_candidates,
    system_tag_candidates,
)
from .vision import clip_tag_candidates, generate_caption_with_ollama, yolo_tag_candidates

logger = logging.getLogger("smart_gallery_analysis")
job_logger = logging.getLogger("smart_gallery_analysis.jobs")

COMPONENT_NOT_REQUESTED = "NOT_REQUESTED"
COMPONENT_SUCCEEDED = "SUCCEEDED"
COMPONENT_PARTIAL = "PARTIAL"
COMPONENT_FAILED = "FAILED"
COMPONENT_UNAVAILABLE = "UNAVAILABLE"
COMPONENT_TIMED_OUT = "TIMED_OUT"

PIPELINE_COMPLETED = "COMPLETED"
PIPELINE_PARTIALLY_COMPLETED = "PARTIALLY_COMPLETED"
PIPELINE_FAILED = "FAILED"


def serialize_tags(tags) -> list[str]:
    return [f"{tag.value}:{tag.confidence:.3f}" if tag.confidence is not None else tag.value for tag in tags]


def is_ocr_text_dominant(debug: AnalysisDebugPayload, recognized_text: str | None) -> bool:
    text = (recognized_text or "").strip()
    if len(text) < 18:
        return False
    subtypes = debug.imageSubtypes or {}
    text_route_score = max(
        subtypes.get("document", 0.0),
        subtypes.get("form", 0.0),
        subtypes.get("receipt", 0.0),
        subtypes.get("invoice", 0.0),
        subtypes.get("photo_with_text", 0.0),
        subtypes.get("web_screenshot", 0.0),
        subtypes.get("chat_screenshot", 0.0),
        subtypes.get("code_screenshot", 0.0),
        subtypes.get("ai_assistant_screenshot", 0.0),
    )
    return debug.imageKind in {"document", "receipt", "screenshot", "meme"} or text_route_score >= 0.18


def save_debug_payload(debug: AnalysisDebugPayload, settings: Settings) -> None:
    if not settings.save_debug:
        return
    try:
        directory = Path(settings.debug_dir)
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"{debug.checksum}.json"
        target.write_text(debug.model_dump_json(indent=2), encoding="utf-8")
        logger.debug("Analysis debug payload saved: %s", target)
    except Exception:
        logger.exception("Failed to save analysis debug payload")


def detect_tags(
    image,
    top_tags: int,
    checksum: str,
    recognized_text: str | None,
    caption: str | None,
    debug: AnalysisDebugPayload,
    settings: Settings,
):
    if settings.provider == "mock":
        tags = ensure_minimum_tags(
            [
                TagCandidate(value="image", confidence=0.99, source="MOCK", reason="mock provider"),
                TagCandidate(value="photo", confidence=0.95, source="MOCK", reason="mock provider"),
                TagCandidate(value="digital media", confidence=0.82, source="MOCK", reason="mock provider"),
            ],
            top_tags,
            recognized_text,
            debug.imageKind,
        )
        debug.finalTagReasons = tags
        return tags

    candidates: list[TagCandidate] = []
    fixture_candidates, _ = fixture_tags(checksum)
    candidates.extend(fixture_candidates)
    candidates.extend(system_tag_candidates(debug.imageKind, recognized_text, debug.imageSubtypes))

    raw_scores: dict[str, float] = {}
    raw_counts: dict[str, int] = {}
    if is_ocr_text_dominant(debug, recognized_text):
        debug.imageRoute = "ocr_text_dominant"
        debug.timingsMs["yolo"] = 0
        debug.timingsMs["clip"] = 0
        debug.warnings.append("visual tag models skipped: OCR text is dominant")
    else:
        yolo_candidates, raw_scores, raw_counts = yolo_tag_candidates(image, top_tags, debug, settings)
        candidates.extend(yolo_candidates)
        candidates.extend(contextual_tag_candidates(raw_scores, raw_counts, recognized_text))
        candidates.extend(clip_tag_candidates(image, debug, settings))
    candidates.extend(caption_to_tag_candidates(caption))

    if not candidates:
        candidates.extend([
            TagCandidate(value="image", confidence=0.99, source="FALLBACK", reason="no model tags were produced"),
            TagCandidate(value="photo", confidence=0.95, source="FALLBACK", reason="no model tags were produced"),
        ])

    candidates, evidence_warnings = merge_evidence_candidates(candidates, raw_counts, recognized_text, debug.imageKind, debug.imageSubtypes)
    debug.warnings.extend(evidence_warnings)
    final_tags = ensure_minimum_tags(candidates, top_tags, recognized_text, debug.imageKind)
    debug.finalTagReasons = final_tags
    logger.debug("Final tags: %s", serialize_tags(final_tags))
    return final_tags


def record_metrics(debug: AnalysisDebugPayload, tags, metrics: AnalysisMetrics | None, rejected_ocr_blocks: int) -> None:
    if metrics is None:
        return
    metrics.add_ocr_rejected_blocks(rejected_ocr_blocks)
    metrics.observe_tag_sources([tag.source or "unknown" for tag in tags])
    for stage, value in debug.timingsMs.items():
        metrics.observe_stage_ms(stage, value)


def component_errors(debug: AnalysisDebugPayload, component: str) -> list[str]:
    prefix = f"{component}:"
    return [item for item in debug.errors if item.startswith(prefix)]


def classify_component_error(message: str) -> str:
    lowered = message.lower()
    if "timed out" in lowered or "timeout" in lowered:
        return COMPONENT_TIMED_OUT
    if "unavailable" in lowered or "not available" in lowered or "missing artifacts" in lowered:
        return COMPONENT_UNAVAILABLE
    return COMPONENT_FAILED


def set_component_status(debug: AnalysisDebugPayload, component: str, status: str, errors: list[str] | None = None) -> None:
    debug.componentStatus[component] = status
    for message in errors or []:
        debug.componentErrors.append(
            {
                "code": f"{component.upper()}_{status}",
                "component": component,
                "message": message,
                "retryable": status in {COMPONENT_UNAVAILABLE, COMPONENT_TIMED_OUT, COMPONENT_FAILED},
            }
        )


def requested_yolo(debug: AnalysisDebugPayload, settings: Settings) -> bool:
    if not settings.enable_yolo or settings.provider == "mock":
        return False
    if debug.imageRoute == "ocr_text_dominant":
        return False
    return not (debug.imageKind in {"screenshot", "document", "meme"} and not settings.yolo_run_on_text_images)


def requested_clip(debug: AnalysisDebugPayload, settings: Settings) -> bool:
    if not settings.enable_clip or settings.provider == "mock":
        return False
    if debug.imageRoute == "ocr_text_dominant":
        return False
    return not (debug.imageKind in {"screenshot", "document", "meme"} and not settings.clip_run_on_text_images)


def requested_vlm(settings: Settings, enhance: bool) -> bool:
    return enhance and settings.enable_vlm and settings.provider != "mock"


def finalize_pipeline_status(
    debug: AnalysisDebugPayload,
    settings: Settings,
    enhance: bool,
    image,
    ocr_result,
    tags,
) -> None:
    ocr_requested = settings.provider != "mock" and settings.ocr_engine != "none" and should_run_ocr(derive_ocr_image_kind(image, debug), settings.ocr_policy, image)
    if not ocr_requested:
        set_component_status(debug, "ocr", COMPONENT_NOT_REQUESTED)
    else:
        errors = component_errors(debug, "ocr")
        if errors:
            set_component_status(debug, "ocr", classify_component_error(errors[-1]), errors)
        elif ocr_result is not None:
            set_component_status(debug, "ocr", COMPONENT_SUCCEEDED)
        else:
            set_component_status(debug, "ocr", COMPONENT_PARTIAL)

    for component, requested in (
        ("yolo", requested_yolo(debug, settings)),
        ("clip", requested_clip(debug, settings)),
        ("vlm", requested_vlm(settings, enhance)),
    ):
        if not requested:
            set_component_status(debug, component, COMPONENT_NOT_REQUESTED)
            continue
        errors = component_errors(debug, component)
        set_component_status(debug, component, classify_component_error(errors[-1]), errors) if errors else set_component_status(debug, component, COMPONENT_SUCCEEDED)

    requested_statuses = [
        status
        for status in debug.componentStatus.values()
        if status != COMPONENT_NOT_REQUESTED
    ]
    failed_statuses = {COMPONENT_FAILED, COMPONENT_UNAVAILABLE, COMPONENT_TIMED_OUT}
    if not tags:
        debug.pipelineStatus = PIPELINE_FAILED
    elif requested_statuses and all(status in failed_statuses for status in requested_statuses):
        debug.pipelineStatus = PIPELINE_FAILED
    elif any(status in failed_statuses or status == COMPONENT_PARTIAL for status in requested_statuses):
        debug.pipelineStatus = PIPELINE_PARTIALLY_COMPLETED
    else:
        debug.pipelineStatus = PIPELINE_COMPLETED


def analyze_content(
    content: bytes,
    filename: str | None,
    content_type: str | None,
    top_tags: int,
    include_debug: bool,
    enhance: bool,
    mode: AnalysisMode,
    ocr_policy: OcrPolicy,
    settings: Settings | None = None,
    metrics: AnalysisMetrics | None = None,
) -> AnalyzeResponse:
    settings = settings or load_settings()
    if metrics is not None:
        metrics.inc_jobs_total()
    total_start = now_ms()
    checksum = checksum_sha256(content)
    image = open_image(content)
    subtype_distribution = image_subtype_distribution(image)
    image_kind = classify_image_kind(image)
    fixture_candidates, fixture_text = fixture_tags(checksum)

    debug = AnalysisDebugPayload(
        checksum=checksum,
        filename=filename,
        imageWidth=image.width,
        imageHeight=image.height,
        provider=settings.provider,
        mode=mode,
        imageKind=image_kind,
        imageKindConfidence=max(subtype_distribution.values(), default=0.0),
        imageSubtypes=subtype_distribution,
        imageRoute=classify_image_route(subtype_distribution),
    )
    job_id = short_checksum(checksum)

    job_logger.info(
        "Analysis job started jobId=%s filename='%s' contentType='%s' bytes=%s size=%sx%s topTags=%s provider=%s kind=%s mode=%s enhance=%s",
        job_id,
        filename,
        content_type,
        len(content),
        image.width,
        image.height,
        top_tags,
        settings.provider,
        image_kind,
        mode,
        enhance,
    )

    try:
        ocr_result, ocr_blocks, rejected_ocr_blocks = detect_text(image, fixture_text, debug, settings, mode, ocr_policy)
        recognized_text = ocr_result.displayText if ocr_result else None
        caption = generate_caption_with_ollama(image.copy(), debug, settings) if enhance else None
        tags = detect_tags(image, max(1, min(top_tags, 30)), checksum, recognized_text, caption, debug, settings)
        finalize_pipeline_status(debug, settings, enhance, image, ocr_result, tags)
        debug.enrichmentScheduled = True
        debug.timingsMs["total"] = elapsed_ms(total_start)
        save_debug_payload(debug, settings)
        record_metrics(debug, tags, metrics, rejected_ocr_blocks)

        job_logger.info(
            "Analysis job completed jobId=%s status=ok totalMs=%s ocrMs=%s yoloMs=%s clipMs=%s tags=%s textPreview='%s' errors=%s",
            job_id,
            debug.timingsMs.get("total"),
            debug.timingsMs.get("ocr", 0),
            debug.timingsMs.get("yolo", 0),
            debug.timingsMs.get("clip", 0),
            serialize_tags(tags),
            preview_text(recognized_text),
            len(debug.errors),
        )

        with_debug = include_debug or settings.include_debug_by_default
        return AnalyzeResponse(
            tags=tags,
            recognizedText=recognized_text,
            pipelineStatus=debug.pipelineStatus,
            caption=caption,
            ocr=ocr_result,
            ocrBlocks=ocr_blocks if with_debug else None,
            debug=debug if with_debug else None,
        )
    except Exception as exception:
        debug.timingsMs["total"] = elapsed_ms(total_start)
        if metrics is not None:
            metrics.inc_jobs_failed_total()
        job_logger.exception(
            "Analysis job completed jobId=%s status=failed totalMs=%s error=%s",
            job_id,
            debug.timingsMs.get("total"),
            exception,
        )
        raise


def analyze_content_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    settings = load_settings()
    response = analyze_content(
        content=payload["content"],
        filename=payload.get("filename"),
        content_type=payload.get("content_type"),
        top_tags=int(payload.get("top_tags", 10)),
        include_debug=bool(payload.get("include_debug", False)),
        enhance=bool(payload.get("enhance", False)),
        mode=payload.get("mode", settings.mode),
        ocr_policy=payload.get("ocr_policy", settings.ocr_policy),
        settings=settings,
        metrics=None,
    )
    return response.model_dump(mode="json")
