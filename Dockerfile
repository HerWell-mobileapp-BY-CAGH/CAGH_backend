FROM python:3.12-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV MALLOC_ARENA_MAX 2

# Set work directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . /app/

# Expose port
EXPOSE 8000

# Admin provisioning can be triggered on a single deploy by setting
# ADMIN_RESET_ON_START=true with ADMIN_USERNAME, ADMIN_EMAIL, and ADMIN_PASSWORD.
# Remove ADMIN_RESET_ON_START immediately after that deploy to prevent later resets.
CMD ["sh", "-c", "python manage.py migrate && if [ \"$ADMIN_RESET_ON_START\" = \"true\" ]; then python manage.py reset_admin || exit $?; fi && python manage.py seed_facilities && python manage.py collectstatic --noinput && daphne -b 0.0.0.0 -p 8000 config.asgi:application"]
