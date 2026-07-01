package com.photocloud.service;

import org.springframework.stereotype.Service;

import java.util.Locale;

@Service
public class OcrTextNormalizationService {

    public String normalize(String value) {
        if (value == null) {
            return null;
        }

        String normalized = value
                .replaceAll("\\s+", " ")
                .trim();

        if (normalized.isEmpty()) {
            return null;
        }

        return normalized.toLowerCase(Locale.ROOT);
    }
}
