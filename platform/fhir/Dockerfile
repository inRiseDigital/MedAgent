# platform/fhir — HAPI FHIR JPA server + MedAgent interceptors
#
# Per docs/solution/03-fhir-data-platform.md §1 (ADR F-1) and 10-devops-infrastructure.md §1:
# official HAPI starter image extended with our interceptor JAR + configuration.
# Pinned exactly to the 8.10.x patch stream (03 §1: upgrades track 8.10.x patches;
# minor bumps are a staged runbook event per 10 §9.3 — never a `latest` tag).
#
# Build context expects the interceptor JAR to have been built first:
#   cd interceptors && mvn -B package
# (CI job `platform/fhir` per 10 §3.2 does this before the image build.)

FROM hapiproject/hapi:v8.10.4

# The starter image is a Spring Boot app launched with PropertiesLauncher.
# /app/extra-classes is on loader.path — anything dropped here joins the
# classpath, which is how our interceptor module is "plugged in" (03 §5:
# one audited Java module registered via the starter's custom-interceptor
# mechanism — see hapi.fhir.custom-interceptor-classes in application.yaml).
COPY interceptors/target/medagent-fhir-interceptors-*.jar /app/extra-classes/

# Server configuration (R4, validation-on-write, partitioning, interceptor
# registration). Datasource credentials arrive as env at runtime
# (HAPI_DB_URL / HAPI_DB_USER / HAPI_DB_PASS) — never baked in (10 §5).
COPY application.yaml /app/config/application.yaml

ENV SPRING_CONFIG_LOCATION=file:///app/config/application.yaml

# Non-root numeric USER per 10 §1 container standards (base image already runs
# as the distroless nonroot uid; declared explicitly so the image-policy check
# can assert it).
USER 65532

# NOTE (03 §1): this container must NEVER be port-published beyond the internal
# network. It is reachable only from core-api, agent-service, and the gateway's
# internal /fhir entrypoint (01 §1 design rule 1). Compose/IaC enforce this;
# the Dockerfile intentionally declares no EXPOSE on a public interface.
EXPOSE 8080
