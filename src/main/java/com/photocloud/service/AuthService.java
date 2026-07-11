package com.photocloud.service;

import com.photocloud.dto.AuthRequest;
import com.photocloud.dto.AuthResponse;
import com.photocloud.entity.AppUser;
import com.photocloud.entity.UserSession;
import com.photocloud.repository.AppUserRepository;
import com.photocloud.repository.UserSessionRepository;
import com.photocloud.security.JwtService;
import org.springframework.http.HttpStatus;
import org.springframework.security.authentication.AuthenticationManager;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

import java.time.Instant;
import java.util.UUID;

@Service
public class AuthService {

    private final AppUserRepository userRepository;
    private final UserSessionRepository userSessionRepository;
    private final BCryptPasswordEncoder passwordEncoder;
    private final AuthenticationManager authenticationManager;
    private final JwtService jwtService;

    public AuthService(
            AppUserRepository userRepository,
            UserSessionRepository userSessionRepository,
            BCryptPasswordEncoder passwordEncoder,
            AuthenticationManager authenticationManager,
            JwtService jwtService
    ) {
        this.userRepository = userRepository;
        this.userSessionRepository = userSessionRepository;
        this.passwordEncoder = passwordEncoder;
        this.authenticationManager = authenticationManager;
        this.jwtService = jwtService;
    }

    @Transactional
    public AuthResponse register(AuthRequest request) {
        if (userRepository.existsByLogin(request.login())) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "Login already exists");
        }

        AppUser user = new AppUser();

        user.setLogin(request.login());
        user.setPasswordHash(passwordEncoder.encode(request.password()));

        AppUser saved = userRepository.save(user);
        return new AuthResponse(issueToken(saved));
    }

    @Transactional
    public AuthResponse login(AuthRequest request) {
        authenticationManager.authenticate(
                new UsernamePasswordAuthenticationToken(
                        request.login(),
                        request.password()
                )
        );

        AppUser user = userRepository.findByLogin(request.login())
                .orElseThrow();

        return new AuthResponse(issueToken(user));
    }

    private String issueToken(AppUser user) {
        UserSession session = new UserSession();
        session.setUserId(user.getId());
        session.setSessionId(UUID.randomUUID());
        session.setActive(true);
        session.setInvalidatedAt(null);

        UserSession savedSession = userSessionRepository.save(session);
        return jwtService.generateToken(user.getId(), user.getLogin(), savedSession.getSessionId());
    }
}
