FROM python:3.12-slim

WORKDIR /usr/src/app

# Narrated videos use FFmpeg and Kokoro's neural TTS model. Kokoro is
# fully local once the model has been downloaded during this image build.
RUN apt-get update \
    && apt-get install --yes --no-install-recommends ffmpeg libsndfile1

# install pip libaries
RUN python3 -m venv /opt/app/venv
RUN . /opt/app/venv/bin/activate \
    && pip3 install --upgrade pip \
    && pip install --no-cache-dir \
        beautifulsoup4 pillow \
        google-api-python-client \
        kokoro-onnx==0.6.1 soundfile==0.13.1 \
        requests requests_oauthlib

# Bundle the full-quality model and all voices for offline CPU inference.
RUN mkdir -p /usr/src/app/voices
ADD https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/kokoro-v1.0.onnx /usr/src/app/voices/kokoro-v1.0.onnx
ADD https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/voices-v1.0.bin /usr/src/app/voices/voices-v1.0.bin

COPY app.py /usr/src/app
COPY util /usr/src/app/util
COPY models /usr/src/app/models
COPY social /usr/src/app/social
COPY fonts /usr/src/app/fonts

ENV PATH="${PATH}:/opt/app/venv/bin"

ENTRYPOINT ["/opt/app/venv/bin/python", "/usr/src/app/app.py"]
