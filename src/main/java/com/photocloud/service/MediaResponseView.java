package com.photocloud.service;

import com.photocloud.entity.MediaAsset;
import com.photocloud.entity.MediaMetadata;
import com.photocloud.entity.MediaTag;
import com.photocloud.entity.MediaVariant;

import java.util.List;

public record MediaResponseView(
        MediaAsset asset,
        MediaMetadata metadata,
        List<MediaTag> tags,
        MediaVariant originalVariant,
        MediaVariant thumbnailVariant
) {
}
