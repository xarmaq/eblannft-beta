FROM python:3.12-slim

WORKDIR /app
COPY server.py /app/server.py

ENV EBLANNFT_HOST=0.0.0.0 \
    EBLANNFT_PORT=8787 \
    EBLANNFT_DATA_DIR=/data \
    EBLANNFT_PLUGIN_KEY=changeme

VOLUME ["/data"]
EXPOSE 8787

CMD ["python", "server.py"]
