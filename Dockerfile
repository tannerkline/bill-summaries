FROM python:3.9-slim

WORKDIR /usr/src/app

COPY app.py /usr/src/app
COPY util /usr/src/app/util
COPY models /usr/src/app/models
COPY social /usr/src/app/social
COPY fonts /usr/src/app/fonts

# install pip libaries
RUN python3 -m venv /opt/app/venv
RUN . /opt/app/venv/bin/activate \
    && pip3 install --upgrade pip \
    && pip install --no-cache-dir \
        beautifulsoup4 pillow \
        requests requests_oauthlib

ENV PATH="${PATH}:/opt/app/venv/bin"

ENTRYPOINT ["/opt/app/venv/bin/python", "/usr/src/app/app.py"]
