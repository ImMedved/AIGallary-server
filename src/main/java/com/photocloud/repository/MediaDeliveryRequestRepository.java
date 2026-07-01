package com.photocloud.repository;

import com.photocloud.entity.MediaDeliveryRequest;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;

public interface MediaDeliveryRequestRepository extends JpaRepository<MediaDeliveryRequest, Long> {

    Optional<MediaDeliveryRequest> findByIdAndOwnerId(Long id, Long ownerId);
}
