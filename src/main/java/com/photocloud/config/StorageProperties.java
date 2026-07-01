package com.photocloud.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "app.storage")
public class StorageProperties {

    private String provider = "filesystem";
    private String bucket = "smart-gallery-media";
    private final Filesystem filesystem = new Filesystem();
    private final Minio minio = new Minio();

    public String getProvider() {
        return provider;
    }

    public void setProvider(String provider) {
        this.provider = provider;
    }

    public String getBucket() {
        return bucket;
    }

    public void setBucket(String bucket) {
        this.bucket = bucket;
    }

    public Filesystem getFilesystem() {
        return filesystem;
    }

    public Minio getMinio() {
        return minio;
    }

    public static class Filesystem {

        private String root = "./storage";

        public String getRoot() {
            return root;
        }

        public void setRoot(String root) {
            this.root = root;
        }
    }

    public static class Minio {

        private String endpoint = "http://localhost:9000";
        private String accessKey = "minio";
        private String secretKey = "minio123";

        public String getEndpoint() {
            return endpoint;
        }

        public void setEndpoint(String endpoint) {
            this.endpoint = endpoint;
        }

        public String getAccessKey() {
            return accessKey;
        }

        public void setAccessKey(String accessKey) {
            this.accessKey = accessKey;
        }

        public String getSecretKey() {
            return secretKey;
        }

        public void setSecretKey(String secretKey) {
            this.secretKey = secretKey;
        }
    }
}
