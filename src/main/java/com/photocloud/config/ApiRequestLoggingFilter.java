package com.photocloud.config;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;

@Component
@Order(Ordered.HIGHEST_PRECEDENCE + 20)
public class ApiRequestLoggingFilter extends OncePerRequestFilter {

    private static final Logger log = LoggerFactory.getLogger(ApiRequestLoggingFilter.class);

    @Override
    protected boolean shouldNotFilter(HttpServletRequest request) {
        String uri = request.getRequestURI();
        return uri == null
                || uri.equals("/actuator/health")
                || uri.equals("/error")
                || !uri.startsWith("/api/");
    }

    @Override
    protected void doFilterInternal(
            HttpServletRequest request,
            HttpServletResponse response,
            FilterChain filterChain
    ) throws ServletException, IOException {
        long startedAt = System.currentTimeMillis();
        String method = request.getMethod();
        String path = sanitizePath(request);

        log.info("API request started method={} path={}", method, path);
        try {
            filterChain.doFilter(request, response);
            log.info(
                    "API request completed method={} path={} status={} durationMs={}",
                    method,
                    path,
                    response.getStatus(),
                    System.currentTimeMillis() - startedAt
            );
        } catch (Exception exception) {
            log.error(
                    "API request failed method={} path={} status={} durationMs={} error={}",
                    method,
                    path,
                    response.getStatus(),
                    System.currentTimeMillis() - startedAt,
                    exception.getMessage(),
                    exception
            );
            throw exception;
        }
    }

    private String sanitizePath(HttpServletRequest request) {
        String uri = request.getRequestURI();
        String query = request.getQueryString();
        if (query == null || query.isBlank()) {
            return uri;
        }

        return uri + "?" + query
                .replaceAll("(?i)(accessToken=)[^&]+", "$1<redacted>")
                .replaceAll("(?i)(token=)[^&]+", "$1<redacted>");
    }
}
