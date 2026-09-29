import os
import shutil
import tempfile
from typing import Dict, Any, List
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import ezdxf

# Verificadores especialistas
from dimension_checker import DimensionChecker
from layer_checker import LayerChecker
from bom_checker import BOMChecker
from text_checker import TextChecker
from standard_checker import StandardChecker

# Gerador da Prancha A3
from a3_pdf_generator import A3VerificationPDFGenerator

app = FastAPI(
    title="LeafTek CAD Engine - QA/QC Checker",
    description="Motor de auditoria e emissão de cópias de verificação A3",
    version="1.1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

REPORTS_DIR = "temp_reports"
os.makedirs(REPORTS_DIR, exist_ok=True)

SEVERITY_WEIGHT = {
    "CRITICA": 4,
    "ALTA": 3,
    "MEDIA": 2,
    "BAIXA": 1
}

def executar_auditoria_completa(doc: ezdxf.document.Drawing, filename: str) -> Dict[str, Any]:
    dim_res = DimensionChecker(tolerance_mm=1.0).check(doc)
    lay_res = LayerChecker().check(doc)
    bom_res = BOMChecker(tolerance_pct=5.0).check(doc)
    txt_res = TextChecker().check(doc)
    std_res = StandardChecker().check(doc)

    todas_inconformidades: List[Dict[str, Any]] = (
        dim_res.get("inconformidades", [])
        + lay_res.get("inconformidades", [])
        + bom_res.get("inconformidades", [])
        + txt_res.get("inconformidades", [])
        + std_res.get("inconformidades", [])
    )

    todas_inconformidades.sort(
        key=lambda x: SEVERITY_WEIGHT.get(x.get("gravidade", "BAIXA"), 0),
        reverse=True
    )

    criticos = sum(1 for err in todas_inconformidades if err.get("gravidade") == "CRITICA")
    altas = sum(1 for err in todas_inconformidades if err.get("gravidade") == "ALTA")
    medias = sum(1 for err in todas_inconformidades if err.get("gravidade") == "MEDIA")

    scores = [
        dim_res.get("conformidade_percentual", 100.0),
        lay_res.get("conformidade_percentual", 100.0),
        bom_res.get("conformidade_percentual", 100.0),
        txt_res.get("conformidade_percentual", 100.0),
        std_res.get("conformidade_percentual", 100.0)
    ]
    score_geral = round(sum(scores) / len(scores), 1)

    if criticos > 0:
        status_geral = "REPROVADO"
    elif altas > 0 or medias > 2:
        status_geral = "APROVADO COM RESSALVAS"
    else:
        status_geral = "APROVADO"

    return {
        "arquivo": filename,
        "status_geral": status_geral,
        "score_conformidade": score_geral,
        "resumo_erros": {
            "total": len(todas_inconformidades),
            "criticos": criticos,
            "altos": altas,
            "medios": medias
        },
        "auditorias": {
            "cotas": dim_res,
            "camadas": lay_res,
            "lista_materiais": bom_res,
            "textos_e_notas": txt_res,
            "prancha_e_padroes": std_res
        },
        "inconformidades": todas_inconformidades
    }

@app.post("/auditar-a3")
async def auditar_e_gerar_a3(file: UploadFile = File(...)):
    filename = file.filename or "desenho.dxf"
    base_name = os.path.splitext(filename)[0]

    with tempfile.NamedTemporaryFile(delete=False, suffix=".dxf") as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    try:
        doc = ezdxf.readfile(tmp_path)
        audit_result = executar_auditoria_completa(doc, filename)

        # Gera o arquivo PDF no formato A3 com o traçado real
        pdf_filename = f"Verificacao_{base_name}.pdf"
        pdf_gen = A3VerificationPDFGenerator(output_dir=REPORTS_DIR)
        pdf_gen.generate(doc, audit_result, pdf_filename)

        audit_result["pdf_filename"] = pdf_filename
        return audit_result

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Falha na auditoria: {str(e)}")
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

@app.get("/download-pdf/{filename}")
def download_pdf(filename: str):
    file_path = os.path.join(REPORTS_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Relatório A3 não encontrado.")
    return FileResponse(
        file_path,
        media_type="application/pdf",
        filename=filename
    )
