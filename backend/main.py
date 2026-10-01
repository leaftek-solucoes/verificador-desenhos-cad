import os
import uuid
import shutil
import subprocess
from datetime import datetime
from typing import Dict, Any, List

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

import ezdxf
from ezdxf import recover

# Módulos do Sistema Especialista
from layer_checker import LayerChecker
from bom_checker import BOMChecker
from dfm_checker import DFMChecker
from weld_checker import WeldChecker
from notes_checker import StandardNotesChecker
from a1_pdf_generator import A1VerificationPDFGenerator
from report_exporter import ReportExporter

app = FastAPI(
    title="LeafTek CAD QA/QC Engine",
    description="Motor de verificação técnica de desenhos mecânicos e estruturas metálicas",
    version="3.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

TEMP_DIR = "temp_uploads"
REPORTS_DIR = "temp_reports"
os.makedirs(TEMP_DIR, exist_ok=True)
os.makedirs(REPORTS_DIR, exist_ok=True)

# Auditor de Cotas Sobrescritas / Override
class DimensionChecker:
    def check(self, doc: ezdxf.document.Drawing) -> Dict[str, Any]:
        issues = []
        target_layout = doc.modelspace()
        for lay in doc.layouts:
            if lay.name.lower() != "model":
                if sum(1 for e in lay if e.dxftype() != "VIEWPORT") > 10:
                    target_layout = lay
                    break

        count = 0
        for dim in target_layout.query("DIMENSION"):
            txt = dim.dxf.get("text", "").strip()
            if txt and txt != "<>" and "<>" not in txt:
                count += 1
                pt = getattr(dim.dxf, "text_midpoint", None) or getattr(dim.dxf, "defpoint", (0, 0))
                issues.append({
                    "id": f"DIM-OVR-{count}",
                    "tipo": "Cota Sobrescrita (Override)",
                    "gravidade": "CRITICA",
                    "descricao": f"Cota com medição forçada para '{txt}'. Deve usar a medição paramétrica (<>).",
                    "posicao": {"x": round(float(pt[0]), 2), "y": round(float(pt[1]), 2)}
                })

        return {"modulo": "dimension_checker", "status": "REPROVADO" if issues else "APROVADO", "inconformidades": issues}


def convert_dwg_to_dxf(input_path: str, output_path: str):
    """Executa a conversão via utilitário nativo do LibreDWG."""
    cmd = ["dwg2dxf", "-y", "-o", output_path, input_path]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=45)
    if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
        raise RuntimeError(f"Falha na conversão do arquivo DWG. Detalhe: {res.stderr or res.stdout}")


# Entrega da interface web integrada
@app.get("/")
@app.get("/app")
async def serve_index():
    candidates = ["index.html", "../index.html", "frontend/index.html", "../frontend/index.html"]
    for path in candidates:
        if os.path.exists(path):
            return FileResponse(path, media_type="text/html")
    return {"status": "OPERACIONAL", "versao": "3.0.0", "mensagem": "Interface HTML não localizada."}


@app.post("/audit")
@app.post("/upload")
@app.post("/verify")
async def audit_cad_file(file: UploadFile = File(...)):
    filename = file.filename
    ext = os.path.splitext(filename)[1].lower()
    if ext not in [".dwg", ".dxf"]:
        raise HTTPException(status_code=400, detail="Formato não suportado. Envie arquivos DWG ou DXF.")

    file_id = str(uuid.uuid4())[:8]
    temp_in = os.path.join(TEMP_DIR, f"{file_id}_{filename}")
    dxf_target = os.path.join(TEMP_DIR, f"{file_id}_converted.dxf") if ext == ".dwg" else temp_in

    with open(temp_in, "wb") as buf:
        shutil.copyfileobj(file.file, buf)

    if ext == ".dwg":
        try:
            convert_dwg_to_dxf(temp_in, dxf_target)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    try:
        doc, _ = recover.readfile(dxf_target)
    except Exception:
        try:
            doc = ezdxf.readfile(dxf_target)
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Erro ao processar dados vetoriais CAD: {str(e)}")

    # Execução de todos os módulos especializados de inspeção
    inconformidades: List[Dict[str, Any]] = []

    layer_res = LayerChecker().check(doc)
    dim_res = DimensionChecker().check(doc)
    bom_res = BOMChecker(steel_density=7850.0, tolerance_kg=0.15).check(doc)
    dfm_res = DFMChecker().check(doc)
    weld_res = WeldChecker().check(doc)
    notes_res = StandardNotesChecker().check(doc)

    inconformidades.extend(layer_res.get("inconformidades", []))
    inconformidades.extend(dim_res.get("inconformidades", []))
    inconformidades.extend(bom_res.get("inconformidades", []))
    inconformidades.extend(dfm_res.get("inconformidades", []))
    inconformidades.extend(weld_res.get("inconformidades", []))
    inconformidades.extend(notes_res.get("inconformidades", []))

    # Cálculo ponderado da conformidade
    penalidades = {"CRITICA": 20.0, "ALTA": 8.0, "MEDIA": 4.0, "BAIXA": 1.5}
    deducoes = sum(penalidades.get(e.get("gravidade", "MEDIA"), 4.0) for e in inconformidades)
    score_final = max(0.0, round(100.0 - deducoes, 1))

    status_geral = "REPROVADO" if any(e.get("gravidade") == "CRITICA" for e in inconformidades) or score_final < 80.0 else ("APROVADO COM RESSALVA" if inconformidades else "APROVADO")

    audit_result = {
        "arquivo": filename,
        "data_verificacao": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        "status_geral": status_geral,
        "score_conformidade": score_final,
        "detalhes_bom": {
            "peso_declarado_kg": bom_res.get("peso_total_declarado_kg", bom_res.get("peso_declarado_kg", 0.0)),
            "peso_calculado_kg": bom_res.get("peso_total_calculado_kg", bom_res.get("peso_calculado_kg", 0.0)),
            "itens_auditados": bom_res.get("itens_auditados", 0)
        },
        "resumo_modulos": {
            "camadas": layer_res.get("status"),
            "cotas": dim_res.get("status"),
            "lista_material": bom_res.get("status"),
            "dfm_furacao": dfm_res.get("status"),
            "soldagem": weld_res.get("status"),
            "notas_tecnicas": notes_res.get("status")
        },
        "inconformidades": inconformidades
    }

    # Emissão dos laudos técnicos
    pdf_filename = f"Verificacao_A1_{os.path.splitext(filename)[0]}.pdf"
    csv_filename = f"Laudo_QAQC_{os.path.splitext(filename)[0]}.csv"

    A1VerificationPDFGenerator(output_dir=REPORTS_DIR).generate(doc, audit_result, pdf_filename)
    ReportExporter(output_dir=REPORTS_DIR).export_csv(audit_result, csv_filename)

    audit_result["pdf_url"] = f"/download/{pdf_filename}"
    audit_result["csv_url"] = f"/download/{csv_filename}"

    # Limpeza de temporários
    for f in [temp_in, dxf_target]:
        if os.path.exists(f):
            try:
                os.remove(f)
            except Exception:
                pass

    return audit_result


@app.get("/download/{filename}")
@app.get("/download-pdf/{filename}")
async def download_file(filename: str):
    fpath = os.path.join(REPORTS_DIR, filename)
    if not os.path.exists(fpath):
        raise HTTPException(status_code=404, detail="Arquivo não encontrado.")
    return FileResponse(
        path=fpath,
        filename=filename,
        headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache", "Expires": "0"}
    )
