from __future__ import annotations

from pydantic import BaseModel, Field


class DetectedTag(BaseModel):
    value: str
    confidence: float | None = None
    source: str | None = None
    reason: str | None = None


class OcrBlock(BaseModel):
    text: str
    confidence: float | None = None
    bbox: list[float] | None = None


class OcrCandidateDebug(BaseModel):
    name: str
    width: int
    height: int
    lineCount: int
    charCount: int
    averageConfidence: float | None = None
    validCharRatio: float | None = None
    mixedScriptTokenRatio: float | None = None
    score: float
    accepted: bool = False
    preview: str | None = None
    rejectionReason: str | None = None
    error: str | None = None


class YoloDetectionDebug(BaseModel):
    label: str
    confidence: float
    count: int


class ClipCandidateDebug(BaseModel):
    tag: str
    confidence: float
    prompt: str
    rawScore: float | None = None


class AnalysisDebugPayload(BaseModel):
    checksum: str
    filename: str | None = None
    imageWidth: int
    imageHeight: int
    provider: str
    mode: str
    imageKind: str
    timingsMs: dict[str, int] = Field(default_factory=dict)
    ocrCandidates: list[OcrCandidateDebug] = Field(default_factory=list)
    ocrBlocks: list[OcrBlock] = Field(default_factory=list)
    rawYoloLabels: list[YoloDetectionDebug] = Field(default_factory=list)
    clipScores: list[ClipCandidateDebug] = Field(default_factory=list)
    finalTagReasons: list[DetectedTag] = Field(default_factory=list)
    vlmCaption: str | None = None
    errors: list[str] = Field(default_factory=list)


class AnalyzeResponse(BaseModel):
    tags: list[DetectedTag]
    recognizedText: str | None = None
    caption: str | None = None
    ocrBlocks: list[OcrBlock] | None = None
    debug: AnalysisDebugPayload | None = None
