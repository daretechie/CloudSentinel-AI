# ================================================
# Stage 1: Builder (Installs dependencies)
# ================================================
FROM python:3.12-slim AS builder

# Set working directory
WORKDIR /app

# Install poetry (our dependency manager)
RUN pip install --no-cache-dir poetry==1.8.2

# Copy only dependencies file first (for layer caching)
COPY pyproject.toml poetry.lock ./

# Export dependencies to requirements.txt (lighter than using Poetry in prod)
# --only main: Excludes dev dependencies (pytest, type stubs, etc.)
RUN poetry config virtualenvs.create false \
  && poetry export -f requirements.txt --output requirements.txt --without-hashes --only main

# ================================================
# Stage 2: Runtime (Lean production image)
# ================================================
FROM python:3.12-slim AS runtime

# Security: RUN as non-root user
RUN useradd --create-home appuser
WORKDIR /app

# Install runtime dependencies only
COPY --from=builder /app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY ./app ./app

# Switch to non-root user
USER appuser

# Expose port and define health check
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

# RUN the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

