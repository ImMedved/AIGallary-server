package com.photocloud.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "app.analysis")
public class AnalysisProperties {

    private boolean enabled;
    private String baseUrl = "http://localhost:8090";
    private int topTags = 5;
    private int connectTimeoutMs = 5000;
    private int readTimeoutMs = 60000;
    private Processing processing = new Processing();

    public boolean isEnabled() {
        return enabled;
    }

    public void setEnabled(boolean enabled) {
        this.enabled = enabled;
    }

    public String getBaseUrl() {
        return baseUrl;
    }

    public void setBaseUrl(String baseUrl) {
        this.baseUrl = baseUrl;
    }

    public int getTopTags() {
        return topTags;
    }

    public void setTopTags(int topTags) {
        this.topTags = topTags;
    }

    public int getConnectTimeoutMs() {
        return connectTimeoutMs;
    }

    public void setConnectTimeoutMs(int connectTimeoutMs) {
        this.connectTimeoutMs = connectTimeoutMs;
    }

    public int getReadTimeoutMs() {
        return readTimeoutMs;
    }

    public void setReadTimeoutMs(int readTimeoutMs) {
        this.readTimeoutMs = readTimeoutMs;
    }

    public Processing getProcessing() {
        return processing;
    }

    public void setProcessing(Processing processing) {
        this.processing = processing;
    }

    public static class Processing {

        private long pollDelayMs = 2000;
        private int maxAttempts = 5;
        private boolean schedulingEnabled = true;

        public long getPollDelayMs() {
            return pollDelayMs;
        }

        public void setPollDelayMs(long pollDelayMs) {
            this.pollDelayMs = pollDelayMs;
        }

        public int getMaxAttempts() {
            return maxAttempts;
        }

        public void setMaxAttempts(int maxAttempts) {
            this.maxAttempts = maxAttempts;
        }

        public boolean isSchedulingEnabled() {
            return schedulingEnabled;
        }

        public void setSchedulingEnabled(boolean schedulingEnabled) {
            this.schedulingEnabled = schedulingEnabled;
        }
    }
}
