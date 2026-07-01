package com.photocloud.service;

import com.photocloud.dto.MediaEventResponse;
import com.photocloud.entity.AppUser;
import org.springframework.messaging.simp.SimpMessagingTemplate;
import org.springframework.stereotype.Service;

import java.time.Instant;

@Service
public class MediaEventPublisher {

    private final SimpMessagingTemplate messagingTemplate;

    public MediaEventPublisher(SimpMessagingTemplate messagingTemplate) {
        this.messagingTemplate = messagingTemplate;
    }

    public void publishMediaReady(AppUser user, MediaResponseView media) {
        publish(user, new MediaEventResponse(
                "MEDIA_READY",
                media.asset().getId(),
                media.asset().getUuid(),
                media.asset().getProcessingStatus().name(),
                media.asset().getAnalysisStatus().name(),
                media.tags().stream().map(tag -> tag.getTagValue()).distinct().toList(),
                Instant.now()
        ));
    }

    public void publishMediaUpdated(AppUser user, MediaResponseView media) {
        publish(user, new MediaEventResponse(
                "MEDIA_UPDATED",
                media.asset().getId(),
                media.asset().getUuid(),
                media.asset().getProcessingStatus().name(),
                media.asset().getAnalysisStatus().name(),
                media.tags().stream().map(tag -> tag.getTagValue()).distinct().toList(),
                Instant.now()
        ));
    }

    public void publishTagsUpdated(AppUser user, MediaResponseView media) {
        publish(user, new MediaEventResponse(
                "TAGS_UPDATED",
                media.asset().getId(),
                media.asset().getUuid(),
                media.asset().getProcessingStatus().name(),
                media.asset().getAnalysisStatus().name(),
                media.tags().stream().map(tag -> tag.getTagValue()).distinct().toList(),
                Instant.now()
        ));
    }

    private void publish(AppUser user, MediaEventResponse event) {
        messagingTemplate.convertAndSendToUser(user.getLogin(), "/queue/library", event);
    }
}
