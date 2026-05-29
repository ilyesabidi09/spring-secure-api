package com.ilyesabidi.secureapi.controller;

import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class SecuredController {

    @GetMapping("/admin")
    @PreAuthorize("hasRole('ADMIN')")
    public String adminEndpoint() {
        return "Bienvenue Admin !";
    }

    @GetMapping("/dev")
    @PreAuthorize("hasRole('DEV') or hasRole('ADMIN')")
    public String devEndpoint() {
        return "Bienvenue DÃ©veloppeur !";
    }

    @GetMapping("/qa")
    @PreAuthorize("hasRole('QA') or hasRole('ADMIN')")
    public String qaEndpoint() {
        return "Bienvenue QA !";
    }
}

