package com.photocloud.repository;

import com.photocloud.entity.UserSession;
import org.springframework.data.jpa.repository.*;
import org.springframework.data.repository.query.Param;

import java.time.Instant;
import java.util.Optional;
import java.util.UUID;

public interface UserSessionRepository extends JpaRepository<UserSession, Long> {

    Optional<UserSession> findBySessionIdAndActiveTrue(UUID sessionId);

    @Modifying
    @Query("""
            update UserSession session
               set session.active = false,
                   session.invalidatedAt = :invalidatedAt
             where session.userId = :userId
               and session.active = true
            """)
    int deactivateActiveSessions(
            @Param("userId") Long userId,
            @Param("invalidatedAt") Instant invalidatedAt
    );
}
