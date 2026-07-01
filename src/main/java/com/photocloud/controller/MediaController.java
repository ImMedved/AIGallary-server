package com.photocloud.controller;

import com.photocloud.dto.DeliveryAckRequest;
import com.photocloud.dto.DeliveryRequestResponse;
import com.photocloud.dto.MediaResponse;
import com.photocloud.dto.TagSummaryResponse;
import com.photocloud.dto.UpsertTagsRequest;
import com.photocloud.entity.MediaType;
import com.photocloud.entity.TagMatchMode;
import com.photocloud.entity.VariantType;
import jakarta.validation.Valid;
import com.photocloud.service.MediaService;
import org.springframework.core.io.Resource;
import org.springframework.core.io.InputStreamResource;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import java.time.Instant;
import java.util.List;

@RestController
@RequestMapping("/api/media")
public class MediaController {

    private final MediaService mediaService;

    public MediaController(MediaService mediaService) {
        this.mediaService = mediaService;
    }

    @PostMapping
    public MediaResponse upload(
            @RequestParam("file") MultipartFile file,
            @RequestParam(name = "checksumSha256", required = false) String checksumSha256,
            @RequestParam(name = "tag", required = false) List<String> tags,
            @RequestParam(name = "person", required = false) List<String> people
    ) {
        return mediaService.upload(file, checksumSha256, tags, people);
    }

    @GetMapping
    public List<MediaResponse> list(
            @RequestParam(name = "tag", required = false) List<String> tags,
            @RequestParam(name = "mode", defaultValue = "ALL") TagMatchMode mode,
            @RequestParam(name = "text", required = false) String text,
            @RequestParam(name = "person", required = false) List<String> people,
            @RequestParam(name = "takenFrom", required = false) Instant takenFrom,
            @RequestParam(name = "takenTo", required = false) Instant takenTo,
            @RequestParam(name = "hasGeo", required = false) Boolean hasGeo,
            @RequestParam(name = "orientation", required = false) String orientation,
            @RequestParam(name = "minWidth", required = false) Integer minWidth,
            @RequestParam(name = "maxWidth", required = false) Integer maxWidth,
            @RequestParam(name = "minHeight", required = false) Integer minHeight,
            @RequestParam(name = "maxHeight", required = false) Integer maxHeight,
            @RequestParam(name = "aspectRatioFrom", required = false) Double aspectRatioFrom,
            @RequestParam(name = "aspectRatioTo", required = false) Double aspectRatioTo,
            @RequestParam(name = "mediaType", required = false) MediaType mediaType
    ) {
        return mediaService.list(tags, mode, text, people, takenFrom, takenTo, hasGeo, orientation, minWidth, maxWidth,
                minHeight, maxHeight, aspectRatioFrom, aspectRatioTo, mediaType);
    }

    @GetMapping("/tags")
    public List<TagSummaryResponse> tags() {
        return mediaService.tags();
    }

    @PostMapping("/{id}/tags")
    public MediaResponse addTags(
            @PathVariable Long id,
            @Valid @RequestBody UpsertTagsRequest request
    ) {
        return mediaService.addManualFields(id, request.tags(), request.people());
    }

    @DeleteMapping("/{id}/tags/{tagValue}")
    public MediaResponse deleteTag(
            @PathVariable Long id,
            @PathVariable String tagValue
    ) {
        return mediaService.removeManualTag(id, tagValue);
    }

    @GetMapping("/{id}/original")
    public ResponseEntity<Resource> original(@PathVariable Long id) {
        var media = mediaService.original(id);

        return ResponseEntity.ok()
                .contentLength(media.sizeBytes())
                .contentType(org.springframework.http.MediaType.parseMediaType(media.contentType()))
                .header("X-Checksum-Sha256", mediaService.checksum(id))
                .header(
                        HttpHeaders.CONTENT_DISPOSITION,
                        "inline; filename=\"" + media.filename() + "\""
                )
                .body(new InputStreamResource(media.inputStream()));
    }

    @GetMapping("/{id}/thumbnail")
    public ResponseEntity<Resource> thumbnail(@PathVariable Long id) {
        var media = mediaService.thumbnail(id);

        return ResponseEntity.ok()
                .contentLength(media.sizeBytes())
                .contentType(org.springframework.http.MediaType.IMAGE_JPEG)
                .body(new InputStreamResource(media.inputStream()));
    }

    @DeleteMapping("/{id}")
    public ResponseEntity<Void> delete(@PathVariable Long id) {
        mediaService.delete(id);
        return ResponseEntity.noContent().build();
    }

    @PostMapping("/{id}/deliveries")
    public DeliveryRequestResponse requestDelivery(
            @PathVariable Long id,
            @RequestParam(name = "variant", defaultValue = "ORIGINAL") VariantType variantType
    ) {
        return mediaService.createDelivery(id, variantType);
    }

    @GetMapping("/deliveries/{deliveryId}/content")
    public ResponseEntity<Resource> deliveryContent(@PathVariable Long deliveryId) {
        var delivery = mediaService.deliveryContent(deliveryId);

        return ResponseEntity.ok()
                .contentLength(delivery.media().sizeBytes())
                .contentType(org.springframework.http.MediaType.parseMediaType(delivery.media().contentType()))
                .header("X-Checksum-Sha256", delivery.checksumSha256())
                .header(HttpHeaders.CONTENT_DISPOSITION, "inline; filename=\"" + delivery.media().filename() + "\"")
                .body(new InputStreamResource(delivery.media().inputStream()));
    }

    @PostMapping("/deliveries/{deliveryId}/ack")
    public DeliveryRequestResponse acknowledgeDelivery(
            @PathVariable Long deliveryId,
            @Valid @RequestBody DeliveryAckRequest request
    ) {
        return mediaService.acknowledgeDelivery(deliveryId, request.checksumSha256());
    }
}
