package com.photocloud.service;

import org.springframework.stereotype.Service;

import java.util.Locale;

@Service
public class TagNormalizationService {

    public String normalize(String value) {
        String trimmed = value == null ? "" : value.trim();

        if (trimmed.isEmpty()) {
            throw new IllegalArgumentException("Tag value must not be blank");
        }

        return trimmed.toLowerCase(Locale.ROOT);
    }

    public String sanitizeDisplayValue(String value) {
        String trimmed = value == null ? "" : value.trim();

        if (trimmed.isEmpty()) {
            throw new IllegalArgumentException("Tag value must not be blank");
        }

        return trimmed;
    }
}
