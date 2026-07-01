package com.photocloud.repository;

import com.photocloud.entity.MediaProcessingJob;
import com.photocloud.entity.ProcessingJobStatus;
import jakarta.persistence.LockModeType;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Lock;

import java.time.Instant;
import java.util.Optional;

public interface MediaProcessingJobRepository extends JpaRepository<MediaProcessingJob, Long> {

    @Lock(LockModeType.PESSIMISTIC_WRITE)
    Optional<MediaProcessingJob> findFirstByStatusAndAvailableAtLessThanEqualOrderByCreatedAtAsc(
            ProcessingJobStatus status,
            Instant availableAt
    );

    Optional<MediaProcessingJob> findByAssetId(Long assetId);
}
