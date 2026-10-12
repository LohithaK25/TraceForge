FROM grafana/tempo:3.1.0 AS tempo

# The upstream runtime is distroless. Alpine keeps the pinned Tempo binary and
# adds wget so Compose can check Tempo's actual readiness endpoint.
FROM alpine:3.24
RUN apk add --no-cache busybox ca-certificates \
    && addgroup -S -g 10001 tempo \
    && adduser -S -D -H -u 10001 -G tempo tempo \
    && mkdir -p /var/tempo \
    && chown tempo:tempo /var/tempo
COPY --from=tempo --chown=tempo:tempo /tempo /tempo
USER tempo:tempo
ENTRYPOINT ["/tempo"]
CMD ["-config.file=/etc/tempo/tempo.yaml"]
