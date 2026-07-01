package com.photocloud.service;

import com.photocloud.entity.AnalysisStatus;
import com.photocloud.entity.MediaAsset;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Service;

import java.util.List;

@Service
@ConditionalOnProperty(prefix = "app.analysis", name = "enabled", havingValue = "false", matchIfMissing = true)
public class StubImageAnalysisService implements ImageAnalysisService {

    @Override
    public AnalysisResult analyze(MediaAsset asset, byte[] originalContent, ExtractedImageMetadata metadata) {
        return new AnalysisResult(AnalysisStatus.SKIPPED, List.of(), null);
    }
}
