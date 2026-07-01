package com.photocloud.storage;

import com.photocloud.config.StorageProperties;
import io.minio.*;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Service;

import java.io.ByteArrayInputStream;

@Service
@ConditionalOnProperty(name = "app.storage.provider", havingValue = "minio")
public class MinioObjectStorage implements ObjectStorage {

    private final MinioClient minioClient;

    public MinioObjectStorage(StorageProperties storageProperties) {
        this.minioClient = MinioClient.builder()
                .endpoint(storageProperties.getMinio().getEndpoint())
                .credentials(
                        storageProperties.getMinio().getAccessKey(),
                        storageProperties.getMinio().getSecretKey()
                )
                .build();
    }

    @Override
    public void putObject(String bucket, String objectKey, byte[] content, String contentType) {
        try (ByteArrayInputStream inputStream = new ByteArrayInputStream(content)) {
            ensureBucket(bucket);
            minioClient.putObject(
                    PutObjectArgs.builder()
                            .bucket(bucket)
                            .object(objectKey)
                            .stream(inputStream, content.length, -1)
                            .contentType(contentType)
                            .build()
            );
        } catch (Exception exception) {
            throw new StorageException("Unable to write object to MinIO", exception);
        }
    }

    @Override
    public StoredObject getObject(String bucket, String objectKey) {
        try {
            StatObjectResponse stat = minioClient.statObject(
                    StatObjectArgs.builder()
                            .bucket(bucket)
                            .object(objectKey)
                            .build()
            );

            return new StoredObject(
                    minioClient.getObject(
                            GetObjectArgs.builder()
                                    .bucket(bucket)
                                    .object(objectKey)
                                    .build()
                    ),
                    stat.size()
            );
        } catch (Exception exception) {
            throw new StorageException("Unable to read object from MinIO", exception);
        }
    }

    @Override
    public void deleteObject(String bucket, String objectKey) {
        try {
            minioClient.removeObject(
                    RemoveObjectArgs.builder()
                            .bucket(bucket)
                            .object(objectKey)
                            .build()
            );
        } catch (Exception exception) {
            throw new StorageException("Unable to delete object from MinIO", exception);
        }
    }

    private void ensureBucket(String bucket) {
        try {
            boolean exists = minioClient.bucketExists(
                    BucketExistsArgs.builder()
                            .bucket(bucket)
                            .build()
            );

            if (!exists) {
                minioClient.makeBucket(
                        MakeBucketArgs.builder()
                                .bucket(bucket)
                                .build()
                );
            }
        } catch (Exception exception) {
            throw new StorageException("Unable to initialize MinIO bucket", exception);
        }
    }
}
