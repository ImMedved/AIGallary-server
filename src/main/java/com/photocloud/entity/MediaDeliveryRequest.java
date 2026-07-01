package com.photocloud.entity;

import jakarta.persistence.*;

import java.time.Instant;

@Entity
@Table(name = "media_delivery_requests")
public class MediaDeliveryRequest {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false)
    private Long assetId;

    @Column(nullable = false)
    private Long ownerId;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false)
    private VariantType variantType;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false)
    private DeliveryStatus status;

    @Column(length = 64)
    private String checksumSha256;

    @Column(length = 64)
    private String acknowledgedChecksumSha256;

    @Column(columnDefinition = "text")
    private String lastError;

    @Column(nullable = false)
    private int downloadAttempts;

    @Column(nullable = false)
    private Instant createdAt = Instant.now();

    private Instant deliveredAt;

    public Long getId() {
        return id;
    }

    public Long getAssetId() {
        return assetId;
    }

    public void setAssetId(Long assetId) {
        this.assetId = assetId;
    }

    public Long getOwnerId() {
        return ownerId;
    }

    public void setOwnerId(Long ownerId) {
        this.ownerId = ownerId;
    }

    public VariantType getVariantType() {
        return variantType;
    }

    public void setVariantType(VariantType variantType) {
        this.variantType = variantType;
    }

    public DeliveryStatus getStatus() {
        return status;
    }

    public void setStatus(DeliveryStatus status) {
        this.status = status;
    }

    public String getChecksumSha256() {
        return checksumSha256;
    }

    public void setChecksumSha256(String checksumSha256) {
        this.checksumSha256 = checksumSha256;
    }

    public String getAcknowledgedChecksumSha256() {
        return acknowledgedChecksumSha256;
    }

    public void setAcknowledgedChecksumSha256(String acknowledgedChecksumSha256) {
        this.acknowledgedChecksumSha256 = acknowledgedChecksumSha256;
    }

    public String getLastError() {
        return lastError;
    }

    public void setLastError(String lastError) {
        this.lastError = lastError;
    }

    public int getDownloadAttempts() {
        return downloadAttempts;
    }

    public void setDownloadAttempts(int downloadAttempts) {
        this.downloadAttempts = downloadAttempts;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    public Instant getDeliveredAt() {
        return deliveredAt;
    }

    public void setDeliveredAt(Instant deliveredAt) {
        this.deliveredAt = deliveredAt;
    }
}
