FROM otel/opentelemetry-collector-contrib:0.143.0 AS collector

# The upstream runtime is scratch. Alpine retains its pinned Collector binary
# and provides wget for the configured health_check extension endpoint.
FROM alpine:3.24
RUN apk add --no-cache busybox ca-certificates \
    && addgroup -S -g 10001 otel \
    && adduser -S -D -H -u 10001 -G otel otel
COPY --from=collector --chown=otel:otel /otelcol-contrib /otelcol-contrib
USER otel:otel
ENTRYPOINT ["/otelcol-contrib"]
CMD ["--config=/etc/otelcol-contrib/config.yaml"]
