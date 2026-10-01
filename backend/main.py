import os
import re
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

# Módulos de auditoria e gerador de pranchas
from layer_checker import LayerChecker
from bom_checker import BOMChecker
from a1_pdf_generator import A1VerificationPDFGenerator

app = FastAPI(
    title="LeafTek CAD QA/QC Engine",
    description="Motor automatizado de verificação técnica de desenhos mecânicos e estruturais (NBR 8800 / AWS D1.1)",
    version="2.5.0"
)

# Habilita CORS total para conexões via navegador / Codespaces
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


# ==============================================================================
# AUDITOR DE COTAS SOBRESCRITAS (DIMENSION OVERRIDES)
# ==============================================================================
class DimensionChecker:
    """Detecta cotas com valores digitados manualmente (override), mascarando erros de projeto."""
    
    def check(self, doc: ezdxf.document.Drawing) -> Dict[str, Any]:
        issues: List[Dict[str, Any]] = []
        count_dims = 0
        overridden_count = 0

        target_layout = doc.modelspace()
        for lay in doc.layouts:
            if lay.name.lower() != "model":
                if sum(1 for e in lay if e.dxftype() != "VIEWPORT") > 10:
                    target_layout = lay
                    break

        for dim in target_layout.query("DIMENSION"):
            count_dims += 1
            custom_text = dim.dxf.get("text", "").strip()

            # No AutoCAD, "<>" representa a medição real paramétrica
            if custom_text and custom_text != "<>" and custom_text != "":
                # Se não contiver "<>", a cota foi forçada com texto fixo
                if "<>" not in custom_text:
                    overridden_count += 1
                    pt = getattr(dim.dxf, "text_midpoint", None) or getattr(dim.dxf, "defpoint", (0, 0))
                    
                    issues.append({
                        "id": f"DIM-OVR-{overridden_count}",
                        "tipo": "Cota Sobrescrita (Override)",
                        "gravidade": "CRITICA",
                        "descricao": f"Cota com medição adulterada para '{custom_text}'. Deve utilizar a medição paramétrica (<>).",
                        "posicao": {"x": round(float(pt[0]), 2), "y": round(float(pt[1]), 2)}
                    })

        return {
            "modulo": "dimension_checker",
            "total_cotas": count_dims,
            "cotas_sobrescritas": overridden_count,
            "status": "REPROVADO" if overridden_count > 0 else "APROVADO",
            "inconformidades": issues
        }


# ==============================================================================
# AUDITOR DE NOTAS GERAIS E NORMAS TÉCNICAS
# ==============================================================================
class StandardNotesChecker:
    """Verifica notas obrigatórias de caldeiraria e fabricação conforme NBR 8800 / AWS."""
    
    def check(self, doc: ezdxf.document.Drawing) -> Dict[str, Any]:
        issues: List[Dict[str, Any]] = []
        all_text = ""

        for entity in doc.modelspace().query("TEXT MTEXT"):
            t = entity.dxf.text if entity.dxftype() == "TEXT" else entity.text
            all_text += " " + t.upper()

        for lay in doc.layouts:
            if lay.name.lower() != "model":
                for entity in lay.query("TEXT MTEXT"):
                    t = entity.dxf.text if entity.dxftype() == "TEXT" else entity.text
                    all_text += " " + t.upper()

        # 1. Nota de Unidade Padrão
        if "MILÍMETRO" not in all_text and "MILIMETRO" not in all_text and "MM" not in all_text:
            issues.append({
                "id": "NOTE-MISS-1",
                "tipo": "Nota Obrigatória Ausente",
                "gravidade": "MEDIA",
                "descricao": "Nota de unidade: 'DIMENSÕES EM MILÍMETROS' não identificada na prancha.",
                "posicao": {"x": 0.0, "y": 0.0}
            })

        # 2. Especificação de Eletrodo / Soldagem
        if "AWS" not in all_text and "E7018" not in all_text and "SOLDA" not in all_text:
            issues.append({
                "id": "NOTE-MISS-2",
                "tipo": "Especificação Técnica de Solda",
                "gravidade": "BAIXA",
                "descricao": "Especificação de processo de soldagem ou eletrodo estrutural (AWS / NBR) não informada.",
                "posicao": {"x": 0.0, "y": 0.0}
            })

        return {
            "modulo": "standard_notes_checker",
            "status": "APROVADO COM RESSALVA" if issues else "APROVADO",
            "inconformidades": issues
        }


# ==============================================================================
# UTILITÁRIO DE CONVERSÃO DWG -> DXF (LIBREDWG)
# ==============================================================================
def convert_dwg_to_dxf(input_dwg_path: str, output_dxf_path: str):
    """Converte arquivo DWG para DXF via utilitário nativo dwg2dxf."""
    try:
        cmd = ["dwg2dxf", "-y", "-o", output_dxf_path, input_dwg_path]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=40)
        
        if not os.path.exists(output_dxf_path) or os.path.getsize(output_dxf_path) == 0:
            raise RuntimeError(f"Falha na conversão do DWG. Log: {result.stderr or result.stdout}")
    except FileNotFoundError:
        raise RuntimeError("O utilitário 'dwg2dxf' não foi encontrado no sistema Linux.")
    except subprocess.TimeoutExpired:
        raise RuntimeError("Tempo limite de 40s excedido ao processar arquivo DWG.")


# ==============================================================================
# ROTAS DA API FASTAPI
# ==============================================================================
@app.get("/")
def health_check():
    return {
        "sistema": "LeafTek CAD QA/QC Engine",
        "status": "OPERACIONAL",
        "padroes_suportados": ["ABNT NBR 8800", "AWS D1.1", "ISO A1"],
        "versao": "2.5.0"
    }


@app.post("/audit")
@app.post("/upload")
async def audit_cad_file(file: UploadFile = File(...)):
    filename = file.filename
    ext = os.path.splitext(filename)[1].lower()

    if ext not in [".dwg", ".dxf"]:
        raise HTTPException(status_code=400, detail="Formato não suportado. Envie arquivos .DWG ou .DXF.")

    file_id = str(uuid.uuid4())[:8]
    temp_input = os.path.join(TEMP_DIR, f"{file_id}_{filename}")
    dxf_target = os.path.join(TEMP_DIR, f"{file_id}_converted.dxf") if ext == ".dwg" else temp_input

    # 1. Salva arquivo enviado no disco temporário
    with open(temp_input, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # 2. Converte para DXF caso seja DWG
    if ext == ".dwg":
        try:
            convert_dwg_to_dxf(temp_input, dxf_target)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Erro na conversão DWG: {str(e)}")

    # 3. Leitura com Recuperação Geométrica (ezdxf.recover)
    try:
        doc, auditor = recover.readfile(dxf_target)
    except Exception:
        try:
            doc = ezdxf.readfile(dxf_target)
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Não foi possível carregar a geometria CAD: {str(e)}")

    # ==============================================================================
    # 4. EXECUÇÃO DOS MÓDULOS DE AUDITORIA
    # ==============================================================================
    inconformidades: List[Dict[str, Any]] = []

    # Auditoria de Camadas e Propriedades ByLayer
    layer_res = LayerChecker().check(doc)
    inconformidades.extend(layer_res.get("inconformidades", []))

    # Auditoria de Cotas Sobrescritas / Adulteradas
    dim_res = DimensionChecker().check(doc)
    inconformidades.extend(dim_res.get("inconformidades", []))

    # Auditoria da Lista de Materiais e Pesos Teóricos (BOM)
    bom_res = BOMChecker(steel_density=7850.0, tolerance_kg=0.15).check(doc)
    inconformidades.extend(bom_res.get("inconformidades", []))

    # Auditoria de Notas Gerais de Projeto
    notes_res = StandardNotesChecker().check(doc)
    inconformidades.extend(notes_res.get("inconformidades", []))

    # ==============================================================================
    # 5. CÁLCULO DO SCORE DE CONFORMIDADE E STATUS FINAL
    # ==============================================================================
    penalidades = {"CRITICA": 25.0, "ALTA": 10.0, "MEDIA": 4.0, "BAIXA": 1.5}
    pontos_perdidos = sum(penalidades.get(err.get("gravidade", "MEDIA"), 5.0) for err in inconformidades)
    score_final = max(0.0, round(100.0 - pontos_perdidos, 1))

    tem_critica = any(e.get("gravidade") == "CRITICA" for e in inconformidades)
    tem_alta = any(e.get("gravidade") == "ALTA" for e in inconformidades)

    if tem_critica or tem_alta or score_final < 80.0:
        status_geral = "REPROVADO"
    elif inconformidades:
        status_geral = "APROVADO COM RESSALVA"
    else:
        status_geral = "APROVADO"

    audit_result = {
        "arquivo": filename,
        "data_verificacao": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        "status_geral": status_geral,
        "score_conformidade": score_final,
        "resumo_auditoria": {
            "total_inconformidades": len(inconformidades),
            "camadas": layer_res.get("status"),
            "cotas": dim_res.get("status"),
            "lista_material": bom_res.get("status"),
            "notas_gerais": notes_res.get("status")
        },
        "detalhes_bom": {
            "peso_declarado_kg": bom_res.get("peso_total_declarado_kg", 0.0),
            "peso_calculado_kg": bom_res.get("peso_total_calculado_kg", 0.0),
            "itens_auditados": bom_res.get("itens_auditados", 0)
        },
        "inconformidades": inconformidades
    }

    # ==============================================================================
    # 6. GERAÇÃO DA CÓPIA DE VERIFICAÇÃO TÉCNICA A1 (PDF)
    # ==============================================================================
    pdf_filename = f"Verificacao_A1_{os.path.splitext(filename)[0]}.pdf"
    pdf_generator = A1VerificationPDFGenerator(output_dir=REPORTS_DIR)
    
    try:
        pdf_path = pdf_generator.generate(doc, audit_result, pdf_filename)
        audit_result["pdf_url"] = f"/download-pdf/{pdf_filename}"
    except Exception as e:
        audit_result["pdf_url"] = None
        audit_result["pdf_erro"] = f"Falha na geração do PDF A1: {str(e)}"

    # Limpeza dos arquivos temporários de entrada
    try:
        if os.path.exists(temp_input):
            os.remove(temp_input)
        if ext == ".dwg" and os.path.exists(dxf_target):
            os.remove(dxf_target)
    except Exception:
        pass

    return audit_result


@app.get("/download-pdf/{filename}")
@app.get("/reports/{filename}")
async def download_report_pdf(filename: str):
    """Disponibiliza o download direto da folha de verificação A1."""
    pdf_path = os.path.join(REPORTS_DIR, filename)
    if not os.path.exists(pdf_path):
        raise HTTPException(status_code=404, detail="Arquivo PDF não encontrado ou expirado.")

    return FileResponse(
        path=pdf_path,
        media_type="application/pdf",
        filename=filename
    )
