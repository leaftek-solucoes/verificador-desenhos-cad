FROM python:3.12-slim

# Conversão DWG -> DXF (LibreDWG, dwg2dxf). Desligada por padrão: sem ela o sistema
# aceita DXF normalmente e responde com mensagem clara quando recebe DWG.
# Para ativar: docker build --build-arg WITH_DWG=1 -t verificador-cad .
ARG WITH_DWG=0
ARG LIBREDWG_VERSION=0.13.3
RUN if [ "$WITH_DWG" = "1" ]; then \
      apt-get update && apt-get install -y --no-install-recommends build-essential curl xz-utils ca-certificates \
      && curl -fsSL "https://ftp.gnu.org/gnu/libredwg/libredwg-${LIBREDWG_VERSION}.tar.xz" | tar -xJ -C /tmp \
      && cd "/tmp/libredwg-${LIBREDWG_VERSION}" && ./configure --disable-bindings && make -j"$(nproc)" && make install && ldconfig \
      && cd / && rm -rf /tmp/libredwg-* \
      && apt-get purge -y build-essential curl xz-utils && apt-get autoremove -y && rm -rf /var/lib/apt/lists/* ; \
    fi

WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend backend
COPY frontend frontend

WORKDIR /app/backend
ENV PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT} --workers ${WEB_CONCURRENCY:-2}"]
