package com.photocloud;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.photocloud.entity.AnalysisStatus;
import com.photocloud.entity.TagSource;
import com.photocloud.service.AnalysisResult;
import com.photocloud.service.GeneratedTag;
import com.photocloud.service.ImageAnalysisService;
import com.photocloud.service.MediaProcessingQueueService;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.test.web.servlet.MockMvc;

import javax.imageio.ImageIO;
import java.awt.*;
import java.awt.image.BufferedImage;
import java.io.ByteArrayOutputStream;
import java.util.List;

import static org.hamcrest.Matchers.nullValue;
import static org.hamcrest.Matchers.notNullValue;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.multipart;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
class MediaFlowIntegrationTest {

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    @Autowired
    private MediaProcessingQueueService mediaProcessingQueueService;

    @MockBean
    private ImageAnalysisService imageAnalysisService;

    @Test
    void shouldUploadImageQueueProcessingThenReturnThumbnailMetadataAndAutoTags() throws Exception {
        when(imageAnalysisService.analyze(any(), any(), any())).thenReturn(new AnalysisResult(
                AnalysisStatus.COMPLETED,
                List.of(
                        new GeneratedTag("cat", TagSource.ANALYSIS, 0.91),
                        new GeneratedTag("sofa", TagSource.ANALYSIS, 0.76)
                ),
                "Hello from OCR"
        ));

        String token = register("media-user", "secret123");
        MockMultipartFile file = new MockMultipartFile(
                "file",
                "sample.png",
                MediaType.IMAGE_PNG_VALUE,
                createImageBytes(240, 120)
        );

        String body = mockMvc.perform(multipart("/api/media")
                        .file(file)
                        .header("Authorization", "Bearer " + token))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.mediaType").value("PHOTO"))
                .andExpect(jsonPath("$.processingStatus").value("UPLOADED"))
                .andExpect(jsonPath("$.analysisStatus").value("PENDING"))
                .andExpect(jsonPath("$.checksumSha256").value(notNullValue()))
                .andExpect(jsonPath("$.metadata").value(nullValue()))
                .andExpect(jsonPath("$.thumbnailUrl").value(nullValue()))
                .andReturn()
                .getResponse()
                .getContentAsString();

        JsonNode json = objectMapper.readTree(body);
        long mediaId = json.get("id").asLong();
        assertNotNull(json.get("originalUrl"));

        mediaProcessingQueueService.processNextPendingJob();

        mockMvc.perform(get("/api/media")
                        .header("Authorization", "Bearer " + token))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[0].id").value(mediaId))
                .andExpect(jsonPath("$[0].processingStatus").value("READY"))
                .andExpect(jsonPath("$[0].analysisStatus").value("COMPLETED"))
                .andExpect(jsonPath("$[0].metadata.widthPx").value(240))
                .andExpect(jsonPath("$[0].metadata.heightPx").value(120))
                .andExpect(jsonPath("$[0].metadata.aspectRatio").value("2:1"))
                .andExpect(jsonPath("$[0].recognizedText").value("Hello from OCR"))
                .andExpect(jsonPath("$[0].tags[?(@ == 'cat')]").exists())
                .andExpect(jsonPath("$[0].thumbnailUrl").value("/api/media/" + mediaId + "/thumbnail"));

        mockMvc.perform(get("/api/media/" + mediaId + "/original")
                        .header("Authorization", "Bearer " + token))
                .andExpect(status().isOk())
                .andExpect(content().contentType(MediaType.IMAGE_PNG));

        mockMvc.perform(get("/api/media/" + mediaId + "/thumbnail")
                        .header("Authorization", "Bearer " + token))
                .andExpect(status().isOk())
                .andExpect(content().contentType(MediaType.IMAGE_JPEG));
    }

    @Test
    void shouldUploadVideoAndKeepOnlyOriginalVariantOnServer() throws Exception {
        when(imageAnalysisService.analyze(any(), any(), any())).thenReturn(new AnalysisResult(
                AnalysisStatus.COMPLETED,
                List.of(),
                null
        ));

        String token = register("video-user", "secret123");
        MockMultipartFile file = new MockMultipartFile(
                "file",
                "clip.mp4",
                "video/mp4",
                new byte[]{0x00, 0x01, 0x02, 0x03}
        );

        String body = mockMvc.perform(multipart("/api/media")
                        .file(file)
                        .header("Authorization", "Bearer " + token))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.mediaType").value("VIDEO"))
                .andExpect(jsonPath("$.thumbnailUrl").value(nullValue()))
                .andExpect(jsonPath("$.metadata").value(nullValue()))
                .andReturn()
                .getResponse()
                .getContentAsString();

        long mediaId = objectMapper.readTree(body).get("id").asLong();

        mockMvc.perform(get("/api/media/" + mediaId + "/original")
                        .header("Authorization", "Bearer " + token))
                .andExpect(status().isOk())
                .andExpect(content().contentType("video/mp4"));
    }

    @Test
    void shouldAddManualTagsSearchByThemAndRemoveThem() throws Exception {
        when(imageAnalysisService.analyze(any(), any(), any())).thenReturn(new AnalysisResult(
                AnalysisStatus.COMPLETED,
                List.of(new GeneratedTag("gallery", TagSource.ANALYSIS, 0.88)),
                "Family vacation postcard"
        ));

        String token = register("tag-user", "secret123");
        long firstId = uploadPhoto(token, "tag-a.png", createImageBytes(180, 180));
        long secondId = uploadPhoto(token, "tag-b.png", createImageBytes(220, 220));
        mediaProcessingQueueService.processNextPendingJob();
        mediaProcessingQueueService.processNextPendingJob();

        mockMvc.perform(post("/api/media/" + firstId + "/tags")
                        .header("Authorization", "Bearer " + token)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "tags": ["Vacation", "Favorites"],
                                  "people": ["Alice"]
                                }
                                """))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.tags").isArray())
                .andExpect(jsonPath("$.tags[?(@ == 'Vacation')]").exists())
                .andExpect(jsonPath("$.people[0]").value("Alice"));

        mockMvc.perform(post("/api/media/" + secondId + "/tags")
                        .header("Authorization", "Bearer " + token)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "tags": ["Vacation", "Family"]
                                }
                                """))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.tags[?(@ == 'Family')]").exists());

        mockMvc.perform(get("/api/media")
                        .header("Authorization", "Bearer " + token)
                        .queryParam("tag", "vacation")
                        .queryParam("mode", "ALL"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.length()").value(2));

        mockMvc.perform(get("/api/media")
                        .header("Authorization", "Bearer " + token)
                        .queryParam("tag", "vacation")
                        .queryParam("tag", "family")
                        .queryParam("mode", "ALL"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.length()").value(1))
                .andExpect(jsonPath("$[0].id").value(secondId));

        mockMvc.perform(get("/api/media/tags")
                        .header("Authorization", "Bearer " + token))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[?(@.value == 'gallery')]").exists())
                .andExpect(jsonPath("$[?(@.value == 'Vacation')]").exists())
                .andExpect(jsonPath("$[?(@.value == 'Family')]").exists());

        mockMvc.perform(get("/api/media")
                        .header("Authorization", "Bearer " + token)
                        .queryParam("text", "postcard"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.length()").value(2));

        mockMvc.perform(get("/api/media")
                        .header("Authorization", "Bearer " + token)
                        .queryParam("person", "Alice")
                        .queryParam("minWidth", "150")
                        .queryParam("aspectRatioFrom", "0.9")
                        .queryParam("aspectRatioTo", "1.1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.length()").value(1))
                .andExpect(jsonPath("$[0].id").value(firstId));

        mockMvc.perform(delete("/api/media/" + secondId + "/tags/Family")
                        .header("Authorization", "Bearer " + token))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.tags[?(@ == 'Family')]").doesNotExist());

        mockMvc.perform(get("/api/media")
                        .header("Authorization", "Bearer " + token)
                        .queryParam("tag", "family")
                        .queryParam("mode", "ALL"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.length()").value(0));
    }

    @Test
    void shouldRejectUploadWhenChecksumDoesNotMatch() throws Exception {
        when(imageAnalysisService.analyze(any(), any(), any())).thenReturn(new AnalysisResult(
                AnalysisStatus.COMPLETED,
                List.of(),
                null
        ));

        String token = register("checksum-user", "secret123");
        MockMultipartFile file = new MockMultipartFile(
                "file",
                "bad.png",
                MediaType.IMAGE_PNG_VALUE,
                createImageBytes(20, 20)
        );

        mockMvc.perform(multipart("/api/media")
                        .file(file)
                        .param("checksumSha256", "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
                        .header("Authorization", "Bearer " + token))
                .andExpect(status().isBadRequest());
    }

    @Test
    void shouldCreateDeliveryAcknowledgeAndDeleteMedia() throws Exception {
        when(imageAnalysisService.analyze(any(), any(), any())).thenReturn(new AnalysisResult(
                AnalysisStatus.COMPLETED,
                List.of(new GeneratedTag("document", TagSource.ANALYSIS, 0.93)),
                "Delivery payload"
        ));

        String token = register("delivery-user", "secret123");
        long mediaId = uploadPhoto(token, "delivery.png", createImageBytes(128, 128));
        mediaProcessingQueueService.processNextPendingJob();

        String deliveryBody = mockMvc.perform(post("/api/media/" + mediaId + "/deliveries")
                        .header("Authorization", "Bearer " + token)
                        .param("variant", "ORIGINAL"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("AVAILABLE"))
                .andReturn()
                .getResponse()
                .getContentAsString();

        JsonNode deliveryJson = objectMapper.readTree(deliveryBody);
        long deliveryId = deliveryJson.get("id").asLong();
        String checksum = deliveryJson.get("checksumSha256").asText();
        String contentUrl = deliveryJson.get("contentUrl").asText();

        mockMvc.perform(get(contentUrl)
                        .header("Authorization", "Bearer " + token))
                .andExpect(status().isOk())
                .andExpect(content().contentType(MediaType.IMAGE_PNG))
                .andExpect(header().string("X-Checksum-Sha256", checksum));

        mockMvc.perform(post("/api/media/deliveries/" + deliveryId + "/ack")
                        .header("Authorization", "Bearer " + token)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "checksumSha256": "%s"
                                }
                                """.formatted(checksum)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("DELIVERED"));

        mockMvc.perform(delete("/api/media/" + mediaId)
                        .header("Authorization", "Bearer " + token))
                .andExpect(status().isNoContent());

        mockMvc.perform(get("/api/media")
                        .header("Authorization", "Bearer " + token))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.length()").value(0));
    }

    @Test
    void shouldSupportTestPreviewEndpoint() throws Exception {
        when(imageAnalysisService.analyze(any(), any(), any())).thenReturn(new AnalysisResult(
                AnalysisStatus.COMPLETED,
                List.of(new GeneratedTag("flower", TagSource.ANALYSIS, 0.77)),
                "Preview Text"
        ));

        String token = register("test-endpoint-user", "secret123");
        MockMultipartFile file = new MockMultipartFile(
                "file",
                "preview.png",
                MediaType.IMAGE_PNG_VALUE,
                createImageBytes(90, 60)
        );

        String body = mockMvc.perform(multipart("/api/test/media/photo-preview")
                        .file(file)
                        .param("tag", "manual-preview")
                        .param("person", "Bob")
                        .header("Authorization", "Bearer " + token))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.media.processingStatus").value("READY"))
                .andExpect(jsonPath("$.media.tags[?(@ == 'flower')]").exists())
                .andExpect(jsonPath("$.media.people[0]").value("Bob"))
                .andExpect(jsonPath("$.thumbnailBase64").value(notNullValue()))
                .andReturn()
                .getResponse()
                .getContentAsString();

        long mediaId = objectMapper.readTree(body).get("media").get("id").asLong();

        mockMvc.perform(get("/api/test/media/" + mediaId + "/original")
                        .header("Authorization", "Bearer " + token))
                .andExpect(status().isOk())
                .andExpect(content().contentType(MediaType.IMAGE_PNG));
    }

    private String register(String login, String password) throws Exception {
        String body = mockMvc.perform(post("/api/auth/register")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "login": "%s",
                                  "password": "%s"
                                }
                                """.formatted(login, password)))
                .andExpect(status().isOk())
                .andReturn()
                .getResponse()
                .getContentAsString();

        return objectMapper.readTree(body).get("token").asText();
    }

    private long uploadPhoto(String token, String filename, byte[] content) throws Exception {
        MockMultipartFile file = new MockMultipartFile(
                "file",
                filename,
                MediaType.IMAGE_PNG_VALUE,
                content
        );

        String body = mockMvc.perform(multipart("/api/media")
                        .file(file)
                        .header("Authorization", "Bearer " + token))
                .andExpect(status().isOk())
                .andReturn()
                .getResponse()
                .getContentAsString();

        return objectMapper.readTree(body).get("id").asLong();
    }

    private byte[] createImageBytes(int width, int height) throws Exception {
        BufferedImage image = new BufferedImage(width, height, BufferedImage.TYPE_INT_RGB);
        Graphics2D graphics = image.createGraphics();
        graphics.setColor(Color.ORANGE);
        graphics.fillRect(0, 0, width, height);
        graphics.dispose();

        ByteArrayOutputStream output = new ByteArrayOutputStream();
        ImageIO.write(image, "png", output);
        return output.toByteArray();
    }
}
