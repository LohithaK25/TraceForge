FROM maven:3.9.16-eclipse-temurin-21 AS build
WORKDIR /workspace
COPY pom.xml .
RUN mvn -B -q dependency:go-offline
COPY src ./src
RUN mvn -B -q package -DskipTests

FROM eclipse-temurin:21-jre-alpine
WORKDIR /app
RUN addgroup -S traceforge && adduser -S -G traceforge traceforge
COPY --from=build /workspace/target/order-service-0.1.0-SNAPSHOT.jar app.jar
USER traceforge
EXPOSE 8082
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
