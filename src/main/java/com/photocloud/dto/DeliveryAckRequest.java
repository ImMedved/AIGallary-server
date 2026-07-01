package com.photocloud.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;

public record DeliveryAckRequest(
        @NotBlank
        @Pattern(regexp = "^[A-Fa-f0-9]{64}$")
        String checksumSha256
) {
}
