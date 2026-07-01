package com.photocloud.entity;

import jakarta.persistence.*;

import java.time.Instant;

@Entity
@Table(name = "media_tags")
public class MediaTag {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false)
    private Long assetId;

    @Column(nullable = false)
    private String tagValue;

    @Column(nullable = false)
    private String normalizedValue;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false)
    private TagSource tagSource;

    private Double confidence;

    @Column(nullable = false)
    private Instant createdAt = Instant.now();

    public Long getId() {
        return id;
    }

    public Long getAssetId() {
        return assetId;
    }

    public void setAssetId(Long assetId) {
        this.assetId = assetId;
    }

    public String getTagValue() {
        return tagValue;
    }

    public void setTagValue(String tagValue) {
        this.tagValue = tagValue;
    }

    public String getNormalizedValue() {
        return normalizedValue;
    }

    public void setNormalizedValue(String normalizedValue) {
        this.normalizedValue = normalizedValue;
    }

    public TagSource getTagSource() {
        return tagSource;
    }

    public void setTagSource(TagSource tagSource) {
        this.tagSource = tagSource;
    }

    public Double getConfidence() {
        return confidence;
    }

    public void setConfidence(Double confidence) {
        this.confidence = confidence;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }
}
