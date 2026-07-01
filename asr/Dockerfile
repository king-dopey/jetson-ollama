ARG ASR_APP_BASE_IMAGE=asr-runtime-base:cuda13-2-sm90

FROM ${ASR_APP_BASE_IMAGE} AS runtime

WORKDIR /app

# Copy application code
RUN addgroup --system app && adduser --system --ingroup app app
COPY --chown=app:app ./*.py ./
COPY --chown=app:app ./providers/*.py ./providers/
COPY --chown=app:app ./entrypoint.sh ./
RUN chmod +x /app/entrypoint.sh && mkdir -p /app/models && chown -R app:app /app

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD python3 -c "import urllib.request, socket; socket.setdefaulttimeout(5); urllib.request.urlopen('http://127.0.0.1:8000/healthz')" || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
