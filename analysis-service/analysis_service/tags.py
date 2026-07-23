from __future__ import annotations

import re
from dataclasses import dataclass

from .schemas import DetectedTag
from .tags_data import (
    ANIMAL_LABELS,
    CAPTION_KEYWORD_TAGS,
    DOCUMENT_LABELS,
    ELECTRONICS_LABELS,
    FIXTURE_ANALYSIS,
    FURNITURE_LABELS,
    GENERIC_TAGS,
    TAG_HINTS,
    TRANSPORT_LABELS,
)


@dataclass(frozen=True)
class TagCandidate:
    value: str
    confidence: float | None
    source: str
    reason: str
    priority: float = 0.0
    category: str | None = None
    model_name: str | None = None
    model_version: str | None = None
    validated: bool | None = None

    def rank_score(self) -> float:
        confidence = self.confidence if self.confidence is not None else 0.0
        generic_penalty = -0.18 if normalize_tag_value(self.value) in GENERIC_TAGS else 0.0
        return confidence + self.priority + source_priority(self.source) + generic_penalty


def source_priority(source: str) -> float:
    return {
        "FIXTURE": 0.30,
        "VLM": 0.16,
        "YOLO": 0.12,
        "OCR": 0.10,
        "SYSTEM": 0.08,
        "CONTEXT": 0.06,
        "CLIP": 0.02,
        "FALLBACK": -0.08,
    }.get(source.upper(), 0.0)


def normalize_tag_value(value: str) -> str:
    normalized = re.sub(r"[\s_-]+", " ", value.strip().lower())
    aliases = {
        "person": "people",
        "human": "people",
        "cell phone": "phone",
        "mobile phone": "phone",
        "tv": "screen",
        "dining table": "table",
        "couch": "sofa",
        "bus-stop": "bus stop",
        "electronic-display": "electronic display",
        "printed object": "document",
        "printed text": "text",
    }
    return aliases.get(normalized, normalized)


TAXONOMY_VERSION = "tag-merger-v1"

SUBTYPE_TAGS = {
    "natural_photo",
    "photo_with_text",
    "screenshot",
    "meme",
    "poster",
    "document",
    "form",
    "receipt",
    "invoice",
    "web_screenshot",
    "ai_assistant_screenshot",
    "code_screenshot",
    "chat_screenshot",
    "game_screenshot",
    "unknown",
}

MEDIA_TAGS = {"image", "photo", "picture", "digital media"}
TEXT_TAGS = {"text", "printed text", "handwritten text", "cyrillic text", "latin text", "paper", "whiteboard", "document"}
PEOPLE_TAGS = {"people", "portrait", "selfie", "face", "group photo"}
OBJECT_TAGS = (
    ANIMAL_LABELS
    | TRANSPORT_LABELS
    | FURNITURE_LABELS
    | ELECTRONICS_LABELS
    | DOCUMENT_LABELS
    | {
        "vehicle",
        "bus stop",
        "street",
        "city",
        "building",
        "food",
        "drink",
        "coffee",
        "restaurant",
        "computer",
        "monitor",
        "screen",
        "keyboard",
        "phone",
        "table",
        "sofa",
        "bedroom",
        "kitchen",
        "books",
        "bookshelf",
        "library",
        "sign",
        "map",
        "diagram",
    }
)
STYLE_TAGS = {"anime", "illustration", "drawing", "art", "meme", "night", "party", "sports", "flower"}


def infer_tag_category(value: str, source: str) -> str:
    tag = normalize_tag_value(value)
    if tag in SUBTYPE_TAGS:
        return "image_subtype"
    if tag in MEDIA_TAGS:
        return "media"
    if tag in TEXT_TAGS:
        return "text"
    if tag in PEOPLE_TAGS:
        return "people"
    if tag in OBJECT_TAGS:
        return "object"
    if tag in STYLE_TAGS:
        return "style"
    if source.upper() == "OCR":
        return "text"
    return "semantic"


def model_name_for_source(source: str) -> str:
    return {
        "FIXTURE": "checksum-fixture",
        "VLM": "ollama-vlm",
        "YOLO": "ultralytics-yolo",
        "OCR": "ocr-runtime",
        "SYSTEM": "image-subtype-heuristics",
        "CONTEXT": "tag-context-rules",
        "CLIP": "openclip",
        "FALLBACK": "fallback-rules",
        "MOCK": "mock-provider",
    }.get(source.upper(), source.lower() or "unknown")


def confidence_quality(confidence: float | None, source_count: int, validated: bool) -> str:
    value = confidence if confidence is not None else 0.0
    if validated and (source_count >= 2 or value >= 0.82):
        return "high"
    if validated or value >= 0.66:
        return "medium"
    return "low"


def has_receipt_or_invoice_text(recognized_text: str | None) -> bool:
    lowered = (recognized_text or "").lower()
    receipt_tokens = ("receipt", "invoice", "total", "subtotal", "vat", "tax", "eur", "usd", "руб", "₽", "$", "€")
    return any(token in lowered for token in receipt_tokens) and bool(re.search(r"\d+[.,]\d{2}|\b\d{2,}\b", lowered))


def subtype_support(subtypes: dict[str, float], *names: str) -> float:
    return max((subtypes or {}).get(name, 0.0) for name in names) if names else 0.0


def evidence_supported(
    value: str,
    source: str,
    source_count: int,
    raw_counts: dict[str, int],
    recognized_text: str | None,
    image_kind: str,
    subtype_distribution: dict[str, float],
) -> tuple[bool, str | None]:
    tag = normalize_tag_value(value)
    source_upper = source.upper()
    document_support = subtype_support(subtype_distribution, "document", "form", "receipt", "invoice")
    screenshot_support = subtype_support(
        subtype_distribution,
        "chat_screenshot",
        "web_screenshot",
        "code_screenshot",
        "ai_assistant_screenshot",
        "game_screenshot",
    )
    natural_support = subtype_support(subtype_distribution, "natural_photo", "photo_with_text")

    if source_upper in {"FIXTURE", "SYSTEM", "YOLO", "OCR"}:
        return True, None
    if source_count >= 2:
        return True, None

    if tag in {"receipt", "invoice"} and source_upper in {"CLIP", "VLM", "CONTEXT"}:
        if document_support >= 0.18 or has_receipt_or_invoice_text(recognized_text):
            return True, None
        return False, "receipt/invoice semantic tag rejected without document subtype or payment text evidence"

    if tag == "group photo":
        if raw_counts.get("person", 0) >= 2:
            return True, None
        return False, "group photo rejected without multiple detected people"

    if tag in {"chat screenshot", "code screenshot", "game screenshot", "screenshot"} and source_upper in {"CLIP", "VLM"}:
        if screenshot_support >= 0.18 or image_kind in {"screenshot", "chat_screenshot", "code_screenshot"}:
            return True, None
        return False, "screenshot semantic tag rejected without screenshot subtype evidence"

    if tag in {"document", "paper", "printed text", "handwritten text", "whiteboard"} and source_upper in {"CLIP", "VLM"}:
        if document_support >= 0.14 or recognized_text:
            return True, None
        if natural_support >= 0.45:
            return False, "document/text semantic tag rejected on natural-photo subtype without OCR evidence"

    if tag in {"transport", "vehicle", "bus stop"} and source_upper == "CLIP":
        if raw_counts.keys() & TRANSPORT_LABELS:
            return True, None
        return False, "transport semantic tag rejected without detector support"

    return True, None


def candidate_is_validated(
    value: str,
    source: str,
    source_count: int,
    raw_counts: dict[str, int],
    recognized_text: str | None,
    image_kind: str,
    subtype_distribution: dict[str, float],
) -> bool:
    tag = normalize_tag_value(value)
    source_upper = source.upper()
    if source_count >= 2 or source_upper in {"FIXTURE", "SYSTEM", "YOLO", "OCR", "CONTEXT"}:
        return True
    if tag in {"receipt", "invoice"}:
        return subtype_support(subtype_distribution, "document", "form", "receipt", "invoice") >= 0.18 or has_receipt_or_invoice_text(recognized_text)
    if tag == "group photo":
        return raw_counts.get("person", 0) >= 2
    if tag in {"chat screenshot", "code screenshot", "game screenshot", "screenshot"}:
        return subtype_support(
            subtype_distribution,
            "chat_screenshot",
            "web_screenshot",
            "code_screenshot",
            "ai_assistant_screenshot",
            "game_screenshot",
        ) >= 0.18 or image_kind in {"screenshot", "chat_screenshot", "code_screenshot"}
    if tag in {"document", "paper", "printed text", "handwritten text", "whiteboard"}:
        return subtype_support(subtype_distribution, "document", "form", "receipt", "invoice") >= 0.14 or bool(recognized_text)
    if tag in {"transport", "vehicle", "bus stop"}:
        return bool(raw_counts.keys() & TRANSPORT_LABELS)
    return False


def merge_evidence_candidates(
    candidates: list[TagCandidate],
    raw_counts: dict[str, int],
    recognized_text: str | None,
    image_kind: str,
    subtype_distribution: dict[str, float] | None,
) -> tuple[list[TagCandidate], list[str]]:
    subtypes = subtype_distribution or {}
    grouped: dict[str, list[TagCandidate]] = {}
    for candidate in candidates:
        normalized = normalize_tag_value(candidate.value)
        if normalized:
            grouped.setdefault(normalized, []).append(candidate)

    merged: list[TagCandidate] = []
    warnings: list[str] = []
    for value, group in grouped.items():
        best = max(group, key=lambda item: item.rank_score())
        source_count = len({item.source.upper() for item in group})
        supported, rejection_reason = evidence_supported(
            value,
            best.source,
            source_count,
            raw_counts,
            recognized_text,
            image_kind,
            subtypes,
        )
        if not supported:
            warnings.append(f"tag '{value}' rejected: {rejection_reason}")
            continue

        confidence_values = [item.confidence for item in group if item.confidence is not None]
        confidence = best.confidence
        if source_count >= 2 and confidence_values:
            confidence = round(min(0.98, max(confidence_values) + min(0.08, 0.025 * (source_count - 1))), 4)
        validated = best.validated if best.validated is not None else candidate_is_validated(
            value,
            best.source,
            source_count,
            raw_counts,
            recognized_text,
            image_kind,
            subtypes,
        )
        category = best.category or infer_tag_category(value, best.source)
        reason = best.reason
        if source_count >= 2:
            reason = f"{reason}; corroborated by {source_count} sources"
        merged.append(
            TagCandidate(
                value=value,
                confidence=confidence,
                source=best.source,
                reason=reason,
                priority=best.priority + min(0.08, 0.025 * (source_count - 1)),
                category=category,
                model_name=best.model_name or model_name_for_source(best.source),
                model_version=best.model_version or TAXONOMY_VERSION,
                validated=validated,
            )
        )
    return merged, warnings


def fixture_tags(checksum: str) -> tuple[list[TagCandidate], str | None]:
    fixture = FIXTURE_ANALYSIS.get(checksum)
    if not fixture:
        return [], None
    tags = [
        TagCandidate(value=value, confidence=confidence, source="FIXTURE", reason="checksum fixture", priority=0.50)
        for value, confidence in fixture.get("tags", [])
    ]
    return tags, fixture.get("recognizedText")


def system_tag_candidates(image_kind: str, recognized_text: str | None, subtype_distribution: dict[str, float] | None = None) -> list[TagCandidate]:
    subtype_distribution = subtype_distribution or {}
    image_kind_confidence = max(subtype_distribution.values(), default=0.72)
    tags = [TagCandidate(value=image_kind, confidence=round(image_kind_confidence, 4), source="SYSTEM", reason="image subtype classifier", priority=0.02)]
    for subtype, confidence in sorted(subtype_distribution.items(), key=lambda item: item[1], reverse=True)[:3]:
        if subtype != image_kind and confidence >= 0.18:
            tags.append(TagCandidate(value=subtype, confidence=confidence, source="SYSTEM", reason="image subtype distribution"))
    if image_kind == "natural_photo":
        tags.append(TagCandidate(value="photo", confidence=0.70, source="SYSTEM", reason="image kind classifier"))
    if image_kind == "receipt":
        tags.append(TagCandidate(value="document", confidence=0.74, source="SYSTEM", reason="receipt subtype classifier"))
    if image_kind == "code_screenshot":
        tags.append(TagCandidate(value="screenshot", confidence=0.76, source="SYSTEM", reason="code screenshot subtype classifier"))
        tags.append(TagCandidate(value="code screenshot", confidence=0.82, source="SYSTEM", reason="code screenshot subtype classifier"))
    if image_kind == "chat_screenshot":
        tags.append(TagCandidate(value="screenshot", confidence=0.76, source="SYSTEM", reason="chat screenshot subtype classifier"))
        tags.append(TagCandidate(value="chat screenshot", confidence=0.82, source="SYSTEM", reason="chat screenshot subtype classifier"))
    if recognized_text:
        lowered = recognized_text.lower()
        tags.append(TagCandidate(value="text", confidence=0.84, source="OCR", reason="OCR recognized non-empty text", priority=0.05))
        if len(recognized_text) >= 30:
            tags.append(TagCandidate(value="document", confidence=0.70, source="OCR", reason="recognized text length >= 30"))
        if any("а" <= char <= "я" or char == "ё" for char in lowered):
            tags.append(TagCandidate(value="cyrillic text", confidence=0.82, source="OCR", reason="recognized text contains Cyrillic"))
        if any("a" <= char <= "z" for char in lowered):
            tags.append(TagCandidate(value="latin text", confidence=0.74, source="OCR", reason="recognized text contains Latin"))
        if any(token in lowered for token in ["public class", "import ", "function", "const ", "return ", "#include"]):
            tags.append(TagCandidate(value="code screenshot", confidence=0.82, source="OCR", reason="code-like text tokens"))
        if any(token in lowered for token in ["http", "www", ".com", ".ru", ".org"]):
            tags.append(TagCandidate(value="web page", confidence=0.74, source="OCR", reason="url-like text tokens"))
    return tags


def contextual_tag_candidates(raw_scores: dict[str, float], raw_counts: dict[str, int], recognized_text: str | None) -> list[TagCandidate]:
    tags: list[TagCandidate] = []
    labels = set(raw_scores.keys())

    for label, score in sorted(raw_scores.items(), key=lambda item: item[1], reverse=True):
        for hint, confidence in TAG_HINTS.get(label, []):
            tags.append(TagCandidate(value=hint, confidence=round(min(score, confidence), 4), source="CONTEXT", reason=f"hint from YOLO label '{label}'"))

    if labels & TRANSPORT_LABELS:
        tags.append(TagCandidate(value="transport", confidence=0.81, source="CONTEXT", reason="transport object labels present"))
    if labels & ANIMAL_LABELS:
        tags.append(TagCandidate(value="animal", confidence=0.80, source="CONTEXT", reason="animal object labels present"))
    if labels & FURNITURE_LABELS:
        tags.append(TagCandidate(value="interior", confidence=0.76, source="CONTEXT", reason="furniture object labels present"))
    if labels & ELECTRONICS_LABELS:
        tags.append(TagCandidate(value="electronics", confidence=0.78, source="CONTEXT", reason="electronics object labels present"))
    if labels & DOCUMENT_LABELS:
        tags.append(TagCandidate(value="printed object", confidence=0.73, source="CONTEXT", reason="document-like object labels present"))

    person_count = raw_counts.get("person", 0)
    if person_count >= 2:
        tags.append(TagCandidate(value="group photo", confidence=0.80, source="CONTEXT", reason="two or more people detected", priority=0.08))
    elif person_count == 1:
        tags.append(TagCandidate(value="portrait", confidence=0.72, source="CONTEXT", reason="single person detected"))

    if recognized_text:
        tags.extend(system_tag_candidates("document", recognized_text))
    return tags


def caption_to_tag_candidates(caption: str | None) -> list[TagCandidate]:
    if not caption:
        return []
    lowered = caption.lower()
    tags = [TagCandidate(value="captioned", confidence=0.64, source="VLM", reason="VLM caption generated")]
    for words, tag, confidence in CAPTION_KEYWORD_TAGS:
        if any(word in lowered for word in words):
            tags.append(TagCandidate(value=tag, confidence=confidence, source="VLM", reason=f"caption keyword matched: {tag}", priority=0.05))
    return tags


def deduplicate_tag_candidates(candidates: list[TagCandidate], top_tags: int) -> list[DetectedTag]:
    best_by_value: dict[str, TagCandidate] = {}
    for candidate in candidates:
        normalized = normalize_tag_value(candidate.value)
        if not normalized:
            continue
        previous = best_by_value.get(normalized)
        if previous is None or candidate.rank_score() > previous.rank_score():
            best_by_value[normalized] = TagCandidate(
                value=normalized,
                confidence=candidate.confidence,
                source=candidate.source,
                reason=candidate.reason,
                priority=candidate.priority,
                category=candidate.category or infer_tag_category(normalized, candidate.source),
                model_name=candidate.model_name or model_name_for_source(candidate.source),
                model_version=candidate.model_version or TAXONOMY_VERSION,
                validated=candidate.validated,
            )

    ordered = sorted(best_by_value.values(), key=lambda item: item.rank_score(), reverse=True)
    return [
        DetectedTag(
            value=item.value,
            confidence=item.confidence,
            source=item.source,
            reason=item.reason,
            category=item.category or infer_tag_category(item.value, item.source),
            quality=confidence_quality(item.confidence, 1, bool(item.validated)),
            modelName=item.model_name or model_name_for_source(item.source),
            modelVersion=item.model_version or TAXONOMY_VERSION,
            validated=bool(item.validated),
        )
        for item in ordered[:top_tags]
    ]


def ensure_minimum_tags(candidates: list[TagCandidate], top_tags: int, recognized_text: str | None, image_kind: str) -> list[DetectedTag]:
    detected = deduplicate_tag_candidates(candidates, top_tags)
    if len(detected) >= min(3, top_tags):
        return detected

    supplements: list[TagCandidate] = []
    existing = {tag.value.lower() for tag in detected}
    if recognized_text and "text" not in existing:
        supplements.append(TagCandidate(value="text", confidence=0.78, source="FALLBACK", reason="recognized text exists"))
    if image_kind not in existing:
        supplements.append(TagCandidate(value=image_kind, confidence=0.70, source="FALLBACK", reason="image kind fallback"))
    if "image" not in existing:
        supplements.append(TagCandidate(value="image", confidence=0.62, source="FALLBACK", reason="minimum tag fallback"))
    return deduplicate_tag_candidates(candidates + supplements, top_tags)
