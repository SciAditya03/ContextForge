"""Package -> technology knowledge base used for stack detection.

Each entry maps a package name (lower-cased) to (technology name, category).
Matching is exact unless the key ends with ``*`` (prefix match).
"""

from __future__ import annotations

PACKAGE_TECH: dict[str, tuple[str, str]] = {
    # ---------- Python web / API
    "fastapi": ("FastAPI", "framework"), "flask": ("Flask", "framework"), "django": ("Django", "framework"),
    "djangorestframework": ("Django REST Framework", "framework"), "starlette": ("Starlette", "framework"),
    "aiohttp": ("aiohttp", "framework"), "tornado": ("Tornado", "framework"), "sanic": ("Sanic", "framework"),
    "litestar": ("Litestar", "framework"), "quart": ("Quart", "framework"), "bottle": ("Bottle", "framework"),
    "uvicorn": ("Uvicorn", "runtime"), "gunicorn": ("Gunicorn", "runtime"), "hypercorn": ("Hypercorn", "runtime"),
    "pydantic": ("Pydantic", "validation"), "marshmallow": ("Marshmallow", "validation"),
    "strawberry-graphql": ("Strawberry GraphQL", "framework"), "graphene": ("Graphene", "framework"),
    "streamlit": ("Streamlit", "framework"), "gradio": ("Gradio", "framework"),
    # ---------- Python data
    "sqlalchemy": ("SQLAlchemy", "orm"), "sqlmodel": ("SQLModel", "orm"), "alembic": ("Alembic", "migration"),
    "peewee": ("Peewee", "orm"), "tortoise-orm": ("Tortoise ORM", "orm"), "mongoengine": ("MongoEngine", "orm"),
    "psycopg2": ("PostgreSQL", "database"), "psycopg2-binary": ("PostgreSQL", "database"), "psycopg": ("PostgreSQL", "database"),
    "asyncpg": ("PostgreSQL", "database"), "pymysql": ("MySQL", "database"), "mysqlclient": ("MySQL", "database"),
    "aiomysql": ("MySQL", "database"), "pymongo": ("MongoDB", "database"), "motor": ("MongoDB", "database"),
    "redis": ("Redis", "cache"), "aioredis": ("Redis", "cache"), "aiosqlite": ("SQLite", "database"),
    "elasticsearch": ("Elasticsearch", "database"), "cassandra-driver": ("Cassandra", "database"),
    "pandas": ("pandas", "library"), "numpy": ("NumPy", "library"), "scikit-learn": ("scikit-learn", "ml"),
    "torch": ("PyTorch", "ml"), "tensorflow": ("TensorFlow", "ml"), "transformers": ("Hugging Face Transformers", "ml"),
    "langchain": ("LangChain", "ai"), "langchain-core": ("LangChain", "ai"), "llama-index": ("LlamaIndex", "ai"),
    "openai": ("OpenAI API", "integration"), "anthropic": ("Anthropic API", "integration"),
    "google-generativeai": ("Google Gemini API", "integration"), "google-genai": ("Google Gemini API", "integration"),
    # ---------- Python auth / security
    "python-jose": ("JWT (python-jose)", "auth"), "pyjwt": ("JWT (PyJWT)", "auth"), "passlib": ("Passlib", "auth"),
    "bcrypt": ("bcrypt", "auth"), "authlib": ("Authlib (OAuth)", "auth"), "fastapi-users": ("FastAPI Users", "auth"),
    "django-allauth": ("django-allauth", "auth"), "flask-login": ("Flask-Login", "auth"), "flask-jwt-extended": ("Flask-JWT-Extended", "auth"),
    "argon2-cffi": ("Argon2", "auth"),
    # ---------- Python async / queue
    "celery": ("Celery", "queue"), "rq": ("RQ", "queue"), "dramatiq": ("Dramatiq", "queue"), "kombu": ("Kombu", "queue"),
    "apscheduler": ("APScheduler", "worker"), "arq": ("arq", "queue"), "pika": ("RabbitMQ", "queue"),
    "kafka-python": ("Kafka", "queue"), "aiokafka": ("Kafka", "queue"), "confluent-kafka": ("Kafka", "queue"),
    # ---------- Python infra
    "boto3": ("AWS SDK", "cloud"), "botocore": ("AWS SDK", "cloud"), "google-cloud-storage": ("Google Cloud Storage", "cloud"),
    "google-cloud-*": ("Google Cloud", "cloud"), "azure-*": ("Azure", "cloud"), "firebase-admin": ("Firebase", "cloud"),
    "stripe": ("Stripe", "integration"), "twilio": ("Twilio", "integration"), "sendgrid": ("SendGrid", "integration"),
    "sentry-sdk": ("Sentry", "logging"), "structlog": ("structlog", "logging"), "loguru": ("Loguru", "logging"),
    "requests": ("Requests", "http_client"), "httpx": ("HTTPX", "http_client"),
    "pytest": ("pytest", "testing"), "pytest-asyncio": ("pytest-asyncio", "testing"), "hypothesis": ("Hypothesis", "testing"),
    "unittest2": ("unittest", "testing"), "coverage": ("coverage.py", "testing"), "tox": ("tox", "testing"),
    "black": ("Black", "build"), "ruff": ("Ruff", "build"), "mypy": ("mypy", "build"), "flake8": ("Flake8", "build"),
    "python-dotenv": ("python-dotenv", "config"), "pydantic-settings": ("pydantic-settings", "config"),
    # ---------- JS frameworks
    "next": ("Next.js", "framework"), "react": ("React", "framework"), "react-dom": ("React DOM", "framework"),
    "vue": ("Vue", "framework"), "nuxt": ("Nuxt", "framework"), "svelte": ("Svelte", "framework"),
    "@sveltejs/kit": ("SvelteKit", "framework"), "@angular/core": ("Angular", "framework"), "solid-js": ("SolidJS", "framework"),
    "astro": ("Astro", "framework"), "remix": ("Remix", "framework"), "@remix-run/react": ("Remix", "framework"),
    "react-native": ("React Native", "framework"), "expo": ("Expo", "framework"), "electron": ("Electron", "framework"),
    "express": ("Express", "framework"), "fastify": ("Fastify", "framework"), "koa": ("Koa", "framework"),
    "@nestjs/core": ("NestJS", "framework"), "hono": ("Hono", "framework"), "@hapi/hapi": ("hapi", "framework"),
    "apollo-server": ("Apollo Server", "framework"), "@apollo/server": ("Apollo Server", "framework"),
    "@apollo/client": ("Apollo Client", "http_client"), "graphql": ("GraphQL", "framework"),
    "@trpc/server": ("tRPC", "framework"), "socket.io": ("Socket.IO", "realtime"), "ws": ("WebSocket (ws)", "realtime"),
    # ---------- JS data
    "prisma": ("Prisma", "orm"), "@prisma/client": ("Prisma", "orm"), "typeorm": ("TypeORM", "orm"),
    "sequelize": ("Sequelize", "orm"), "mongoose": ("Mongoose", "orm"), "drizzle-orm": ("Drizzle ORM", "orm"),
    "knex": ("Knex", "orm"), "pg": ("PostgreSQL", "database"), "mysql2": ("MySQL", "database"), "mysql": ("MySQL", "database"),
    "sqlite3": ("SQLite", "database"), "better-sqlite3": ("SQLite", "database"), "mongodb": ("MongoDB", "database"),
    "ioredis": ("Redis", "cache"), "@supabase/supabase-js": ("Supabase", "database"), "firebase": ("Firebase", "cloud"),
    "@planetscale/database": ("PlanetScale", "database"), "@neondatabase/serverless": ("Neon Postgres", "database"),
    # ---------- JS state / UI
    "redux": ("Redux", "state"), "@reduxjs/toolkit": ("Redux Toolkit", "state"), "zustand": ("Zustand", "state"),
    "jotai": ("Jotai", "state"), "recoil": ("Recoil", "state"), "mobx": ("MobX", "state"), "pinia": ("Pinia", "state"),
    "@tanstack/react-query": ("TanStack Query", "state"), "swr": ("SWR", "state"), "xstate": ("XState", "state"),
    "tailwindcss": ("Tailwind CSS", "styling"), "styled-components": ("styled-components", "styling"),
    "@emotion/react": ("Emotion", "styling"), "sass": ("Sass", "styling"), "@mui/material": ("Material UI", "ui"),
    "@chakra-ui/react": ("Chakra UI", "ui"), "antd": ("Ant Design", "ui"), "@radix-ui/*": ("Radix UI", "ui"),
    "lucide-react": ("Lucide", "ui"), "framer-motion": ("Framer Motion", "ui"), "@xyflow/react": ("React Flow", "ui"),
    "zod": ("Zod", "validation"), "yup": ("Yup", "validation"), "joi": ("Joi", "validation"), "react-hook-form": ("React Hook Form", "library"),
    "axios": ("Axios", "http_client"), "node-fetch": ("node-fetch", "http_client"), "ky": ("ky", "http_client"),
    # ---------- JS auth
    "next-auth": ("NextAuth.js", "auth"), "@auth/core": ("Auth.js", "auth"), "passport": ("Passport", "auth"),
    "jsonwebtoken": ("JWT (jsonwebtoken)", "auth"), "jose": ("JOSE/JWT", "auth"), "bcryptjs": ("bcrypt", "auth"),
    "@clerk/nextjs": ("Clerk", "auth"), "@auth0/nextjs-auth0": ("Auth0", "auth"), "firebase-auth": ("Firebase Auth", "auth"),
    "express-session": ("express-session", "auth"), "lucia": ("Lucia", "auth"), "iron-session": ("iron-session", "auth"),
    # ---------- JS infra
    "@aws-sdk/*": ("AWS SDK", "cloud"), "aws-sdk": ("AWS SDK", "cloud"), "@google-cloud/*": ("Google Cloud", "cloud"),
    "@azure/*": ("Azure", "cloud"), "@vercel/*": ("Vercel", "deploy"), "stripe-node": ("Stripe", "integration"),
    "@stripe/stripe-js": ("Stripe", "integration"), "nodemailer": ("Nodemailer", "integration"), "bullmq": ("BullMQ", "queue"),
    "bull": ("Bull", "queue"), "amqplib": ("RabbitMQ", "queue"), "kafkajs": ("Kafka", "queue"),
    "winston": ("Winston", "logging"), "pino": ("Pino", "logging"), "morgan": ("Morgan", "logging"), "@sentry/*": ("Sentry", "logging"),
    "cors": ("CORS middleware", "middleware"), "helmet": ("Helmet", "middleware"), "dotenv": ("dotenv", "config"),
    "jest": ("Jest", "testing"), "vitest": ("Vitest", "testing"), "mocha": ("Mocha", "testing"), "chai": ("Chai", "testing"),
    "@playwright/test": ("Playwright", "testing"), "cypress": ("Cypress", "testing"), "@testing-library/react": ("Testing Library", "testing"),
    "supertest": ("Supertest", "testing"),
    "typescript": ("TypeScript", "language"), "vite": ("Vite", "build"), "webpack": ("webpack", "build"), "esbuild": ("esbuild", "build"),
    "turbo": ("Turborepo", "build"), "eslint": ("ESLint", "build"), "prettier": ("Prettier", "build"), "@biomejs/biome": ("Biome", "build"),
    "nodemon": ("nodemon", "build"), "ts-node": ("ts-node", "runtime"), "tsx": ("tsx", "runtime"),
    "openai-node": ("OpenAI API", "integration"), "@anthropic-ai/sdk": ("Anthropic API", "integration"),
    "@google/generative-ai": ("Google Gemini API", "integration"), "@google/genai": ("Google Gemini API", "integration"),
    # ---------- Java / Kotlin
    "org.springframework.boot:spring-boot-starter-web": ("Spring Boot (Web)", "framework"),
    "org.springframework.boot:spring-boot-starter-data-jpa": ("Spring Data JPA", "orm"),
    "org.springframework.boot:spring-boot-starter-security": ("Spring Security", "auth"),
    "org.springframework.boot:*": ("Spring Boot", "framework"), "org.hibernate*": ("Hibernate", "orm"),
    "org.postgresql:postgresql": ("PostgreSQL", "database"), "mysql:mysql-connector-java": ("MySQL", "database"),
    "com.mysql:mysql-connector-j": ("MySQL", "database"), "junit:junit": ("JUnit", "testing"),
    "org.junit.jupiter:*": ("JUnit 5", "testing"), "io.ktor:*": ("Ktor", "framework"), "io.quarkus:*": ("Quarkus", "framework"),
    "io.micronaut:*": ("Micronaut", "framework"), "org.mockito:*": ("Mockito", "testing"), "org.projectlombok:lombok": ("Lombok", "library"),
    # ---------- Go
    "github.com/gin-gonic/gin": ("Gin", "framework"), "github.com/labstack/echo/v4": ("Echo", "framework"),
    "github.com/gofiber/fiber/v2": ("Fiber", "framework"), "github.com/go-chi/chi/v5": ("chi", "framework"),
    "github.com/gorilla/mux": ("Gorilla Mux", "framework"), "gorm.io/gorm": ("GORM", "orm"), "github.com/jackc/pgx/v5": ("PostgreSQL", "database"),
    "github.com/lib/pq": ("PostgreSQL", "database"), "github.com/go-redis/redis/v8": ("Redis", "cache"), "github.com/redis/go-redis/v9": ("Redis", "cache"),
    "github.com/golang-jwt/jwt/v5": ("JWT (golang-jwt)", "auth"), "google.golang.org/grpc": ("gRPC", "framework"),
    "github.com/stretchr/testify": ("testify", "testing"), "github.com/spf13/cobra": ("Cobra CLI", "library"),
    # ---------- Rust
    "actix-web": ("Actix Web", "framework"), "axum": ("Axum", "framework"), "rocket": ("Rocket", "framework"),
    "tokio": ("Tokio", "runtime"), "serde": ("Serde", "library"), "diesel": ("Diesel", "orm"), "sqlx": ("SQLx", "orm"),
    "sea-orm": ("SeaORM", "orm"), "reqwest": ("reqwest", "http_client"), "tonic": ("tonic (gRPC)", "framework"),
    "warp": ("warp", "framework"), "clap": ("clap CLI", "library"), "jsonwebtoken-rs": ("JWT", "auth"),
    # ---------- PHP / Ruby
    "laravel/framework": ("Laravel", "framework"), "symfony/*": ("Symfony", "framework"), "slim/slim": ("Slim", "framework"),
    "doctrine/orm": ("Doctrine", "orm"), "phpunit/phpunit": ("PHPUnit", "testing"), "guzzlehttp/guzzle": ("Guzzle", "http_client"),
    "rails": ("Ruby on Rails", "framework"), "sinatra": ("Sinatra", "framework"), "activerecord": ("ActiveRecord", "orm"),
    "rspec": ("RSpec", "testing"), "rspec-rails": ("RSpec", "testing"), "devise": ("Devise", "auth"), "sidekiq": ("Sidekiq", "queue"),
    "pg-ruby": ("PostgreSQL", "database"), "puma": ("Puma", "runtime"),
    # ---------- Dart
    "flutter": ("Flutter", "framework"), "provider": ("Provider", "state"), "flutter_bloc": ("BLoC", "state"),
    "riverpod": ("Riverpod", "state"), "dio": ("Dio", "http_client"), "http": ("http (Dart)", "http_client"),
}

DOCKER_IMAGE_TECH: dict[str, tuple[str, str]] = {
    "postgres": ("PostgreSQL", "database"), "postgis/postgis": ("PostgreSQL", "database"), "mysql": ("MySQL", "database"),
    "mariadb": ("MariaDB", "database"), "mongo": ("MongoDB", "database"), "redis": ("Redis", "cache"),
    "memcached": ("Memcached", "cache"), "rabbitmq": ("RabbitMQ", "queue"), "elasticsearch": ("Elasticsearch", "database"),
    "nginx": ("Nginx", "deploy"), "traefik": ("Traefik", "deploy"), "minio/minio": ("MinIO", "storage"),
    "confluentinc/cp-kafka": ("Kafka", "queue"), "bitnami/kafka": ("Kafka", "queue"), "localstack/localstack": ("LocalStack (AWS)", "cloud"),
    "python": ("Python", "runtime"), "node": ("Node.js", "runtime"), "golang": ("Go", "runtime"), "openjdk": ("Java", "runtime"),
    "eclipse-temurin": ("Java", "runtime"), "rust": ("Rust", "runtime"), "php": ("PHP", "runtime"), "ruby": ("Ruby", "runtime"),
    "mcr.microsoft.com/dotnet/*": (".NET", "runtime"), "qdrant/qdrant": ("Qdrant", "database"), "chromadb/chroma": ("Chroma", "database"),
}

DEPLOY_FILE_TECH: dict[str, tuple[str, str]] = {
    "vercel.json": ("Vercel", "deploy"), "netlify.toml": ("Netlify", "deploy"), "fly.toml": ("Fly.io", "deploy"),
    "render.yaml": ("Render", "deploy"), "Procfile": ("Heroku-style Procfile", "deploy"), "app.yaml": ("Google App Engine", "deploy"),
    "serverless.yml": ("Serverless Framework", "deploy"), "firebase.json": ("Firebase Hosting", "deploy"),
    "railway.json": ("Railway", "deploy"), "amplify.yml": ("AWS Amplify", "deploy"), "Chart.yaml": ("Helm", "deploy"),
    "cloudbuild.yaml": ("Google Cloud Build", "deploy"),
}


def lookup_package(name: str) -> tuple[str, str] | None:
    key = name.lower()
    if key in PACKAGE_TECH:
        return PACKAGE_TECH[key]
    for k, v in PACKAGE_TECH.items():
        if k.endswith("*") and key.startswith(k[:-1]):
            return v
    return None


def lookup_image(image: str) -> tuple[str, str] | None:
    base = image.split("@", 1)[0]
    base = base.rsplit(":", 1)[0] if ":" in base.rsplit("/", 1)[-1] else base
    base = base.removeprefix("docker.io/").removeprefix("library/")
    if base in DOCKER_IMAGE_TECH:
        return DOCKER_IMAGE_TECH[base]
    for k, v in DOCKER_IMAGE_TECH.items():
        if k.endswith("*") and base.startswith(k[:-1]):
            return v
    return None
