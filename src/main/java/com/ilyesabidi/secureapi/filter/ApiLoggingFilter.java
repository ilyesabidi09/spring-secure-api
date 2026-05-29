package com.ilyesabidi.secureapi.filter;

import com.ilyesabidi.secureapi.entity.ApiLog;
import com.ilyesabidi.secureapi.event.ApiCallEvent;
import com.ilyesabidi.secureapi.messaging.ApiEventProducer;
import com.ilyesabidi.secureapi.repository.ApiLogRepository;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.time.LocalDateTime;

@Component
@RequiredArgsConstructor
public class ApiLoggingFilter extends OncePerRequestFilter {

    private final ApiLogRepository apiLogRepository;
    private final ApiEventProducer apiEventProducer;

    @Override
    protected void doFilterInternal(HttpServletRequest request,
                                    HttpServletResponse response,
                                    FilterChain filterChain) throws ServletException, IOException {

        long start = System.currentTimeMillis();

        try {
            filterChain.doFilter(request, response);
        } finally {
            long duration = System.currentTimeMillis() - start;
            LocalDateTime now = LocalDateTime.now();

            Authentication auth = SecurityContextHolder.getContext().getAuthentication();
            String caller = (auth != null && auth.isAuthenticated()
                    && !"anonymousUser".equals(auth.getName()))
                    ? auth.getName() : "anonymous";

            apiLogRepository.save(ApiLog.builder()
                    .caller(caller)
                    .method(request.getMethod())
                    .endpoint(request.getRequestURI())
                    .queryParams(request.getQueryString())
                    .httpStatus(response.getStatus())
                    .durationMs(duration)
                    .calledAt(now)
                    .build());

            apiEventProducer.sendApiCallEvent(ApiCallEvent.builder()
                    .caller(caller)
                    .method(request.getMethod())
                    .endpoint(request.getRequestURI())
                    .httpStatus(response.getStatus())
                    .durationMs(duration)
                    .calledAt(now)
                    .build());
        }
    }
}

