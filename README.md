# Verificador de Desenhos CAD (LeafTek QA/QC)

API FastAPI que audita desenhos DXF/DWG (camadas, cotas sobrescritas, lista de material,
furação NBR 8800, solda, notas técnicas e ortografia) e devolve um PDF A1 marcado e um laudo CSV.

## Rodar localmente

```bash
pip install -r backend/requirements.txt
cd backend && uvicorn main:app --port 8000
```

Interface em http://localhost:8000. DWG exige o `dwg2dxf` (LibreDWG) instalado no servidor;
sem ele, envie DXF.

## Docker

```bash
docker build -t verificador-cad .
docker run -p 8000:8000 verificador-cad
```

`--build-arg WITH_DWG=1` compila o LibreDWG na imagem (não validado neste repositório).

Variáveis: `PORT` (8000), `WEB_CONCURRENCY` (2 processos), `CAD_MAX_UPLOAD_MB` (50),
`CAD_REPORT_TTL_HOURS` (24, tempo até apagar PDFs/CSVs gerados).
