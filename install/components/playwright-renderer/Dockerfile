FROM mcr.microsoft.com/playwright/python:v1.62.0-noble

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_ROOT_USER_ACTION=ignore \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN pip install --no-cache-dir \
      playwright==1.62.0 \
      fastapi==0.141.1 \
      uvicorn==0.52.4 \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin ragpw \
    && mkdir -p /app /state \
    && chown -R ragpw:ragpw /app /state

WORKDIR /app
COPY --chown=ragpw:ragpw app/ /app/

USER ragpw

EXPOSE 8080
CMD ["uvicorn", "renderer:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1", "--no-access-log"]
