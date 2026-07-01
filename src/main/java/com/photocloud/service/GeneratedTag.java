package com.photocloud.service;

import com.photocloud.entity.TagSource;

public record GeneratedTag(
        String value,
        TagSource source,
        Double confidence
) {
}
