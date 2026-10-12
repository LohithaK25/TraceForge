FROM maven:3.9.16-eclipse-temurin-21 AS build
ARG OTEL_JAVA_AGENT_VERSION=2.30.0
WORKDIR /workspace
COPY pom.xml .
RUN mvn -B -q dependency:go-offline
RUN mvn -B -q dependency:copy -Dartifact=io.opentelemetry.javaagent:opentelemetry-javaagent:${OTEL_JAVA_AGENT_VERSION} -DoutputDirectory=/workspace/otel \
    && mv /workspace/otel/opentelemetry-javaagent-${OTEL_JAVA_AGENT_VERSION}.jar /workspace/otel/opentelemetry-javaagent.jar
COPY src ./src
RUN mvn -B -q package -DskipTests

FROM eclipse-temurin:21-jre-alpine
WORKDIR /app
RUN addgroup -S traceforge && adduser -S -G traceforge traceforge
COPY --from=build /workspace/target/api-gateway-0.1.0-SNAPSHOT.jar app.jar
COPY --from=build /workspace/otel/opentelemetry-javaagent.jar /otel/opentelemetry-javaagent.jar
USER traceforge
EXPOSE 8080
ENTRYPOINT ["java", "-javaagent:/otel/opentelemetry-javaagent.jar", "-jar", "/app/app.jar"]
