# Stage 1: Build the Java Engine using Maven
FROM eclipse-temurin:17-jdk-alpine AS java-builder
WORKDIR /build

# Install standard maven package
RUN apk add --no-cache maven

# Copy pom.xml and source files
COPY pom.xml ./
COPY src/ ./src/

# Build the jar package
RUN mvn clean package -DskipTests

# Stage 2: Setup Python & Playwright Runtime
FROM python:3.10-slim-bookworm

# Install system dependencies and Java runtime for the final image
RUN apt-get update && apt-get install -y \
    openjdk-17-jre-headless \
    curl \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy Python requirements and install dependencies
COPY requirements.txt ./

# CRITICAL FIX: Upgrade pip first to give it the modern package resolver matrix
RUN pip install --upgrade pip setuptools wheel
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install --with-deps chromium

# Copy application source code
COPY . .

# Copy built jar from the java-builder stage
COPY --from=java-builder /build/target/*.jar ./engine.jar

# Fixed to match Uvicorn port 10000 settings in main_supervisor.py
EXPOSE 10000

# Start command for supervisor
CMD ["python", "main_supervisor.py"]
