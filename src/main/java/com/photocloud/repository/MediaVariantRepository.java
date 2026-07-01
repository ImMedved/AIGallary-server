package com.photocloud.repository;

import com.photocloud.entity.MediaVariant;
import com.photocloud.entity.VariantType;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.Optional;

public interface MediaVariantRepository extends JpaRepository<MediaVariant, Long> {

    List<MediaVariant> findByAssetId(Long assetId);

    Optional<MediaVariant> findByAssetIdAndVariantType(Long assetId, VariantType variantType);
}
