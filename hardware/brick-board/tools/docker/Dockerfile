# KiCad 9 with the Python packages the brick-board tools need.
FROM kicad/kicad:9.0
USER root
RUN apt-get update && apt-get install -y --no-install-recommends python3-scipy python3-reportlab python3-pil python3-numpy \
    && rm -rf /var/lib/apt/lists/*
USER kicad
