# Use an official Python runtime as the base image
FROM python:3.11-slim-bookworm


WORKDIR /opt/project

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=.

# Install system dependencies required for GeoDjango (GDAL/GEOS/PROJ) + build tools
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    gcc \
    g++ \
    libpq-dev \
    gdal-bin \
    libgdal-dev \
    libgeos-dev \
    libproj-dev \
    proj-bin \
    ; \
    rm -rf /var/lib/apt/lists/*



# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the whole project (since manage.py is at repo root)
COPY . .

EXPOSE 8000

COPY scripts/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
