FROM python:3.9-slim

WORKDIR /usr/src/app

# The debug video artifact uses FFmpeg and Piper's neural TTS model. Piper is
# fully local once the model has been downloaded during this image build.
RUN apt-get update \
    && apt-get install --yes --no-install-recommends ffmpeg

# install pip libaries
RUN python3 -m venv /opt/app/venv
RUN . /opt/app/venv/bin/activate \
    && pip3 install --upgrade pip \
    && pip install --no-cache-dir \
        beautifulsoup4 pillow \
        google-api-python-client \
        piper-tts==1.6.0 \
        requests requests_oauthlib

# The ONNX model and its JSON configuration are kept in the image rather than
# fetched during a debug run. Lessac high supplies a higher-fidelity American
# voice for narration. Change PIPER_MODEL and add its voice files to use a
# different Piper voice.
RUN /opt/app/venv/bin/python -m piper.download_voices \
        --data-dir /usr/src/app/voices \
        en_US-lessac-high

COPY app.py /usr/src/app
COPY util /usr/src/app/util
COPY models /usr/src/app/models
COPY social /usr/src/app/social
COPY fonts /usr/src/app/fonts

ENV PATH="${PATH}:/opt/app/venv/bin"

ENTRYPOINT ["/opt/app/venv/bin/python", "/usr/src/app/app.py"]
