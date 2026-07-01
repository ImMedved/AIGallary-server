package com.photocloud.dto;

import com.photocloud.entity.DeliveryStatus;
import com.photocloud.entity.VariantType;

import java.time.Instant;

public record DeliveryRequestResponse(
        Long id,
        Long mediaId,
        VariantType variantType,
        DeliveryStatus status,
        String checksumSha256,
        String contentUrl,
        Instant createdAt,
        Instant deliveredAt
) {
}
