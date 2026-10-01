# syntax=docker/dockerfile:1

# ---- frontend build stage ----
FROM node:20-slim AS frontend-build
WORKDIR /build
COPY frontend/package.json ./
RUN npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- backend image (also serves the built page at / as a fallback) ----
FROM python:3.11-slim AS backend
ENV PYTHONUNBUFFERED=1
WORKDIR /app
COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY backend/app /app/app
# app/main.py serves the page from /frontend/dist when the directory exists
COPY --from=frontend-build /build/dist /frontend/dist
EXPOSE 8000
HEALTHCHECK --interval=5s --timeout=3s --retries=10 --start-period=5s \
    CMD python -c "import json,urllib.request,sys; r=urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=3); sys.exit(0 if json.load(r)['status']=='ok' else 1)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

# ---- one-shot verification image ----
FROM backend AS verify
RUN pip install --no-cache-dir pytest==8.3.4 httpx==0.28.1
COPY backend/tests /app/tests
COPY verify /verify
CMD ["sh", "/verify/run.sh"]

# ---- frontend served by nginx, proxying API calls to the backend ----
FROM nginx:1.27-alpine AS frontend
COPY --from=frontend-build /build/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
