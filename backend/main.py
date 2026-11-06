import os
import re
import time
import uuid
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
from dimension_checker import DimensionChecker
from text_checker import TextChecker
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

MAX_UPLOAD_MB = float(os.getenv("CAD_MAX_UPLOAD_MB", "50"))
REPORT_TTL_HOURS = float(os.getenv("CAD_REPORT_TTL_HOURS", "24"))

# Penalidade por ocorrência e teto por tipo de apontamento: 40 linhas com cor forçada
# continuam aparecendo no laudo, mas não zeram sozinhas a nota do desenho.
PENALIDADES = {"CRITICA": 20.0, "ALTA": 8.0, "MEDIA": 4.0, "BAIXA": 1.5}
MAX_OCORRENCIAS_POR_TIPO = 3


def calcular_score(inconformidades: List[Dict[str, Any]]) -> float:
    por_tipo: Dict[tuple, int] = {}
    deducoes = 0.0
    for e in inconformidades:
        grav = e.get("gravidade", "MEDIA")
        chave = (e.get("tipo", ""), grav)
        por_tipo[chave] = por_tipo.get(chave, 0) + 1
        if por_tipo[chave] <= MAX_OCORRENCIAS_POR_TIPO:
            deducoes += PENALIDADES.get(grav, 4.0)
    return max(0.0, round(100.0 - deducoes, 1))


def safe_filename(name: str) -> str:
    """Remove diretórios e caracteres problemáticos do nome enviado pelo navegador."""
    base = os.path.basename((name or "").replace("\\", "/"))
    base = re.sub(r"[^\w.\- ]", "_", base).strip(" .")
    return base[:120] or "desenho"


def cleanup_old_reports():
    limite = time.time() - REPORT_TTL_HOURS * 3600
    for d in (REPORTS_DIR, TEMP_DIR):
        for f in os.listdir(d):
            fp = os.path.join(d, f)
            try:
                if os.path.isfile(fp) and os.path.getmtime(fp) < limite:
                    os.remove(fp)
            except OSError:
                pass


def convert_dwg_to_dxf(input_path: str, output_path: str):
    """Executa a conversão via utilitário nativo do LibreDWG."""
    cmd = ["dwg2dxf", "-y", "-o", output_path, input_path]
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=45)
    except FileNotFoundError:
        raise RuntimeError("Conversor DWG (LibreDWG/dwg2dxf) não instalado no servidor. Envie o arquivo em DXF.")
    except subprocess.TimeoutExpired:
        raise RuntimeError("Tempo esgotado na conversão do DWG. Tente exportar o arquivo como DXF.")
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
def audit_cad_file(file: UploadFile = File(...)):
    # Rota síncrona: o FastAPI executa em thread separada e o processamento pesado
    # (leitura do CAD e PDF A1) não trava o atendimento das outras requisições.
    filename = safe_filename(file.filename)
    ext = os.path.splitext(filename)[1].lower()
    if ext not in [".dwg", ".dxf"]:
        raise HTTPException(status_code=400, detail="Formato não suportado. Envie arquivos DWG ou DXF.")

    cleanup_old_reports()

    file_id = uuid.uuid4().hex[:12]
    temp_in = os.path.join(TEMP_DIR, f"{file_id}{ext}")
    dxf_target = os.path.join(TEMP_DIR, f"{file_id}_converted.dxf") if ext == ".dwg" else temp_in

    try:
        limite = int(MAX_UPLOAD_MB * 1024 * 1024)
        recebido = 0
        with open(temp_in, "wb") as buf:
            while chunk := file.file.read(1024 * 1024):
                recebido += len(chunk)
                if recebido > limite:
                    raise HTTPException(status_code=413, detail=f"Arquivo acima do limite de {MAX_UPLOAD_MB:g} MB.")
                buf.write(chunk)

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

        return _run_audit(doc, filename, file_id)
    finally:
        # Limpeza de temporários também em caso de erro
        for f in {temp_in, dxf_target}:
            if os.path.exists(f):
                try:
                    os.remove(f)
                except Exception:
                    pass


def _run_audit(doc, filename: str, file_id: str) -> Dict[str, Any]:
    # Execução de todos os módulos especializados de inspeção
    inconformidades: List[Dict[str, Any]] = []

    layer_res = LayerChecker().check(doc)
    dim_res = DimensionChecker().check(doc)
    bom_res = BOMChecker(steel_density=7850.0, tolerance_kg=0.15).check(doc)
    dfm_res = DFMChecker().check(doc)
    weld_res = WeldChecker().check(doc)
    notes_res = StandardNotesChecker().check(doc)
    text_res = TextChecker().check(doc)

    for res in (layer_res, dim_res, bom_res, dfm_res, weld_res, notes_res, text_res):
        inconformidades.extend(res.get("inconformidades", []))

    # Críticas primeiro: o quadro do PDF mostra só os 7 primeiros itens
    ordem = list(PENALIDADES)
    inconformidades.sort(key=lambda e: ordem.index(e["gravidade"]) if e.get("gravidade") in ordem else len(ordem))

    # Cálculo ponderado da conformidade
    score_final = calcular_score(inconformidades)

    status_geral = "REPROVADO" if any(e.get("gravidade") == "CRITICA" for e in inconformidades) or score_final < 80.0 else ("APROVADO COM RESSALVA" if inconformidades else "APROVADO")

    audit_result = {
        "arquivo": filename,
        "data_verificacao": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        "status_geral": status_geral,
        "score_conformidade": score_final,
        "detalhes_bom": {
            "peso_declarado_kg": bom_res.get("peso_total_declarado_kg", 0.0),
            "peso_calculado_kg": bom_res.get("peso_total_calculado_kg", 0.0),
            "itens_auditados": bom_res.get("itens_auditados", 0)
        },
        "resumo_modulos": {
            "camadas": layer_res.get("status"),
            "cotas": dim_res.get("status"),
            "lista_material": bom_res.get("status"),
            "dfm_furacao": dfm_res.get("status"),
            "soldagem": weld_res.get("status"),
            "notas_tecnicas": notes_res.get("status"),
            "ortografia": text_res.get("status")
        },
        "inconformidades": inconformidades
    }

    # Emissão dos laudos técnicos (id único no nome: dois clientes com o mesmo
    # nome de arquivo não sobrescrevem nem baixam o laudo um do outro)
    base = os.path.splitext(filename)[0]
    pdf_filename = f"Verificacao_A1_{base}_{file_id}.pdf"
    csv_filename = f"Laudo_QAQC_{base}_{file_id}.csv"

    A1VerificationPDFGenerator(output_dir=REPORTS_DIR).generate(doc, audit_result, pdf_filename)
    ReportExporter(output_dir=REPORTS_DIR).export_csv(audit_result, csv_filename)

    audit_result["pdf_url"] = f"/download/{pdf_filename}"
    audit_result["csv_url"] = f"/download/{csv_filename}"
    return audit_result


@app.get("/download/{filename}")
@app.get("/download-pdf/{filename}")
async def download_file(filename: str):
    if filename != os.path.basename(filename) or filename.startswith("."):
        raise HTTPException(status_code=404, detail="Arquivo não encontrado.")
    fpath = os.path.join(REPORTS_DIR, filename)
    if not os.path.isfile(fpath):
        raise HTTPException(status_code=404, detail="Arquivo não encontrado.")
    return FileResponse(
        path=fpath,
        filename=filename,
        headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache", "Expires": "0"}
    )
