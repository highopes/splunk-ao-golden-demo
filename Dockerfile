# syntax=docker/dockerfile:1
# Splunk AO Golden Demo: Streamlit app image (built for linux/amd64).
# No credential or environment-specific value is copied into the image:
# .streamlit/secrets.toml is mounted at run time (Kubernetes Secret), and
# .dockerignore keeps secrets.toml.*, .git, .venv, .runtime, .work, data and
# local agent context out of the build context.
FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b

ARG UV_VERSION=0.11.2
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    HOME=/home/app \
    DEMO_DATA_DIR=/data \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_SERVER_PORT=8501 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

RUN pip install "uv==${UV_VERSION}" \
 && groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --home-dir /home/app --create-home --shell /usr/sbin/nologin app \
 && mkdir -p /app /data \
 && chown app:app /data

WORKDIR /app

# Same dependency set as the validated local environment: requirements.txt
# constrained by requirements.lock.txt. The build fails if the set is inconsistent.
COPY requirements.txt requirements.lock.txt ./
RUN uv venv --python /usr/local/bin/python3 "$VIRTUAL_ENV" \
 && uv pip install --python "$VIRTUAL_ENV/bin/python" --no-cache -r requirements.txt \
 && uv pip check --python "$VIRTUAL_ENV/bin/python"

COPY . .

USER 10001:10001
EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=4).status == 200 else 1)"]
CMD ["python", "-m", "streamlit", "run", "app.py"]
