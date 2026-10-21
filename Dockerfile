# The engine as a web service: Python + ffmpeg (with libass for captions) + fonts.
FROM python:3.12-slim-bookworm

RUN apt-get update -qq \
    && apt-get install -y -qq --no-install-recommends ffmpeg fonts-liberation fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md LICENSE OPTOUT.md ./
COPY core ./core
COPY roastmygithub ./roastmygithub
COPY api ./api
RUN pip install --no-cache-dir -e ".[web]"

ENV ROASTMYGITHUB_CACHE_DIR=/data/cache ROAST_OUT_DIR=/data/out PORT=8080
VOLUME ["/data"]
EXPOSE 8080
CMD ["uvicorn", "api.app:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "2"]
