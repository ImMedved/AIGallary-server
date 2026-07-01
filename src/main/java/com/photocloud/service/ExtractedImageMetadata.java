package com.photocloud.service;

import java.time.Instant;

public record ExtractedImageMetadata(
        Integer widthPx,
        Integer heightPx,
        Instant takenAt,
        String cameraMake,
        String cameraModel,
        String deviceName,
        Double latitude,
        Double longitude,
        String orientation
) {
    public boolean isEmpty() {
        return widthPx == null
                && heightPx == null
                && takenAt == null
                && cameraMake == null
                && cameraModel == null
                && deviceName == null
                && latitude == null
                && longitude == null
                && orientation == null;
    }
}
