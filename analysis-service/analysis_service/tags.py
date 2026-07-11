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


def fixture_tags(checksum: str) -> tuple[list[TagCandidate], str | None]:
    fixture = FIXTURE_ANALYSIS.get(checksum)
    if not fixture:
        return [], None
    tags = [
        TagCandidate(value=value, confidence=confidence, source="FIXTURE", reason="checksum fixture", priority=0.50)
        for value, confidence in fixture.get("tags", [])
    ]
    return tags, fixture.get("recognizedText")


def system_tag_candidates(image_kind: str, recognized_text: str | None) -> list[TagCandidate]:
    tags = [TagCandidate(value=image_kind, confidence=0.72, source="SYSTEM", reason="image kind classifier", priority=0.02)]
    if image_kind == "photo":
        tags.append(TagCandidate(value="photo", confidence=0.70, source="SYSTEM", reason="image kind classifier"))
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
            )

    ordered = sorted(best_by_value.values(), key=lambda item: item.rank_score(), reverse=True)
    return [
        DetectedTag(value=item.value, confidence=item.confidence, source=item.source, reason=item.reason)
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
