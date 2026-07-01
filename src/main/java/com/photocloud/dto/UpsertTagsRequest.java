package com.photocloud.dto;

import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;

import java.util.List;

public record UpsertTagsRequest(
        List<@NotBlank @Size(max = 128) String> tags,
        List<@NotBlank @Size(max = 128) String> people
) {
}
