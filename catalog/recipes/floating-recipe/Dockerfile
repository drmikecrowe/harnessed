# Test fixture — contains a floating ref (triggers PinValidationError).
#
# WARNING: intentionally malformed for testing only. The URL below is unreachable
# (example.com/fake-repo.git) and must never be used in a real build — the assembler's
# validate_pin() gate rejects this file before any build command is issued.
RUN git clone --branch main https://example.com/fake-repo.git /opt/fake
