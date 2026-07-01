package com.photocloud.dto;

import com.photocloud.entity.TagSource;

import java.util.List;

public record TagSummaryResponse(
        String value,
        long assetCount,
        List<TagSource> sources
) {
}
