package com.photocloud.service;

public record DeliveryDownload(
        MediaDownload media,
        String checksumSha256
) {
}
