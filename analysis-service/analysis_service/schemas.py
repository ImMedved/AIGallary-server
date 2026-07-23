from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class DetectedTag(BaseModel):
    value: str
    confidence: float | None = None
    source: str | None = None
    reason: str | None = None
    category: str | None = None
    quality: str | None = None
    modelName: str | None = None
    modelVersion: str | None = None
    validated: bool | None = None


class OcrBlock(BaseModel):
    rawText: str
    displayText: str
    searchText: str
    confidence: float | None = None
    bbox: list[float] | None = None
    language: str | None = None
    quality: str | None = None
    engine: str | None = None
    variant: str | None = None
    correctionTrace: list[str] = Field(default_factory=list)
    text: str | None = None

    @model_validator(mode="after")
    def ensure_legacy_text(self) -> "OcrBlock":
        if self.text is None:
            self.text = self.displayText
        return self


class OcrResult(BaseModel):
    rawText: str | None = None
    displayText: str | None = None
    searchText: str | None = None
    languageHints: list[str] = Field(default_factory=list)
    averageConfidence: float | None = None
    quality: str | None = None
    blocks: list[OcrBlock] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class OcrCandidateDebug(BaseModel):
    name: str
    width: int
    height: int
    lineCount: int
    charCount: int
    averageConfidence: float | None = None
    validCharRatio: float | None = None
    mixedScriptTokenRatio: float | None = None
    repetitionRatio: float | None = None
    languagePlausibility: float | None = None
    geometryScore: float | None = None
    lineConsistency: float | None = None
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
    rawSimilarity: float | None = None
    positiveSimilarity: float | None = None
    negativeSimilarity: float | None = None
    margin: float | None = None
    calibratedConfidence: float | None = None
    accepted: bool = False
    rejectionReason: str | None = None


class AnalysisDebugPayload(BaseModel):
    checksum: str
    filename: str | None = None
    imageWidth: int
    imageHeight: int
    provider: str
    mode: str
    imageKind: str
    imageKindConfidence: float | None = None
    imageSubtypes: dict[str, float] = Field(default_factory=dict)
    imageRoute: str | None = None
    pipelineStatus: str = "COMPLETED"
    componentStatus: dict[str, str] = Field(default_factory=dict)
    componentErrors: list[dict[str, object]] = Field(default_factory=list)
    enrichmentScheduled: bool = False
    timingsMs: dict[str, int] = Field(default_factory=dict)
    ocrCandidates: list[OcrCandidateDebug] = Field(default_factory=list)
    ocrBlocks: list[OcrBlock] = Field(default_factory=list)
    rawYoloLabels: list[YoloDetectionDebug] = Field(default_factory=list)
    clipScores: list[ClipCandidateDebug] = Field(default_factory=list)
    finalTagReasons: list[DetectedTag] = Field(default_factory=list)
    vlmCaption: str | None = None
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class AnalyzeResponse(BaseModel):
    tags: list[DetectedTag]
    recognizedText: str | None = None
    pipelineStatus: str = "COMPLETED"
    caption: str | None = None
    ocr: OcrResult | None = None
    ocrBlocks: list[OcrBlock] | None = None
    debug: AnalysisDebugPayload | None = None
