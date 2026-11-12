FROM python:3.14-slim

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY . /app
RUN useradd --create-home --uid 10001 appuser && mkdir -p /data/private-evidence && chown -R appuser:appuser /app /data/private-evidence && chmod +x /app/scripts/docker-entrypoint.sh
USER appuser
RUN DJANGO_SECRET_KEY=build-only-throwaway python manage.py collectstatic --noinput
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 CMD ["python", "-c", "import os, urllib.request; host=os.environ.get('DJANGO_ALLOWED_HOSTS', 'localhost').split(',')[0].strip() or 'localhost'; headers={'Host': host}; headers.update({'X-Forwarded-Proto': 'https'} if os.environ.get('DJANGO_HTTPS_MODE', '').strip() == 'proxy' else {}); request=urllib.request.Request('http://127.0.0.1:8000/accounts/login/', headers=headers); urllib.request.urlopen(request, timeout=3)"]
ENTRYPOINT ["/app/scripts/docker-entrypoint.sh"]
CMD ["gunicorn", "scms.wsgi:application", "--bind", "0.0.0.0:8000"]
