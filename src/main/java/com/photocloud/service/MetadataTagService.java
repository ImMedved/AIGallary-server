package com.photocloud.service;

import org.springframework.stereotype.Service;

import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;

@Service
public class MetadataTagService {

    public List<String> createTags(ExtractedImageMetadata metadata) {
        Set<String> tags = new LinkedHashSet<>();

        if (metadata.takenAt() != null) {
            tags.add("year:" + metadata.takenAt().atZone(ZoneOffset.UTC).getYear());
        }

        if (metadata.deviceName() != null && !metadata.deviceName().isBlank()) {
            tags.add("device:" + normalize(metadata.deviceName()));
        }

        if (metadata.widthPx() != null && metadata.heightPx() != null) {
            tags.add("resolution:" + metadata.widthPx() + "x" + metadata.heightPx());
        }

        if (metadata.latitude() != null && metadata.longitude() != null) {
            tags.add("geo:present");
        }

        if (metadata.orientation() != null && !metadata.orientation().isBlank()) {
            tags.add("orientation:" + normalize(metadata.orientation()));
        }

        return new ArrayList<>(tags);
    }

    private String normalize(String value) {
        return value.trim()
                .toLowerCase(Locale.ROOT)
                .replaceAll("[^a-z0-9]+", "-")
                .replaceAll("(^-+|-+$)", "");
    }
}
