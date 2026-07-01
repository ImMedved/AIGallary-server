package com.photocloud.security;

import com.photocloud.entity.UserSession;
import com.photocloud.repository.UserSessionRepository;
import org.springframework.messaging.*;
import org.springframework.messaging.simp.stomp.StompCommand;
import org.springframework.messaging.simp.stomp.StompHeaderAccessor;
import org.springframework.messaging.support.ChannelInterceptor;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.stereotype.Component;

import java.security.Principal;
import java.util.List;
import java.util.UUID;

@Component
public class WebSocketAuthChannelInterceptor implements ChannelInterceptor {

    private final JwtService jwtService;
    private final UserSessionRepository userSessionRepository;

    public WebSocketAuthChannelInterceptor(
            JwtService jwtService,
            UserSessionRepository userSessionRepository
    ) {
        this.jwtService = jwtService;
        this.userSessionRepository = userSessionRepository;
    }

    @Override
    public Message<?> preSend(Message<?> message, MessageChannel channel) {
        StompHeaderAccessor accessor = StompHeaderAccessor.wrap(message);

        if (StompCommand.CONNECT.equals(accessor.getCommand())) {
            String authorization = firstHeader(accessor, "Authorization");

            if (authorization == null || !authorization.startsWith("Bearer ")) {
                throw new MessagingException("Missing bearer token");
            }

            String token = authorization.substring(7);
            String login = jwtService.extractLogin(token);
            Long userId = jwtService.extractUserId(token);
            UUID sessionId = jwtService.extractSessionId(token);

            UserSession session = userSessionRepository.findBySessionIdAndActiveTrue(sessionId)
                    .orElseThrow(() -> new MessagingException("Inactive session"));

            if (!session.getUserId().equals(userId)) {
                throw new MessagingException("Session user mismatch");
            }

            Principal principal = new UsernamePasswordAuthenticationToken(login, token, List.of());
            accessor.setUser(principal);
        }

        if ((StompCommand.SUBSCRIBE.equals(accessor.getCommand()) || StompCommand.SEND.equals(accessor.getCommand()))
                && accessor.getUser() == null) {
            throw new MessagingException("Unauthenticated websocket access");
        }

        return message;
    }

    private String firstHeader(StompHeaderAccessor accessor, String name) {
        List<String> values = accessor.getNativeHeader(name);
        return values == null || values.isEmpty() ? null : values.get(0);
    }
}
