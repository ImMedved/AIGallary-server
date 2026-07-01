package com.photocloud.service;

import com.photocloud.entity.MediaAsset;

public interface ImageAnalysisService {

    AnalysisResult analyze(MediaAsset asset, byte[] originalContent, ExtractedImageMetadata metadata);
}
