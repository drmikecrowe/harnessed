# Recipe Dockerfile for: gstack (Phase 8 test artifact)
#
# ARG HARNESS is stripped by the assembler during concatenation but is needed for
# standalone builds so Docker can resolve the ${HARNESS} reference below.
# The assembler provides the canonical `FROM harnessed-${HARNESS}:latest` header;
# this file must NOT contain a FROM line.
ARG HARNESS=claude

RUN pnpm dlx @gstack/install --host ${HARNESS} --version 1.2.3
