# ==========================================
# STAGE 1: Compile the High-Speed Java Engine
# ==========================================
FROM eclipse-temurin:17-jdk-alpine AS java-builder
WORKDIR /build
# Copy your maven configuration files
COPY .mvn/ .mvn
COPY mvnw pom.xml ./
# Download dependencies out-of-band to cache them safely on GitHub
RUN ./mvnw dependency:go-offline
COPY src ./src
# Build the optimized production JAR file, skipping test overhead
RUN ./mvnw clean package -DskipTests

# ==========================================
# STAGE 2: The Unified Ultra-Light Runtime Environment
# ==========================================
FROM python:3.10-slim-buster
WORKDIR /app

# Install OpenJDK 17 runtime (matched to Java 17 compiler) and minimal network tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    openjdk-17-jre-headless \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install lightweight Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright and only the Chromium driver (skipping Firefox/Webkit to save RAM)
RUN pip install playwright && playwright install chromium --with-deps

# Copy the compiled Java engine from Stage 1
COPY --from=java-builder /build/target/*.jar ./engine.jar

# Copy your Python orchestration scripts, background loops, and the ping engine
COPY . .

# Expose the web port required by Render's free tier
EXPOSE 10000

# Fire up your main Python supervisor process (which manages Java and tasks simultaneously)
CMD ["python", "main_supervisor.py"]
