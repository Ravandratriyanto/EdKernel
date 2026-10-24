# 3.12 because the COOL AMI ships preconfigured venvs for 3.10-3.12 only.
# Matching it here keeps local, CI and the Graviton box on one interpreter.
FROM python:3.12-slim

# ffmpeg is a system binary, so requirements.txt cannot express it, and
# video/frame_extractor.py shells out to it. Without this line the image
# installs cleanly and then dies the first time anyone uploads a video.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements alone first. Docker caches each step, so editing app.py
# does not reinstall chromadb and opencv every build.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Default paths — override with -e flags or ECS task definition env vars.
# DB_DIR   → where users.db lives   (mount an EFS volume here in production)
# CHROMA_DIR → where ChromaDB lives (mount an EFS volume here in production)
ENV DB_DIR=/app/.logs
ENV CHROMA_DIR=/app/data/chroma

# Both dirs must survive container restarts. Mount EFS or a named volume here.
VOLUME /app/.logs
VOLUME /app/data/chroma

EXPOSE 5000

# gunicorn, not app.run(). The dev server is single-threaded and app.py's
# __main__ block passes debug=True, which exposes the Werkzeug debugger --
# arbitrary code execution for anyone who can trigger an exception. Importing
# app:app means that block never runs.
#
# users.init() runs once, alone, before the workers start. Switching users.db
# out of WAL needs every other connection closed; with two workers both calling
# init() at boot they lock each other out and the task crash-loops. Retried
# because EFS can hold a dead task's lock for a short while.
CMD ["sh", "-c", "for i in 1 2 3 4 5 6; do python -c 'import users; users.init()' && break; echo 'users.init failed, retrying in 10s'; sleep 10; done; exec gunicorn --bind 0.0.0.0:5000 --workers 2 --threads 4 --timeout 120 app:app"]
