package com.photocloud.service;

import org.junit.jupiter.api.Test;

import java.time.Instant;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertTrue;

class MetadataTagServiceTest {

    private final MetadataTagService metadataTagService = new MetadataTagService();

    @Test
    void shouldCreateInitialMetadataTags() {
        ExtractedImageMetadata metadata = new ExtractedImageMetadata(
                4000,
                3000,
                Instant.parse("2024-04-12T10:15:30Z"),
                "Google",
                "Pixel 8",
                "Google Pixel 8",
                46.05,
                14.51,
                "Horizontal (normal)"
        );

        List<String> tags = metadataTagService.createTags(metadata);

        assertTrue(tags.contains("year:2024"));
        assertTrue(tags.contains("device:google-pixel-8"));
        assertTrue(tags.contains("resolution:4000x3000"));
        assertTrue(tags.contains("geo:present"));
        assertTrue(tags.contains("orientation:horizontal-normal"));
    }
}
