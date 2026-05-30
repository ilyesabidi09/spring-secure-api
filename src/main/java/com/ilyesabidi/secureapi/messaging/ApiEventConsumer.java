package com.ilyesabidi.secureapi.messaging;

import com.ilyesabidi.secureapi.event.ApiCallEvent;
import io.awspring.cloud.sqs.annotation.SqsListener;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

@Slf4j
@Component
public class ApiEventConsumer {

    @SqsListener("${sqs.queue.api-logs:queue-api-logs-local}")
    public void onApiCall(ApiCallEvent event) {
        log.info("[API LOG] {} {} {} - {}ms - status {}",
                event.getCaller(),
                event.getMethod(),
                event.getEndpoint(),
                event.getDurationMs(),
                event.getHttpStatus());
    }

    @SqsListener("${sqs.queue.security-alerts:queue-security-alerts-local}")
    public void onSecurityAlert(ApiCallEvent event) {
        log.warn("[SECURITY ALERT] User '{}' was denied access to '{}' at {}",
                event.getCaller(),
                event.getEndpoint(),
                event.getCalledAt());
    }
}
