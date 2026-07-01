package com.photocloud.storage;

public interface ObjectStorage {

    void putObject(String bucket, String objectKey, byte[] content, String contentType);

    StoredObject getObject(String bucket, String objectKey);

    void deleteObject(String bucket, String objectKey);
}
