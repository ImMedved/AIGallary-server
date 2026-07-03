package com.photocloud.security;

import com.photocloud.entity.MediaAsset;
import com.photocloud.entity.VariantType;
import io.jsonwebtoken.Claims;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

import javax.crypto.SecretKey;
import java.nio.charset.StandardCharsets;
import java.util.Date;

import static org.springframework.http.HttpStatus.UNAUTHORIZED;

@Service
public class MediaAccessTokenService {

    private final SecretKey key;
    private final long expirationMs;

    public MediaAccessTokenService(
            @Value("${app.jwt.secret}") String secret,
            @Value("${app.media.download-token-expiration-ms:900000}") long expirationMs
    ) {
        this.key = Keys.hmacShaKeyFor(secret.getBytes(StandardCharsets.UTF_8));
        this.expirationMs = expirationMs;
    }

    public String generateToken(MediaAsset asset, VariantType variantType) {
        Date now = new Date();
        Date expires = new Date(now.getTime() + expirationMs);

        return Jwts.builder()
                .subject("media-download")
                .claim("userId", asset.getOwnerId())
                .claim("assetId", asset.getId())
                .claim("variantType", variantType.name())
                .issuedAt(now)
                .expiration(expires)
                .signWith(key)
                .compact();
    }

    public void validate(String token, MediaAsset asset, VariantType variantType) {
        if (token == null || token.isBlank()) {
            throw new ResponseStatusException(UNAUTHORIZED, "Media access token is required");
        }

        try {
            Claims claims = Jwts.parser()
                    .verifyWith(key)
                    .build()
                    .parseSignedClaims(token)
                    .getPayload();

            String subject = claims.getSubject();
            Long userId = claims.get("userId", Long.class);
            Long assetId = claims.get("assetId", Long.class);
            String tokenVariant = claims.get("variantType", String.class);

            if (!"media-download".equals(subject)
                    || !asset.getOwnerId().equals(userId)
                    || !asset.getId().equals(assetId)
                    || !variantType.name().equals(tokenVariant)) {
                throw new ResponseStatusException(UNAUTHORIZED, "Invalid media access token");
            }
        } catch (ResponseStatusException exception) {
            throw exception;
        } catch (Exception exception) {
            throw new ResponseStatusException(UNAUTHORIZED, "Invalid media access token", exception);
        }
    }
}
