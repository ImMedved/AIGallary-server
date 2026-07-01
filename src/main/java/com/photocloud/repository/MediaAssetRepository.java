package com.photocloud.repository;

import com.photocloud.entity.MediaAsset;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.Optional;

public interface MediaAssetRepository extends JpaRepository<MediaAsset, Long> {

    List<MediaAsset> findByOwnerIdOrderByUploadedAtDesc(Long ownerId);

    Optional<MediaAsset> findByIdAndOwnerId(Long id, Long ownerId);
}
