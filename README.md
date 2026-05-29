# 🚀 Demo API — Spring Boot + Keycloak + ActiveMQ

A secured REST API built to demonstrate a real-world backend architecture with role-based access control, event-driven logging, and full containerization.

---

## 🧱 What's inside

| Technology | Role |
|---|---|
| **Spring Boot 4** | REST API framework |
| **Spring Security + OAuth2** | JWT-based authentication |
| **Keycloak** | Authorization Server (manages users, roles, tokens) |
| **PostgreSQL** | Persistent storage for API logs |
| **ActiveMQ** | Message broker — event-driven architecture |
| **Docker / Docker Compose** | Containerization |

---

## 🔐 How authentication works

This app is a **Resource Server** — it does not generate tokens. Tokens are issued by **Keycloak** and validated here.

```
Postman / Client
     │
     │  POST /token (username + password)
     ▼
  Keycloak :9090          ← Authorization Server
     │
     │  JWT Token
     ▼
  demo-app :8080          ← Resource Server (this project)
     │
     │  validates JWT signature via JWKS
     │  extracts roles from realm_access.roles
     ▼
  Endpoint (allowed or 403)
```

---

## 👥 Users & Roles

| User | Password | Role | Access |
|------|----------|------|--------|
| alice | alice1234 | ADMIN | `/admin` `/dev` `/qa` |
| bob | bob1234 | DEV | `/dev` only |
| charlie | charlie1234 | QA | `/qa` only |

> Admins have access to everything.

---

## 📡 Endpoints

| Method | Endpoint | Auth required | Role |
|--------|----------|---------------|------|
| GET | `/hello` | ❌ No | Public |
| GET | `/admin` | ✅ Yes | ADMIN |
| GET | `/dev` | ✅ Yes | DEV or ADMIN |
| GET | `/qa` | ✅ Yes | QA or ADMIN |

---

## 📨 Event-Driven Logging

Every API call triggers two actions automatically:

1. **Saved to PostgreSQL** — table `api_logs`
2. **Published to ActiveMQ** — two queues:
   - `queue.api.logs` — all API calls (caller, endpoint, status, duration)
   - `queue.security.alerts` — fired when a user gets a **403 Forbidden**

```
Request → Filter → Save to DB
                 → Publish to ActiveMQ → Consumer logs the event
                                       → Security alert if 403
```

---

## 🐳 Running the project

> This app depends on the **infrastructure** project (Keycloak + PostgreSQL + ActiveMQ).  
> Start that first.

```bash
# 1. Start infrastructure
cd ../infrastructure
docker compose up -d

# 2. Start the app
cd demo
docker compose up --build -d
```

The app will be available at `http://localhost:8080`.

---

## 🔑 Getting a token (Postman or curl)

```bash
curl -X POST http://localhost:9090/realms/ilyes-realm/protocol/openid-connect/token \
  -d "client_id=demo-client" \
  -d "username=alice" \
  -d "password=alice1234" \
  -d "grant_type=password"
```

Then use the `access_token` in your requests:
```
Authorization: Bearer <token>
```

A ready-to-use **Postman collection** is available at the root of the repository: `ilyes-realm.postman_collection.json`

---

## 🗂️ Project structure

```
demo/
├── src/main/java/com/example/demo/
│   ├── config/
│   │   ├── SecurityConfig.java       # OAuth2 + role extraction from JWT
│   │   └── JmsConfig.java            # ActiveMQ Jackson converter
│   ├── controller/
│   │   ├── HelloWorld.java           # Public endpoint
│   │   └── SecuredController.java    # Role-protected endpoints
│   ├── entity/
│   │   └── ApiLog.java               # DB entity for API logs
│   ├── filter/
│   │   └── ApiLoggingFilter.java     # Intercepts every request
│   ├── messaging/
│   │   ├── ApiEventProducer.java     # Publishes events to ActiveMQ
│   │   └── ApiEventConsumer.java     # Listens and processes events
│   └── event/
│       └── ApiCallEvent.java         # Event DTO
├── Dockerfile                        # Multi-stage build
├── docker-compose.yml                # App container only
└── README.md
```

---

## 📊 Monitoring

| Tool | URL | Credentials |
|------|-----|-------------|
| ActiveMQ Console | http://localhost:8161 | admin / admin |
| Keycloak Admin | http://localhost:9090 | admin / admin |
| pgAdmin | http://localhost:5050 | admin@admin.com / admin |
