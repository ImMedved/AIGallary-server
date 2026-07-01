package com.photocloud.service;

import java.io.InputStream;

public record MediaDownload(
        String filename,
        String contentType,
        long sizeBytes,
        InputStream inputStream
) {
}
