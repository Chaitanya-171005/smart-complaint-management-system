FROM python:3.14-slim
WORKDIR /app
COPY requirements.txt requirements-dev.txt /app/
RUN python -m pip install --no-cache-dir -r requirements.txt -r requirements-dev.txt 'psycopg[binary]==3.3.8'
COPY . /app
RUN chmod -R a+rX /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
CMD ["python", "q05_checks/run.py"]
