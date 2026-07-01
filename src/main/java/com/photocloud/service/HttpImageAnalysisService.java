package com.photocloud.service;

import com.photocloud.config.AnalysisProperties;
import com.photocloud.entity.AnalysisStatus;
import com.photocloud.entity.MediaAsset;
import com.photocloud.entity.TagSource;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.core.io.ByteArrayResource;
import org.springframework.http.MediaType;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Service;
import org.springframework.util.LinkedMultiValueMap;
import org.springframework.util.MultiValueMap;
import org.springframework.web.client.RestClient;
import org.springframework.web.multipart.MultipartFile;

import java.util.List;

@Service
@ConditionalOnProperty(prefix = "app.analysis", name = "enabled", havingValue = "true")
public class HttpImageAnalysisService implements ImageAnalysisService {

    private final RestClient restClient;
    private final AnalysisProperties analysisProperties;

    public HttpImageAnalysisService(AnalysisProperties analysisProperties) {
        this.analysisProperties = analysisProperties;
        SimpleClientHttpRequestFactory requestFactory = new SimpleClientHttpRequestFactory();
        requestFactory.setConnectTimeout(analysisProperties.getConnectTimeoutMs());
        requestFactory.setReadTimeout(analysisProperties.getReadTimeoutMs());
        this.restClient = RestClient.builder()
                .baseUrl(analysisProperties.getBaseUrl())
                .requestFactory(requestFactory)
                .build();
    }

    @Override
    public AnalysisResult analyze(MediaAsset asset, byte[] originalContent, ExtractedImageMetadata metadata) {
        MultiValueMap<String, Object> body = new LinkedMultiValueMap<>();
        body.add("file", new NamedByteArrayResource(originalContent, asset.getOriginalFilename()));
        body.add("topTags", Integer.toString(analysisProperties.getTopTags()));

        RemoteAnalysisResponse response = restClient.post()
                .uri("/analyze")
                .contentType(MediaType.MULTIPART_FORM_DATA)
                .body(body)
                .retrieve()
                .body(RemoteAnalysisResponse.class);

        List<GeneratedTag> tags = response == null || response.tags() == null
                ? List.of()
                : response.tags().stream()
                .filter(tag -> tag.value() != null && !tag.value().isBlank())
                .map(tag -> new GeneratedTag(tag.value().trim(), TagSource.ANALYSIS, tag.confidence()))
                .toList();

        return new AnalysisResult(AnalysisStatus.COMPLETED, tags, response == null ? null : response.recognizedText());
    }

    private static class NamedByteArrayResource extends ByteArrayResource {

        private final String filename;

        private NamedByteArrayResource(byte[] byteArray, String filename) {
            super(byteArray);
            this.filename = filename;
        }

        @Override
        public String getFilename() {
            return filename;
        }
    }
}
