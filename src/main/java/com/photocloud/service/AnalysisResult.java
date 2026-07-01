package com.photocloud.service;

import com.photocloud.entity.AnalysisStatus;

import java.util.List;

public record AnalysisResult(
        AnalysisStatus status,
        List<GeneratedTag> tags,
        String recognizedText
) {
}
