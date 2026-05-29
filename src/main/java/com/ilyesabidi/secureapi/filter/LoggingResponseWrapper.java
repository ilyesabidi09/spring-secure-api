package com.ilyesabidi.secureapi.filter;

import jakarta.servlet.http.HttpServletResponse;
import jakarta.servlet.http.HttpServletResponseWrapper;

public class LoggingResponseWrapper extends HttpServletResponseWrapper {

    private int status = 200;

    public LoggingResponseWrapper(HttpServletResponse response) {
        super(response);
    }

    @Override
    public void setStatus(int sc) {
        this.status = sc;
        super.setStatus(sc);
    }

    @Override
    public void sendError(int sc) throws java.io.IOException {
        this.status = sc;
        super.sendError(sc);
    }

    @Override
    public void sendError(int sc, String msg) throws java.io.IOException {
        this.status = sc;
        super.sendError(sc, msg);
    }

    @Override
    public int getStatus() {
        return status;
    }
}

