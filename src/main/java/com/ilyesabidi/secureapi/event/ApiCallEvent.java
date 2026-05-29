package com.ilyesabidi.secureapi.event;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.io.Serializable;
import java.time.LocalDateTime;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class ApiCallEvent implements Serializable {

    private String caller;
    private String method;
    private String endpoint;
    private Integer httpStatus;
    private Long durationMs;
    private LocalDateTime calledAt;
}

