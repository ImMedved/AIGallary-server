package com.photocloud.service;

import com.photocloud.dto.MediaMetadataResponse;
import com.photocloud.dto.MediaResponse;
import com.photocloud.dto.TagSummaryResponse;
import com.photocloud.entity.AppUser;
import com.photocloud.entity.*;
import com.photocloud.repository.MediaAssetRepository;
import com.photocloud.repository.MediaDeliveryRequestRepository;
import com.photocloud.repository.MediaMetadataRepository;
import com.photocloud.repository.MediaTagRepository;
import com.photocloud.repository.MediaVariantRepository;
import com.photocloud.security.MediaAccessTokenService;
import com.photocloud.security.UserDetailsServiceImpl;
import com.photocloud.storage.ObjectStorage;
import com.photocloud.storage.StoredObject;
import org.springframework.http.HttpStatus;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.server.ResponseStatusException;

import java.io.IOException;
import java.net.URLConnection;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.stream.Collectors;

@Service
public class MediaService {

    private static final Set<String> IMAGE_EXTENSIONS = Set.of(".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp");
    private static final Set<String> VIDEO_EXTENSIONS = Set.of(".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm");
    private static final String PERSON_PREFIX = "person:";

    private final MediaAssetRepository mediaAssetRepository;
    private final MediaVariantRepository mediaVariantRepository;
    private final MediaMetadataRepository mediaMetadataRepository;
    private final MediaTagRepository mediaTagRepository;
    private final MediaDeliveryRequestRepository mediaDeliveryRequestRepository;
    private final UserDetailsServiceImpl userDetailsService;
    private final ObjectStorage objectStorage;
    private final MediaProcessingQueueService mediaProcessingQueueService;
    private final TagNormalizationService tagNormalizationService;
    private final ChecksumService checksumService;
    private final MediaEventPublisher mediaEventPublisher;
    private final com.photocloud.config.StorageProperties storageProperties;
    private final MediaAccessTokenService mediaAccessTokenService;

    public MediaService(
            MediaAssetRepository mediaAssetRepository,
            MediaVariantRepository mediaVariantRepository,
            MediaMetadataRepository mediaMetadataRepository,
            MediaTagRepository mediaTagRepository,
            MediaDeliveryRequestRepository mediaDeliveryRequestRepository,
            UserDetailsServiceImpl userDetailsService,
            ObjectStorage objectStorage,
            MediaProcessingQueueService mediaProcessingQueueService,
            TagNormalizationService tagNormalizationService,
            ChecksumService checksumService,
            MediaEventPublisher mediaEventPublisher,
            com.photocloud.config.StorageProperties storageProperties,
            MediaAccessTokenService mediaAccessTokenService
    ) {
        this.mediaAssetRepository = mediaAssetRepository;
        this.mediaVariantRepository = mediaVariantRepository;
        this.mediaMetadataRepository = mediaMetadataRepository;
        this.mediaTagRepository = mediaTagRepository;
        this.mediaDeliveryRequestRepository = mediaDeliveryRequestRepository;
        this.userDetailsService = userDetailsService;
        this.objectStorage = objectStorage;
        this.mediaProcessingQueueService = mediaProcessingQueueService;
        this.tagNormalizationService = tagNormalizationService;
        this.checksumService = checksumService;
        this.mediaEventPublisher = mediaEventPublisher;
        this.storageProperties = storageProperties;
        this.mediaAccessTokenService = mediaAccessTokenService;
    }

    @Transactional
    public MediaResponse upload(
            MultipartFile file,
            String expectedChecksumSha256,
            List<String> tags,
            List<String> people
    ) {
        AppUser user = currentUser();
        validateFile(file);

        try {
            String originalFilename = resolveOriginalFilename(file.getOriginalFilename());
            String mimeType = resolveMimeType(file.getContentType(), originalFilename);
            MediaType mediaType = resolveMediaType(mimeType, originalFilename);
            byte[] content = file.getBytes();
            String actualChecksum = checksumService.sha256(content);
            verifyChecksum(expectedChecksumSha256, actualChecksum);
            UUID uuid = UUID.randomUUID();

            MediaAsset asset = new MediaAsset();
            asset.setOwnerId(user.getId());
            asset.setUuid(uuid);
            asset.setMediaType(mediaType);
            asset.setProcessingStatus(ProcessingStatus.UPLOADED);
            asset.setAnalysisStatus(mediaType == MediaType.PHOTO ? AnalysisStatus.PENDING : AnalysisStatus.SKIPPED);
            asset.setOriginalFilename(originalFilename);
            asset.setMimeType(mimeType);
            asset.setSizeBytes(content.length);
            asset.setChecksumSha256(actualChecksum);

            MediaAsset savedAsset = mediaAssetRepository.save(asset);

            String bucket = storageProperties.getBucket();
            String originalObjectKey = buildOriginalObjectKey(user.getId(), uuid, originalFilename);

            objectStorage.putObject(bucket, originalObjectKey, content, mimeType);
            MediaVariant originalVariant = saveVariant(
                    savedAsset,
                    VariantType.ORIGINAL,
                    bucket,
                    originalObjectKey,
                    mimeType,
                    content.length
            );

            if (mediaType == MediaType.PHOTO) {
                mediaProcessingQueueService.enqueueImageProcessing(savedAsset);
            } else {
                savedAsset.setProcessingStatus(ProcessingStatus.READY);
                savedAsset = mediaAssetRepository.save(savedAsset);
            }
            addManualValues(savedAsset, tags, people);
            MediaResponseView view = buildView(savedAsset);

            if (mediaType == MediaType.PHOTO) {
                mediaEventPublisher.publishMediaUpdated(user, view);
            } else {
                mediaEventPublisher.publishMediaReady(user, view);
            }

            return toResponse(view);
        } catch (IOException exception) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Unable to read uploaded file", exception);
        }
    }

    public List<MediaResponse> list(
            List<String> tags,
            TagMatchMode mode,
            String text,
            List<String> people,
            java.time.Instant takenFrom,
            java.time.Instant takenTo,
            Boolean hasGeo,
            String orientation,
            Integer minWidth,
            Integer maxWidth,
            Integer minHeight,
            Integer maxHeight,
            Double aspectRatioFrom,
            Double aspectRatioTo,
            MediaType mediaType
    ) {
        AppUser user = currentUser();
        List<MediaAsset> assets = mediaAssetRepository.findByOwnerIdOrderByUploadedAtDesc(user.getId());
        MediaFilter filter = new MediaFilter(
                tags,
                mode,
                text,
                people,
                takenFrom,
                takenTo,
                hasGeo,
                orientation,
                minWidth,
                maxWidth,
                minHeight,
                maxHeight,
                aspectRatioFrom,
                aspectRatioTo,
                mediaType
        );

        return assets.stream()
                .filter(asset -> matches(asset, filter))
                .map(this::buildView)
                .map(this::toResponse)
                .toList();
    }

    public List<TagSummaryResponse> tags() {
        AppUser user = currentUser();
        List<MediaAsset> assets = mediaAssetRepository.findByOwnerIdOrderByUploadedAtDesc(user.getId());

        if (assets.isEmpty()) {
            return List.of();
        }

        Map<Long, MediaAsset> assetsById = assets.stream()
                .collect(Collectors.toMap(MediaAsset::getId, asset -> asset));

        List<MediaTag> tags = mediaTagRepository.findByAssetIdInOrderByCreatedAtAsc(assetsById.keySet());
        Map<String, TagAggregate> aggregates = new LinkedHashMap<>();

        for (MediaTag tag : tags) {
            TagAggregate aggregate = aggregates.computeIfAbsent(
                    tag.getNormalizedValue(),
                    key -> new TagAggregate(tag.getTagValue())
            );

            aggregate.add(tag);
        }

        return aggregates.values().stream()
                .map(aggregate -> new TagSummaryResponse(
                        aggregate.displayValue,
                        aggregate.assetIds.size(),
                        aggregate.sources.stream().sorted(Comparator.comparing(Enum::name)).toList()
                ))
                .sorted(Comparator.comparing(TagSummaryResponse::value))
                .toList();
    }

    @Transactional
    public MediaResponse addManualFields(Long id, List<String> values, List<String> people) {
        AppUser user = currentUser();
        MediaAsset asset = getOwnedMedia(id);
        addManualValues(asset, values, people);

        MediaResponseView view = buildView(asset);
        mediaEventPublisher.publishTagsUpdated(user, view);
        return toResponse(view);
    }

    @Transactional
    public MediaResponse removeManualTag(Long id, String tagValue) {
        AppUser user = currentUser();
        MediaAsset asset = getOwnedMedia(id);
        String normalizedValue = tagNormalizationService.normalize(tagValue);

        mediaTagRepository.deleteByAssetIdAndTagSourceAndNormalizedValue(
                asset.getId(),
                TagSource.USER,
                normalizedValue
        );

        MediaResponseView view = buildView(asset);
        mediaEventPublisher.publishTagsUpdated(user, view);
        return toResponse(view);
    }

    public MediaDownload original(Long id, String accessToken) {
        MediaAsset asset = getAccessibleMedia(id, VariantType.ORIGINAL, accessToken);
        MediaVariant variant = getVariant(asset.getId(), VariantType.ORIGINAL);
        StoredObject object = objectStorage.getObject(variant.getBucketName(), variant.getObjectKey());

        return new MediaDownload(
                asset.getOriginalFilename(),
                variant.getContentType(),
                object.sizeBytes(),
                object.inputStream()
        );
    }

    public MediaDownload original(Long id) {
        return original(id, null);
    }

    public MediaDownload thumbnail(Long id, String accessToken) {
        MediaAsset asset = getAccessibleMedia(id, VariantType.THUMBNAIL, accessToken);
        MediaVariant variant = getVariant(asset.getId(), VariantType.THUMBNAIL);
        StoredObject object = objectStorage.getObject(variant.getBucketName(), variant.getObjectKey());

        return new MediaDownload(
                asset.getOriginalFilename(),
                variant.getContentType(),
                object.sizeBytes(),
                object.inputStream()
        );
    }

    public MediaDownload thumbnail(Long id) {
        return thumbnail(id, null);
    }

    public MediaAsset getOwnedMedia(Long id) {
        AppUser user = currentUser();
        return getOwnedMedia(id, user);
    }

    public String checksum(Long id, String accessToken) {
        return getAccessibleMedia(id, VariantType.ORIGINAL, accessToken).getChecksumSha256();
    }

    private MediaAsset getOwnedMedia(Long id, AppUser user) {
        return mediaAssetRepository.findByIdAndOwnerId(id, user.getId())
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Media not found"));
    }

    public String checksum(Long id) {
        return getOwnedMedia(id).getChecksumSha256();
    }

    @Transactional
    public void delete(Long id) {
        AppUser user = currentUser();
        MediaAsset asset = getOwnedMedia(id);
        List<MediaVariant> variants = mediaVariantRepository.findByAssetId(asset.getId());

        for (MediaVariant variant : variants) {
            objectStorage.deleteObject(variant.getBucketName(), variant.getObjectKey());
        }

        mediaAssetRepository.delete(asset);
        mediaEventPublisher.publishMediaUpdated(user, new MediaResponseView(asset, null, List.of(), null, null));
    }

    @Transactional
    public com.photocloud.dto.DeliveryRequestResponse createDelivery(Long mediaId, VariantType variantType) {
        MediaAsset asset = getOwnedMedia(mediaId);
        AppUser user = currentUser();
        getVariant(asset.getId(), variantType);

        MediaDeliveryRequest request = new MediaDeliveryRequest();
        request.setAssetId(asset.getId());
        request.setOwnerId(user.getId());
        request.setVariantType(variantType);
        request.setStatus(DeliveryStatus.QUEUED);
        request.setChecksumSha256(asset.getChecksumSha256());
        request = mediaDeliveryRequestRepository.save(request);
        request.setStatus(DeliveryStatus.AVAILABLE);

        return toDeliveryResponse(request);
    }

    @Transactional
    public DeliveryDownload deliveryContent(Long deliveryId) {
        MediaDeliveryRequest request = getOwnedDelivery(deliveryId);
        request.setDownloadAttempts(request.getDownloadAttempts() + 1);
        request.setStatus(DeliveryStatus.AVAILABLE);

        MediaDownload media = request.getVariantType() == VariantType.THUMBNAIL
                ? thumbnail(request.getAssetId())
                : original(request.getAssetId());

        return new DeliveryDownload(media, getOwnedMedia(request.getAssetId()).getChecksumSha256());
    }

    @Transactional
    public com.photocloud.dto.DeliveryRequestResponse acknowledgeDelivery(Long deliveryId, String checksumSha256) {
        MediaDeliveryRequest request = getOwnedDelivery(deliveryId);

        if (request.getChecksumSha256() != null && !request.getChecksumSha256().equalsIgnoreCase(checksumSha256)) {
            request.setStatus(DeliveryStatus.FAILED);
            request.setLastError("Checksum mismatch");
            return toDeliveryResponse(request);
        }

        request.setAcknowledgedChecksumSha256(checksumSha256.toLowerCase(Locale.ROOT));
        request.setDeliveredAt(java.time.Instant.now());
        request.setStatus(DeliveryStatus.DELIVERED);
        request.setLastError(null);
        return toDeliveryResponse(request);
    }

    @Transactional
    public MediaResponse processForTesting(Long mediaId) {
        mediaProcessingQueueService.processAssetNow(mediaId);
        return toResponse(getOwnedMedia(mediaId));
    }

    private AppUser currentUser() {
        AppUser user = currentUserOrNull();
        if (user == null) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "Authentication required");
        }
        return user;
    }

    private AppUser currentUserOrNull() {
        Authentication authentication = SecurityContextHolder.getContext().getAuthentication();
        if (authentication == null || !authentication.isAuthenticated()) {
            return null;
        }

        String login = SecurityContextHolder.getContext()
                .getAuthentication()
                .getName();

        if (login == null || login.isBlank() || "anonymousUser".equals(login)) {
            return null;
        }

        return userDetailsService.loadAppUser(login);
    }

    private MediaResponse toResponse(MediaAsset asset) {
        return toResponse(buildView(asset));
    }

    private MediaResponse toResponse(MediaResponseView view) {
        List<String> tagValues = view.tags().stream()
                .map(MediaTag::getTagValue)
                .distinct()
                .toList();
        List<String> people = tagValues.stream()
                .filter(value -> value.startsWith(PERSON_PREFIX))
                .map(value -> value.substring(PERSON_PREFIX.length()))
                .toList();

        return new MediaResponse(
                view.asset().getId(),
                view.asset().getUuid(),
                view.asset().getMediaType(),
                view.asset().getProcessingStatus(),
                view.asset().getAnalysisStatus(),
                view.asset().getOriginalFilename(),
                view.asset().getMimeType(),
                view.asset().getSizeBytes(),
                view.asset().getChecksumSha256(),
                view.asset().getUploadedAt(),
                view.metadata() == null ? null : new MediaMetadataResponse(
                        view.metadata().getWidthPx(),
                        view.metadata().getHeightPx(),
                        formatAspectRatio(view.metadata().getWidthPx(), view.metadata().getHeightPx()),
                        view.metadata().getTakenAt(),
                        view.metadata().getDeviceName(),
                        view.metadata().getLatitude(),
                        view.metadata().getLongitude(),
                        view.metadata().getOrientation()
                ),
                view.asset().getRecognizedText(),
                tagValues,
                people,
                view.thumbnailVariant() == null ? null : buildSignedVariantUrl(view.asset(), VariantType.THUMBNAIL),
                view.originalVariant() == null ? null : buildSignedVariantUrl(view.asset(), VariantType.ORIGINAL)
        );
    }

    private void validateFile(MultipartFile file) {
        if (file.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Uploaded file is empty");
        }
    }

    private String resolveOriginalFilename(String originalFilename) {
        if (originalFilename == null || originalFilename.isBlank()) {
            return "unknown";
        }

        String sanitized = originalFilename.replace("\\", "/");
        int lastSlash = sanitized.lastIndexOf('/');

        return lastSlash >= 0 ? sanitized.substring(lastSlash + 1) : sanitized;
    }

    private String resolveMimeType(String contentType, String filename) {
        if (contentType != null && !contentType.isBlank()) {
            return contentType;
        }

        String guessed = URLConnection.guessContentTypeFromName(filename);
        return guessed == null ? "application/octet-stream" : guessed;
    }

    private MediaType resolveMediaType(String mimeType, String filename) {
        if (mimeType.startsWith("image/")) {
            return MediaType.PHOTO;
        }

        if (mimeType.startsWith("video/")) {
            return MediaType.VIDEO;
        }

        String extension = extractExtension(filename);

        if (IMAGE_EXTENSIONS.contains(extension)) {
            return MediaType.PHOTO;
        }

        if (VIDEO_EXTENSIONS.contains(extension)) {
            return MediaType.VIDEO;
        }

        throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Only image and video files are supported");
    }

    private String extractExtension(String filename) {
        int dot = filename.lastIndexOf('.');
        return dot == -1 ? "" : filename.substring(dot).toLowerCase(Locale.ROOT);
    }

    private String buildOriginalObjectKey(Long ownerId, UUID uuid, String filename) {
        return "users/%d/assets/%s/original%s".formatted(ownerId, uuid, extractExtension(filename));
    }

    private MediaVariant saveVariant(
            MediaAsset asset,
            VariantType variantType,
            String bucketName,
            String objectKey,
            String contentType,
            long sizeBytes
    ) {
        MediaVariant variant = new MediaVariant();
        variant.setAssetId(asset.getId());
        variant.setVariantType(variantType);
        variant.setBucketName(bucketName);
        variant.setObjectKey(objectKey);
        variant.setContentType(contentType);
        variant.setSizeBytes(sizeBytes);
        return mediaVariantRepository.save(variant);
    }

    private MediaVariant getVariant(Long assetId, VariantType variantType) {
        return mediaVariantRepository.findByAssetIdAndVariantType(assetId, variantType)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Requested media variant not found"));
    }

    private MediaResponseView buildView(MediaAsset asset) {
        MediaMetadata metadata = mediaMetadataRepository.findByAssetId(asset.getId()).orElse(null);
        List<MediaTag> tags = mediaTagRepository.findByAssetIdOrderByCreatedAtAsc(asset.getId());
        MediaVariant originalVariant = getVariant(asset.getId(), VariantType.ORIGINAL);
        MediaVariant thumbnailVariant = mediaVariantRepository.findByAssetIdAndVariantType(
                asset.getId(),
                VariantType.THUMBNAIL
        ).orElse(null);

        return new MediaResponseView(asset, metadata, tags, originalVariant, thumbnailVariant);
    }

    private MediaAsset getAccessibleMedia(Long id, VariantType variantType, String accessToken) {
        AppUser user = currentUserOrNull();

        if (user != null) {
            return getOwnedMedia(id, user);
        }

        MediaAsset asset = mediaAssetRepository.findById(id)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Media not found"));
        mediaAccessTokenService.validate(accessToken, asset, variantType);
        return asset;
    }

    private void verifyChecksum(String expectedChecksumSha256, String actualChecksum) {
        if (expectedChecksumSha256 == null || expectedChecksumSha256.isBlank()) {
            return;
        }

        if (!actualChecksum.equalsIgnoreCase(expectedChecksumSha256.trim())) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Checksum mismatch");
        }
    }

    private boolean matches(MediaAsset asset, MediaFilter filter) {
        if (filter.mediaType() != null && asset.getMediaType() != filter.mediaType()) {
            return false;
        }

        MediaMetadata metadata = mediaMetadataRepository.findByAssetId(asset.getId()).orElse(null);
        List<MediaTag> tags = mediaTagRepository.findByAssetIdOrderByCreatedAtAsc(asset.getId());
        Set<String> normalizedTags = tags.stream()
                .map(MediaTag::getNormalizedValue)
                .collect(Collectors.toSet());

        if (filter.tags() != null && !filter.tags().isEmpty()) {
            Set<String> requestedTags = filter.tags().stream()
                    .map(tagNormalizationService::normalize)
                    .collect(Collectors.toCollection(LinkedHashSet::new));
            if (!matches(normalizedTags, requestedTags, filter.tagMatchMode())) {
                return false;
            }
        }

        if (filter.people() != null && !filter.people().isEmpty()) {
            Set<String> requestedPeople = filter.people().stream()
                    .map(this::toPersonTag)
                    .map(tagNormalizationService::normalize)
                    .collect(Collectors.toSet());
            if (!normalizedTags.containsAll(requestedPeople)) {
                return false;
            }
        }

        if (filter.text() != null && !filter.text().isBlank()) {
            String normalized = filter.text().trim().toLowerCase(Locale.ROOT);
            if (asset.getRecognizedTextNormalized() == null || !asset.getRecognizedTextNormalized().contains(normalized)) {
                return false;
            }
        }

        if (metadata == null) {
            return filter.takenFrom() == null
                    && filter.takenTo() == null
                    && filter.hasGeo() == null
                    && filter.orientation() == null
                    && filter.minWidth() == null
                    && filter.maxWidth() == null
                    && filter.minHeight() == null
                    && filter.maxHeight() == null
                    && filter.aspectRatioFrom() == null
                    && filter.aspectRatioTo() == null;
        }

        if (filter.takenFrom() != null && (metadata.getTakenAt() == null || metadata.getTakenAt().isBefore(filter.takenFrom()))) {
            return false;
        }

        if (filter.takenTo() != null && (metadata.getTakenAt() == null || metadata.getTakenAt().isAfter(filter.takenTo()))) {
            return false;
        }

        if (filter.hasGeo() != null) {
            boolean hasGeo = metadata.getLatitude() != null && metadata.getLongitude() != null;
            if (hasGeo != filter.hasGeo()) {
                return false;
            }
        }

        if (filter.orientation() != null && !filter.orientation().isBlank()) {
            if (metadata.getOrientation() == null || !metadata.getOrientation().toLowerCase(Locale.ROOT)
                    .contains(filter.orientation().trim().toLowerCase(Locale.ROOT))) {
                return false;
            }
        }

        if (!within(metadata.getWidthPx(), filter.minWidth(), filter.maxWidth())) {
            return false;
        }

        if (!within(metadata.getHeightPx(), filter.minHeight(), filter.maxHeight())) {
            return false;
        }

        if (filter.aspectRatioFrom() != null || filter.aspectRatioTo() != null) {
            if (metadata.getWidthPx() == null || metadata.getHeightPx() == null || metadata.getHeightPx() == 0) {
                return false;
            }
            double ratio = (double) metadata.getWidthPx() / metadata.getHeightPx();
            if (filter.aspectRatioFrom() != null && ratio < filter.aspectRatioFrom()) {
                return false;
            }
            if (filter.aspectRatioTo() != null && ratio > filter.aspectRatioTo()) {
                return false;
            }
        }

        return true;
    }

    private boolean within(Integer value, Integer min, Integer max) {
        if (min == null && max == null) {
            return true;
        }

        if (value == null) {
            return false;
        }

        return (min == null || value >= min) && (max == null || value <= max);
    }

    private String formatAspectRatio(Integer width, Integer height) {
        if (width == null || height == null || width <= 0 || height <= 0) {
            return null;
        }

        int gcd = gcd(width, height);
        return (width / gcd) + ":" + (height / gcd);
    }

    private int gcd(int left, int right) {
        int a = left;
        int b = right;
        while (b != 0) {
            int temp = a % b;
            a = b;
            b = temp;
        }
        return a;
    }

    private void addManualValues(MediaAsset asset, List<String> values, List<String> people) {
        saveUserTags(asset, values);
        if (people != null) {
            saveUserTags(asset, people.stream().map(this::toPersonTag).toList());
        }
    }

    private void saveUserTags(MediaAsset asset, List<String> values) {
        if (values == null) {
            return;
        }

        for (String value : values) {
            if (value == null || value.isBlank()) {
                continue;
            }

            String displayValue = tagNormalizationService.sanitizeDisplayValue(value);
            String normalizedValue = tagNormalizationService.normalize(value);

            if (mediaTagRepository.existsByAssetIdAndTagSourceAndNormalizedValue(asset.getId(), TagSource.USER, normalizedValue)) {
                continue;
            }

            MediaTag tag = new MediaTag();
            tag.setAssetId(asset.getId());
            tag.setTagValue(displayValue);
            tag.setNormalizedValue(normalizedValue);
            tag.setTagSource(TagSource.USER);
            mediaTagRepository.save(tag);
        }
    }

    private String toPersonTag(String person) {
        return PERSON_PREFIX + person;
    }

    private String buildSignedVariantUrl(MediaAsset asset, VariantType variantType) {
        String token = mediaAccessTokenService.generateToken(asset, variantType);
        return "/api/media/" + asset.getId() + "/" + variantType.name().toLowerCase(Locale.ROOT)
                + "?accessToken=" + token;
    }

    private MediaDeliveryRequest getOwnedDelivery(Long deliveryId) {
        AppUser user = currentUser();
        return mediaDeliveryRequestRepository.findByIdAndOwnerId(deliveryId, user.getId())
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Delivery request not found"));
    }

    private com.photocloud.dto.DeliveryRequestResponse toDeliveryResponse(MediaDeliveryRequest request) {
        return new com.photocloud.dto.DeliveryRequestResponse(
                request.getId(),
                request.getAssetId(),
                request.getVariantType(),
                request.getStatus(),
                request.getChecksumSha256(),
                "/api/media/deliveries/" + request.getId() + "/content",
                request.getCreatedAt(),
                request.getDeliveredAt()
        );
    }

    private boolean matches(Set<String> assetTags, Set<String> requestedTags, TagMatchMode mode) {
        if (requestedTags.isEmpty()) {
            return true;
        }

        return switch (mode) {
            case ANY -> requestedTags.stream().anyMatch(assetTags::contains);
            case ALL -> assetTags.containsAll(requestedTags);
        };
    }

    private static class TagAggregate {

        private final String displayValue;
        private final Set<Long> assetIds = new LinkedHashSet<>();
        private final Set<TagSource> sources = new LinkedHashSet<>();

        private TagAggregate(String displayValue) {
            this.displayValue = displayValue;
        }

        private void add(MediaTag tag) {
            assetIds.add(tag.getAssetId());
            sources.add(tag.getTagSource());
        }
    }
}
