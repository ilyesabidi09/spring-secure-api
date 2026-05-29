package com.ilyesabidi.secureapi.repository;

import com.ilyesabidi.secureapi.entity.ApiLog;
import org.springframework.data.jpa.repository.JpaRepository;

public interface ApiLogRepository extends JpaRepository<ApiLog, Long> {
}

