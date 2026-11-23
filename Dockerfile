# syntax=docker/dockerfile:1

############ build stage: install the package into a venv ############
FROM python:3-slim AS builder
ARG TARGETARCH
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

# On 32-bit ARM (Raspberry Pi 2) PyPI has few prebuilt wheels; piwheels has them.
RUN if [ "$TARGETARCH" = "arm" ]; then \
    printf '[global]\nextra-index-url=https://www.piwheels.org/simple\n' > /etc/pip.conf; \
    fi

# Compiler + headers only as a fallback if a dependency (e.g. lxml) has no wheel
# for the target platform. They never reach the final image.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libxml2-dev libxslt1-dev libffi-dev libssl-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH

WORKDIR /build
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install .

############ runtime stage ############
FROM python:3-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata libxml2 libxslt1.1 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --uid 1000 --create-home app \
    && mkdir -p /config /data && chown app /data

COPY --from=builder /opt/venv /opt/venv
COPY docker/entrypoint.sh /usr/local/bin/docker-entrypoint.sh
COPY docker/google_login.py /usr/local/bin/google-login.py
RUN chmod 755 /usr/local/bin/docker-entrypoint.sh

ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    SYNC_INTERVAL_SECONDS=3600 \
    GOOGLE_CREDENTIALS_PATH=/config/google_credentials.json \
    GOOGLE_TOKEN_PATH=/data/google_token.json

# Fail the build early if the CLI entry point is not there.
RUN calendar-sync --help >/dev/null

USER app
WORKDIR /data
VOLUME ["/data"]
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["loop"]
