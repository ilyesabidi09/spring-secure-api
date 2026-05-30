package com.ilyesabidi.secureapi.messaging;

import com.ilyesabidi.secureapi.event.ApiCallEvent;
import io.awspring.cloud.sqs.operations.SqsTemplate;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

@Slf4j
@Component
@RequiredArgsConstructor
public class ApiEventProducer {

    @Value("${sqs.queue.api-logs:queue-api-logs-local}")
    private String queueApiLogs;

    @Value("${sqs.queue.security-alerts:queue-security-alerts-local}")
    private String queueSecurityAlerts;

    private final SqsTemplate sqsTemplate;

    public void sendApiCallEvent(ApiCallEvent event) {
        sqsTemplate.send(queueApiLogs, event);
        log.debug("Event sent to {} : {} {}", queueApiLogs, event.getMethod(), event.getEndpoint());

        if (event.getHttpStatus() == 403) {
            sqsTemplate.send(queueSecurityAlerts, event);
            log.warn("Security alert sent : {} tried to access {}", event.getCaller(), event.getEndpoint());
        }
    }
}
