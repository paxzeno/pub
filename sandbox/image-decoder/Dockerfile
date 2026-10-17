FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
RUN pip install --no-cache-dir Pillow==12.0.0
COPY decode.py /decode.py
USER 65534:65534
ENTRYPOINT ["python", "-I", "/decode.py"]
