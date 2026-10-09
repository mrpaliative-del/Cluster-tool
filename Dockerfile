# Stage 1: Build the Java Engine using Maven
FROM eclipse-temurin:17-jdk-alpine AS java-builder
WORKDIR /build
RUN apk add --no-cache maven
COPY pom.xml ./
COPY src/ ./src/
RUN mvn clean package -DskipTests

# Stage 2: Setup Python, Playwright, and Supervisor Runtime
FROM python:3.10-slim-bookworm

# Install system dependencies, Java runtime, and supervisor
RUN apt-get update && apt-get install -y \
    openjdk-17-jre-headless \
    supervisor \
    curl \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy Python requirements and install dependencies
COPY requirements.txt ./
RUN pip install --upgrade pip setuptools wheel
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install --with-deps chromium

# Copy application source code and configuration mappings
COPY . .
COPY --from=java-builder /build/target/*.jar ./engine.jar
COPY supervisor.conf /etc/supervisor/conf.d/supervisord.conf

EXPOSE 10000

# Start command handed off directly to native OS supervisor process manager
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
