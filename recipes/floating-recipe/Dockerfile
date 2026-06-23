# Phase 8 test fixture — contains a floating --branch ref (triggers ASM-02 PinValidationError).
#
# WARNING: This Dockerfile is intentionally malformed for testing purposes only.
# The URL below is unreachable (example.com/fake-repo.git) — it must never be
# used in a real build. The assembler's validate_pin() gate rejects this file
# before any docker build command is issued.
ARG HARNESS=claude

RUN git clone --branch main https://example.com/fake-repo.git /opt/fake
