package com.photocloud.dto;

import com.photocloud.entity.AnalysisStatus;
import com.photocloud.entity.MediaType;
import com.photocloud.entity.ProcessingStatus;

import java.time.Instant;
import java.util.List;
import java.util.UUID;

public record MediaResponse(
        Long id,
        UUID uuid,
        MediaType mediaType,
        ProcessingStatus processingStatus,
        AnalysisStatus analysisStatus,
        String filename,
        String mimeType,
        long sizeBytes,
        String checksumSha256,
        Instant uploadedAt,
        MediaMetadataResponse metadata,
        String recognizedText,
        List<String> tags,
        List<String> people,
        String thumbnailUrl,
        String originalUrl
) {
}
