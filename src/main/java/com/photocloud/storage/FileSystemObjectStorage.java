package com.photocloud.storage;

import com.photocloud.config.StorageProperties;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Service;

import java.io.IOException;
import java.io.InputStream;
import java.nio.file.*;

@Service
@ConditionalOnProperty(name = "app.storage.provider", havingValue = "filesystem", matchIfMissing = true)
public class FileSystemObjectStorage implements ObjectStorage {

    private final Path root;

    public FileSystemObjectStorage(StorageProperties storageProperties) {
        this.root = Path.of(storageProperties.getFilesystem().getRoot()).toAbsolutePath().normalize();
    }

    @Override
    public void putObject(String bucket, String objectKey, byte[] content, String contentType) {
        try {
            Path target = resolve(bucket, objectKey);
            Files.createDirectories(target.getParent());
            Files.write(target, content, StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING);
        } catch (IOException exception) {
            throw new StorageException("Unable to write object to filesystem storage", exception);
        }
    }

    @Override
    public StoredObject getObject(String bucket, String objectKey) {
        try {
            Path target = resolve(bucket, objectKey);
            return new StoredObject(Files.newInputStream(target), Files.size(target));
        } catch (IOException exception) {
            throw new StorageException("Unable to read object from filesystem storage", exception);
        }
    }

    @Override
    public void deleteObject(String bucket, String objectKey) {
        try {
            Files.deleteIfExists(resolve(bucket, objectKey));
        } catch (IOException exception) {
            throw new StorageException("Unable to delete object from filesystem storage", exception);
        }
    }

    private Path resolve(String bucket, String objectKey) {
        Path resolved = root.resolve(bucket).resolve(objectKey).normalize();

        if (!resolved.startsWith(root)) {
            throw new StorageException("Object key resolves outside of storage root");
        }

        return resolved;
    }
}
