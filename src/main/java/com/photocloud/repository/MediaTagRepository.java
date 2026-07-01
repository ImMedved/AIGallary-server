package com.photocloud.repository;

import com.photocloud.entity.MediaTag;
import com.photocloud.entity.TagSource;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Collection;
import java.util.List;

public interface MediaTagRepository extends JpaRepository<MediaTag, Long> {

    List<MediaTag> findByAssetIdOrderByCreatedAtAsc(Long assetId);

    List<MediaTag> findByAssetIdInOrderByCreatedAtAsc(Collection<Long> assetIds);

    boolean existsByAssetIdAndTagSourceAndNormalizedValue(Long assetId, TagSource tagSource, String normalizedValue);

    @Modifying
    void deleteByAssetIdAndTagSourceAndNormalizedValue(Long assetId, TagSource tagSource, String normalizedValue);
}
