FROM python:3.12.11-slim-bookworm@sha256:519591d6871b7bc437060736b9f7456b8731f1499a57e22e6c285135ae657bf7 AS runtime

ARG FMC_RELEASE_SHA=unknown
LABEL org.opencontainers.image.source="https://github.com/samorakibagendi254/find-my-customer" \
      org.opencontainers.image.revision="${FMC_RELEASE_SHA}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN groupadd --gid 10001 app && useradd --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY find-first-customers ./find-first-customers
COPY examples ./examples

RUN pip install --no-cache-dir . && \
    python -c "from find_my_customer.skill_runtime import report_schema; assert report_schema()['type'] == 'object'" && \
    chown -R app:app /app

USER app

EXPOSE 8000

HEALTHCHECK --interval=20s --timeout=4s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=3)"

CMD ["python", "-m", "find_my_customer.web"]
