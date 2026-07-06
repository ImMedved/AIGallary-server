package com.photocloud.service;

import com.photocloud.config.AnalysisProperties;
import com.photocloud.entity.*;
import com.photocloud.repository.AppUserRepository;
import com.photocloud.repository.MediaAssetRepository;
import com.photocloud.repository.MediaMetadataRepository;
import com.photocloud.repository.MediaProcessingJobRepository;
import com.photocloud.repository.MediaTagRepository;
import com.photocloud.repository.MediaVariantRepository;
import com.photocloud.storage.ObjectStorage;
import com.photocloud.storage.StoredObject;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.io.IOException;
import java.io.InputStream;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;

@Service
public class MediaProcessingQueueService {

    private static final Logger log = LoggerFactory.getLogger(MediaProcessingQueueService.class);

    private final MediaProcessingJobRepository mediaProcessingJobRepository;
    private final MediaAssetRepository mediaAssetRepository;
    private final MediaVariantRepository mediaVariantRepository;
    private final MediaMetadataRepository mediaMetadataRepository;
    private final MediaTagRepository mediaTagRepository;
    private final AppUserRepository appUserRepository;
    private final ObjectStorage objectStorage;
    private final ThumbnailService thumbnailService;
    private final ImageMetadataExtractor imageMetadataExtractor;
    private final MetadataTagService metadataTagService;
    private final ImageAnalysisService imageAnalysisService;
    private final OcrTextNormalizationService ocrTextNormalizationService;
    private final TagNormalizationService tagNormalizationService;
    private final MediaEventPublisher mediaEventPublisher;
    private final AnalysisProperties analysisProperties;

    public MediaProcessingQueueService(
            MediaProcessingJobRepository mediaProcessingJobRepository,
            MediaAssetRepository mediaAssetRepository,
            MediaVariantRepository mediaVariantRepository,
            MediaMetadataRepository mediaMetadataRepository,
            MediaTagRepository mediaTagRepository,
            AppUserRepository appUserRepository,
            ObjectStorage objectStorage,
            ThumbnailService thumbnailService,
            ImageMetadataExtractor imageMetadataExtractor,
            MetadataTagService metadataTagService,
            ImageAnalysisService imageAnalysisService,
            OcrTextNormalizationService ocrTextNormalizationService,
            TagNormalizationService tagNormalizationService,
            MediaEventPublisher mediaEventPublisher,
            AnalysisProperties analysisProperties
    ) {
        this.mediaProcessingJobRepository = mediaProcessingJobRepository;
        this.mediaAssetRepository = mediaAssetRepository;
        this.mediaVariantRepository = mediaVariantRepository;
        this.mediaMetadataRepository = mediaMetadataRepository;
        this.mediaTagRepository = mediaTagRepository;
        this.appUserRepository = appUserRepository;
        this.objectStorage = objectStorage;
        this.thumbnailService = thumbnailService;
        this.imageMetadataExtractor = imageMetadataExtractor;
        this.metadataTagService = metadataTagService;
        this.imageAnalysisService = imageAnalysisService;
        this.ocrTextNormalizationService = ocrTextNormalizationService;
        this.tagNormalizationService = tagNormalizationService;
        this.mediaEventPublisher = mediaEventPublisher;
        this.analysisProperties = analysisProperties;
    }

    @Transactional
    public void enqueueImageProcessing(MediaAsset asset) {
        MediaProcessingJob job = mediaProcessingJobRepository.findByAssetId(asset.getId())
                .orElseGet(MediaProcessingJob::new);
        job.setAssetId(asset.getId());
        job.setStatus(ProcessingJobStatus.PENDING);
        job.setAvailableAt(Instant.now());
        job.setLastError(null);
        mediaProcessingJobRepository.save(job);
        log.info(
                "Media processing job queued jobAssetId={} assetUuid={} ownerId={} status={}",
                asset.getId(),
                asset.getUuid(),
                asset.getOwnerId(),
                job.getStatus()
        );
    }

    @Scheduled(fixedDelayString = "${app.analysis.processing.poll-delay-ms:2000}")
    @Transactional
    public void pollQueue() {
        if (!analysisProperties.getProcessing().isSchedulingEnabled()) {
            return;
        }
        processNextPendingJob();
    }

    @Transactional
    public void processNextPendingJob() {
        MediaProcessingJob job = mediaProcessingJobRepository
                .findFirstByStatusAndAvailableAtLessThanEqualOrderByCreatedAtAsc(ProcessingJobStatus.PENDING, Instant.now())
                .orElse(null);

        if (job == null) {
            return;
        }

        MediaAsset asset = mediaAssetRepository.findById(job.getAssetId()).orElse(null);
        if (asset == null) {
            job.setStatus(ProcessingJobStatus.FAILED);
            job.setLastError("Asset no longer exists");
            job.setCompletedAt(Instant.now());
            log.warn("Media processing job failed jobAssetId={} reason=asset-no-longer-exists", job.getAssetId());
            return;
        }

        job.setStatus(ProcessingJobStatus.RUNNING);
        job.setStartedAt(Instant.now());
        asset.setProcessingStatus(ProcessingStatus.PROCESSING);
        Instant startedAt = Instant.now();
        log.info(
                "Media processing job started jobAssetId={} assetUuid={} attempt={} scheduled=true",
                asset.getId(),
                asset.getUuid(),
                job.getAttempts() + 1
        );

        try {
            processAsset(asset);
            job.setStatus(ProcessingJobStatus.COMPLETED);
            job.setCompletedAt(Instant.now());
            job.setLastError(null);
            log.info(
                    "Media processing job completed jobAssetId={} assetUuid={} analysisStatus={} processingStatus={} durationMs={}",
                    asset.getId(),
                    asset.getUuid(),
                    asset.getAnalysisStatus(),
                    asset.getProcessingStatus(),
                    job.getCompletedAt().toEpochMilli() - startedAt.toEpochMilli()
            );
        } catch (Exception exception) {
            job.setAttempts(job.getAttempts() + 1);
            if (job.getAttempts() >= analysisProperties.getProcessing().getMaxAttempts()) {
                job.setStatus(ProcessingJobStatus.FAILED);
                job.setCompletedAt(Instant.now());
                asset.setProcessingStatus(ProcessingStatus.FAILED);
                asset.setAnalysisStatus(AnalysisStatus.FAILED);
                log.error(
                        "Media processing job failed jobAssetId={} assetUuid={} attempt={} maxAttempts={} durationMs={} error={}",
                        asset.getId(),
                        asset.getUuid(),
                        job.getAttempts(),
                        analysisProperties.getProcessing().getMaxAttempts(),
                        job.getCompletedAt().toEpochMilli() - startedAt.toEpochMilli(),
                        exception.getMessage(),
                        exception
                );
            } else {
                job.setStatus(ProcessingJobStatus.PENDING);
                job.setAvailableAt(Instant.now().plusSeconds(job.getAttempts() * 10L));
                log.warn(
                        "Media processing job retry scheduled jobAssetId={} assetUuid={} attempt={} nextAvailableAt={} error={}",
                        asset.getId(),
                        asset.getUuid(),
                        job.getAttempts(),
                        job.getAvailableAt(),
                        exception.getMessage()
                );
            }
            job.setLastError(exception.getMessage());
        }
    }

    @Transactional
    public void processAssetNow(Long assetId) {
        MediaProcessingJob job = mediaProcessingJobRepository.findByAssetId(assetId)
                .orElseGet(MediaProcessingJob::new);
        job.setAssetId(assetId);
        job.setStatus(ProcessingJobStatus.RUNNING);
        job.setStartedAt(Instant.now());
        mediaProcessingJobRepository.save(job);

        MediaAsset asset = mediaAssetRepository.findById(assetId)
                .orElseThrow(() -> new IllegalStateException("Asset not found"));
        asset.setProcessingStatus(ProcessingStatus.PROCESSING);
        Instant startedAt = Instant.now();
        log.info(
                "Media processing job started jobAssetId={} assetUuid={} attempt={} scheduled=false",
                asset.getId(),
                asset.getUuid(),
                job.getAttempts() + 1
        );

        try {
            processAsset(asset);
            job.setStatus(ProcessingJobStatus.COMPLETED);
            job.setCompletedAt(Instant.now());
            job.setLastError(null);
            log.info(
                    "Media processing job completed jobAssetId={} assetUuid={} analysisStatus={} processingStatus={} durationMs={}",
                    asset.getId(),
                    asset.getUuid(),
                    asset.getAnalysisStatus(),
                    asset.getProcessingStatus(),
                    job.getCompletedAt().toEpochMilli() - startedAt.toEpochMilli()
            );
        } catch (IOException exception) {
            job.setStatus(ProcessingJobStatus.FAILED);
            job.setCompletedAt(Instant.now());
            job.setLastError(exception.getMessage());
            asset.setProcessingStatus(ProcessingStatus.FAILED);
            asset.setAnalysisStatus(AnalysisStatus.FAILED);
            mediaAssetRepository.save(asset);
            log.error(
                    "Media processing job failed jobAssetId={} assetUuid={} scheduled=false durationMs={} error={}",
                    asset.getId(),
                    asset.getUuid(),
                    job.getCompletedAt().toEpochMilli() - startedAt.toEpochMilli(),
                    exception.getMessage(),
                    exception
            );
            throw new IllegalStateException("Unable to process asset", exception);
        }
    }

    private void processAsset(MediaAsset asset) throws IOException {
        MediaVariant original = mediaVariantRepository.findByAssetIdAndVariantType(asset.getId(), VariantType.ORIGINAL)
                .orElseThrow(() -> new IllegalStateException("Original variant not found"));

        StoredObject storedObject = objectStorage.getObject(original.getBucketName(), original.getObjectKey());
        byte[] content;
        try (InputStream stream = storedObject.inputStream()) {
            content = stream.readAllBytes();
        }

        ExtractedImageMetadata metadata = imageMetadataExtractor.extract(content);
        saveOrUpdateMetadata(asset, metadata);
        saveMetadataTags(asset, metadata);
        saveThumbnail(asset, content, original.getBucketName());

        AnalysisResult analysisResult = imageAnalysisService.analyze(asset, content, metadata);
        saveAnalysisTags(asset, analysisResult.tags());
        asset.setRecognizedText(analysisResult.recognizedText());
        asset.setRecognizedTextNormalized(ocrTextNormalizationService.normalize(analysisResult.recognizedText()));
        asset.setAnalysisStatus(analysisResult.status());
        asset.setProcessingStatus(ProcessingStatus.READY);

        MediaAsset updatedAsset = mediaAssetRepository.save(asset);
        AppUser owner = appUserRepository.findById(updatedAsset.getOwnerId())
                .orElseThrow(() -> new IllegalStateException("Owner not found"));
        mediaEventPublisher.publishMediaUpdated(owner, new MediaResponseView(
                updatedAsset,
                mediaMetadataRepository.findByAssetId(updatedAsset.getId()).orElse(null),
                mediaTagRepository.findByAssetIdOrderByCreatedAtAsc(updatedAsset.getId()),
                original,
                mediaVariantRepository.findByAssetIdAndVariantType(updatedAsset.getId(), VariantType.THUMBNAIL).orElse(null)
        ));
    }

    private void saveOrUpdateMetadata(MediaAsset asset, ExtractedImageMetadata metadata) {
        if (metadata.isEmpty()) {
            return;
        }

        MediaMetadata entity = mediaMetadataRepository.findByAssetId(asset.getId()).orElseGet(MediaMetadata::new);
        entity.setAssetId(asset.getId());
        entity.setWidthPx(metadata.widthPx());
        entity.setHeightPx(metadata.heightPx());
        entity.setTakenAt(metadata.takenAt());
        entity.setCameraMake(metadata.cameraMake());
        entity.setCameraModel(metadata.cameraModel());
        entity.setDeviceName(metadata.deviceName());
        entity.setLatitude(metadata.latitude());
        entity.setLongitude(metadata.longitude());
        entity.setOrientation(metadata.orientation());
        mediaMetadataRepository.save(entity);
    }

    private void saveMetadataTags(MediaAsset asset, ExtractedImageMetadata metadata) {
        for (String value : metadataTagService.createTags(metadata)) {
            String normalizedValue = tagNormalizationService.normalize(value);
            if (mediaTagRepository.existsByAssetIdAndTagSourceAndNormalizedValue(asset.getId(), TagSource.METADATA, normalizedValue)) {
                continue;
            }

            MediaTag tag = new MediaTag();
            tag.setAssetId(asset.getId());
            tag.setTagValue(value);
            tag.setNormalizedValue(normalizedValue);
            tag.setTagSource(TagSource.METADATA);
            mediaTagRepository.save(tag);
        }
    }

    private void saveAnalysisTags(MediaAsset asset, List<GeneratedTag> generatedTags) {
        for (GeneratedTag generatedTag : generatedTags) {
            String normalizedValue = tagNormalizationService.normalize(generatedTag.value());
            if (mediaTagRepository.existsByAssetIdAndTagSourceAndNormalizedValue(asset.getId(), TagSource.ANALYSIS, normalizedValue)) {
                continue;
            }

            MediaTag tag = new MediaTag();
            tag.setAssetId(asset.getId());
            tag.setTagValue(generatedTag.value());
            tag.setNormalizedValue(normalizedValue);
            tag.setTagSource(TagSource.ANALYSIS);
            tag.setConfidence(generatedTag.confidence());
            mediaTagRepository.save(tag);
        }
    }

    private void saveThumbnail(MediaAsset asset, byte[] content, String bucketName) {
        byte[] thumbnailBytes = thumbnailService.generate(content);
        String objectKey = "users/%d/assets/%s/thumbnail.jpg".formatted(asset.getOwnerId(), asset.getUuid());

        objectStorage.putObject(bucketName, objectKey, thumbnailBytes, org.springframework.http.MediaType.IMAGE_JPEG_VALUE);

        MediaVariant variant = mediaVariantRepository.findByAssetIdAndVariantType(asset.getId(), VariantType.THUMBNAIL)
                .orElseGet(MediaVariant::new);
        variant.setAssetId(asset.getId());
        variant.setVariantType(VariantType.THUMBNAIL);
        variant.setBucketName(bucketName);
        variant.setObjectKey(objectKey);
        variant.setContentType(org.springframework.http.MediaType.IMAGE_JPEG_VALUE);
        variant.setSizeBytes(thumbnailBytes.length);
        mediaVariantRepository.save(variant);
    }
}
