package com.photocloud.service;

import com.photocloud.entity.MediaType;
import com.photocloud.entity.TagMatchMode;

import java.time.Instant;
import java.util.List;

public record MediaFilter(
        List<String> tags,
        TagMatchMode tagMatchMode,
        String text,
        List<String> people,
        Instant takenFrom,
        Instant takenTo,
        Boolean hasGeo,
        String orientation,
        Integer minWidth,
        Integer maxWidth,
        Integer minHeight,
        Integer maxHeight,
        Double aspectRatioFrom,
        Double aspectRatioTo,
        MediaType mediaType
) {
}
