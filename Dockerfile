
# ---------------------------------------------------------
# Stage 1: Build the Java engine
# ---------------------------------------------------------
FROM eclipse-temurin:17-jdk-alpine AS java-builder

WORKDIR /build

RUN apk add --no-cache maven

COPY pom.xml ./
COPY src/ ./src/

RUN mvn --batch-mode --no-transfer-progress clean package \
    -DskipTests

RUN test -f /build/target/engine.jar


# ---------------------------------------------------------
# Stage 2: Python, Java runtime, Playwright and Supervisor
# ---------------------------------------------------------
FROM python:3.10-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=10000 \
    HOST=0.0.0.0 \
    LOG_LEVEL=INFO \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

# Install Java runtime and Supervisor.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        openjdk-17-jre-headless \
        supervisor \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies.
COPY requirements.txt ./

RUN python -m pip install --no-cache-dir --upgrade pip setuptools wheel \
    && python -m pip install --no-cache-dir -r requirements.txt

# Install Chromium and the OS dependencies Playwright needs.
RUN python -m playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*

# Copy the application.
COPY . .

# Copy the exact JAR produced by the Maven build.
COPY --from=java-builder /build/target/engine.jar /app/engine.jar

# Use the actual configuration filename supplied in this repository.
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

EXPOSE 10000

CMD ["/usr/bin/supervisord", "-n", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
