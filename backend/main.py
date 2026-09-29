import os
import shutil
import tempfile
from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
import ezdxf

from dimension_checker import DimensionChecker

app = FastAPI(title="Motor de Verificação CAD LeafTek")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/auditar")
async def auditar_desenho(file: UploadFile = File(...)):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".dxf") as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    try:
        doc = ezdxf.readfile(tmp_path)
        dim_results = DimensionChecker().check(doc)
        return {
            "arquivo": file.filename,
            "status_geral": dim_results["status"],
            "auditoria_cotas": dim_results
        }
    except Exception as e:
        return {"erro": f"Falha ao processar o arquivo: {str(e)}"}
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)