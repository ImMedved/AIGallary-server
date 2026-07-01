package com.photocloud.service;

import java.util.List;

public record RemoteAnalysisResponse(
        List<RemoteDetectedTag> tags,
        String recognizedText
) {
}
