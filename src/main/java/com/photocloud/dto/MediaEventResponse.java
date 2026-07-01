package com.photocloud.dto;

import java.time.Instant;
import java.util.List;
import java.util.UUID;

public record MediaEventResponse(
        String eventType,
        Long mediaId,
        UUID mediaUuid,
        String processingStatus,
        String analysisStatus,
        List<String> tags,
        Instant timestamp
) {
}
