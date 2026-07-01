package com.photocloud.repository;

import com.photocloud.entity.MediaMetadata;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;

public interface MediaMetadataRepository extends JpaRepository<MediaMetadata, Long> {

    Optional<MediaMetadata> findByAssetId(Long assetId);
}
