package com.photocloud.dto;

import java.time.Instant;

public record MediaMetadataResponse(
        Integer widthPx,
        Integer heightPx,
        String aspectRatio,
        Instant takenAt,
        String deviceName,
        Double latitude,
        Double longitude,
        String orientation
) {
}
