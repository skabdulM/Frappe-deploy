# syntax=docker/dockerfile:1.4

ARG FRAPPE_PATH=https://github.com/frappe/frappe
ARG FRAPPE_BRANCH=version-15
ARG PYTHON_VERSION=3.11.6
ARG NODE_VERSION=18.18.2
ARG APPS_JSON_BASE64

# Base image for building
FROM frappe/bench:latest as builder

ARG FRAPPE_PATH
ARG FRAPPE_BRANCH
ARG PYTHON_VERSION
ARG NODE_VERSION
ARG APPS_JSON_BASE64

USER frappe

WORKDIR /home/frappe

# Install Frappe
RUN bench init \
    --skip-redis-config-generation \
    --frappe-path=${FRAPPE_PATH} \
    --frappe-branch=${FRAPPE_BRANCH} \
    --python=python${PYTHON_VERSION%.*} \
    frappe-bench

WORKDIR /home/frappe/frappe-bench

# Decode and install apps from apps.json
RUN if [ -n "${APPS_JSON_BASE64}" ]; then \
    echo "${APPS_JSON_BASE64}" | base64 -d > /tmp/apps.json && \
    bench install apps /tmp/apps.json; \
    fi

# Final stage
FROM frappe/erpnext:v15

# Copy built frappe bench from builder
COPY --from=builder --chown=frappe:frappe /home/frappe/frappe-bench /home/frappe/frappe-bench

# Copy nginx configuration templates
COPY --chown=frappe:frappe resources/nginx-template.conf /templates/nginx/frappe.conf.template
COPY --chown=frappe:frappe resources/nginx-entrypoint.sh /usr/local/bin/nginx-entrypoint.sh

# Make entrypoint executable
USER root
RUN chmod +x /usr/local/bin/nginx-entrypoint.sh
USER frappe

WORKDIR /home/frappe/frappe-bench

# Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000 || exit 1

# Default command (can be overridden in docker-compose)
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "4", "--timeout", "120", "frappe.app:application"]
