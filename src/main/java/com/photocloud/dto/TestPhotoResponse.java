package com.photocloud.dto;

public record TestPhotoResponse(
        MediaResponse media,
        String thumbnailBase64
) {
}
