package com.ilyesabidi.secureapi.messaging;

import com.ilyesabidi.secureapi.event.ApiCallEvent;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.jms.core.JmsTemplate;
import org.springframework.stereotype.Component;

@Slf4j
@Component
@RequiredArgsConstructor
public class ApiEventProducer {

    private static final String QUEUE_API_LOGS    = "queue.api.logs";
    private static final String QUEUE_SECURITY    = "queue.security.alerts";

    private final JmsTemplate jmsTemplate;

    public void sendApiCallEvent(ApiCallEvent event) {
        jmsTemplate.convertAndSend(QUEUE_API_LOGS, event);
        log.debug("Event sent to {} : {} {}", QUEUE_API_LOGS, event.getMethod(), event.getEndpoint());

        // Si 403 â†’ publier aussi sur la queue sÃ©curitÃ©
        if (event.getHttpStatus() == 403) {
            jmsTemplate.convertAndSend(QUEUE_SECURITY, event);
            log.warn("Security alert sent : {} tried to access {}", event.getCaller(), event.getEndpoint());
        }
    }
}

