package com.photocloud.storage;

import java.io.InputStream;

public record StoredObject(
        InputStream inputStream,
        long sizeBytes
) {
}
