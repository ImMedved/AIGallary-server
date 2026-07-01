package com.photocloud.controller;

import com.photocloud.dto.TestPhotoResponse;
import com.photocloud.service.MediaDownload;
import com.photocloud.service.MediaService;
import org.springframework.core.io.InputStreamResource;
import org.springframework.core.io.Resource;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import java.util.Base64;
import java.util.List;

@RestController
@RequestMapping("/api/test/media")
public class TestMediaController {

    private final MediaService mediaService;

    public TestMediaController(MediaService mediaService) {
        this.mediaService = mediaService;
    }

    @PostMapping("/photo-preview")
    public TestPhotoResponse uploadPhotoPreview(
            @RequestParam("file") MultipartFile file,
            @RequestParam(name = "checksumSha256", required = false) String checksumSha256,
            @RequestParam(name = "tag", required = false) List<String> tags,
            @RequestParam(name = "person", required = false) List<String> people
    ) {
        var media = mediaService.upload(file, checksumSha256, tags, people);
        var ready = mediaService.processForTesting(media.id());
        MediaDownload thumbnail = mediaService.thumbnail(ready.id());
        byte[] thumbnailBytes;

        try (var stream = thumbnail.inputStream()) {
            thumbnailBytes = stream.readAllBytes();
        } catch (Exception exception) {
            throw new IllegalStateException("Unable to read generated thumbnail", exception);
        }

        return new TestPhotoResponse(
                ready,
                Base64.getEncoder().encodeToString(thumbnailBytes)
        );
    }

    @GetMapping("/{id}/original")
    public ResponseEntity<Resource> original(@PathVariable Long id) {
        MediaDownload media = mediaService.original(id);

        return ResponseEntity.ok()
                .contentType(MediaType.parseMediaType(media.contentType()))
                .contentLength(media.sizeBytes())
                .header(HttpHeaders.CONTENT_DISPOSITION, "inline; filename=\"" + media.filename() + "\"")
                .body(new InputStreamResource(media.inputStream()));
    }
}
