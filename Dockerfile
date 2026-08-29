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

# ~3,500 chunks and minutes of CPU to build, so it lives outside the image
# and survives a rebuild. Mount it: -v $(pwd)/data/chroma:/app/data/chroma
VOLUME /app/data/chroma

EXPOSE 5000

# gunicorn, not app.run(). The dev server is single-threaded and app.py's
# __main__ block passes debug=True, which exposes the Werkzeug debugger --
# arbitrary code execution for anyone who can trigger an exception. Importing
# app:app means that block never runs.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", \
     "--workers", "2", "--threads", "4", \
     "--timeout", "120", \
     "app:app"]
