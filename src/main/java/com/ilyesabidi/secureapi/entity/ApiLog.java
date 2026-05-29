package com.ilyesabidi.secureapi.entity;

import jakarta.persistence.*;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;
import lombok.AllArgsConstructor;

import java.time.LocalDateTime;

@Entity
@Table(name = "api_logs")
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class ApiLog {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    private String caller;
    private String method;
    private String endpoint;
    private String queryParams;
    private Integer httpStatus;
    private Long durationMs;
    private LocalDateTime calledAt;
}

