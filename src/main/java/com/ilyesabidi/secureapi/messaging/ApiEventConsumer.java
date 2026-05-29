package com.ilyesabidi.secureapi.messaging;

import com.ilyesabidi.secureapi.event.ApiCallEvent;
import lombok.extern.slf4j.Slf4j;
import org.springframework.jms.annotation.JmsListener;
import org.springframework.stereotype.Component;

@Slf4j
@Component
public class ApiEventConsumer {

    @JmsListener(destination = "queue.api.logs")
    public void onApiCall(ApiCallEvent event) {
        log.info("[API LOG] {} {} {} - {}ms - status {}",
                event.getCaller(),
                event.getMethod(),
                event.getEndpoint(),
                event.getDurationMs(),
                event.getHttpStatus());
    }

    @JmsListener(destination = "queue.security.alerts")
    public void onSecurityAlert(ApiCallEvent event) {
        log.warn("[SECURITY ALERT] User '{}' was denied access to '{}' at {}",
                event.getCaller(),
                event.getEndpoint(),
                event.getCalledAt());
    }
}

