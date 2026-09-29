import os
import shutil
import tempfile
import subprocess
from typing import Dict, Any, List
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import ezdxf

from dimension_checker import DimensionChecker
from layer_checker import LayerChecker
from bom_checker import BOMChecker
from text_checker import TextChecker
from standard_checker import StandardChecker
from a1_pdf_generator import A1VerificationPDFGenerator

app = FastAPI(
    title="LeafTek CAD QA/QC Engine",
    description="Motor de auditoria de projetos DWG/DXF com emissão de pranchas A1",
    version="1.3.0"
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

def converter_dwg_para_dxf(dwg_path: str) -> str:
    """
    Converte arquivos DWG para DXF via LibreDWG (dwg2dxf).
    Trata códigos de alerta e executa tentativas com versões de compatibilidade.
    """
    dxf_path = os.path.splitext(dwg_path)[0] + ".dxf"

    # Verifica se o LibreDWG está instalado no sistema operacional
    if shutil.which("dwg2dxf") is None:
        raise RuntimeError(
            "O utilitário 'dwg2dxf' (LibreDWG) não está instalado no servidor. "
            "Execute: sudo apt update && sudo apt install -y libredwg-tools"
        )

    # Tentativa 1: Conversão direta com substituição forçada
    cmd_padrao = ["dwg2dxf", "-y", "-o", dxf_path, dwg_path]
    try:
        subprocess.run(
            cmd_padrao,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=35
        )
        if os.path.exists(dxf_path) and os.path.getsize(dxf_path) > 100:
            return dxf_path
    except subprocess.TimeoutExpired:
        raise RuntimeError("Tempo limite de conversão excedido (DWG muito denso).")
    except Exception as e:
        pass

    # Tentativa 2: Fallback para padrão de intercâmbio R2000
    cmd_fallback = ["dwg2dxf", "-y", "-v2000", "-o", dxf_path, dwg_path]
    try:
        res = subprocess.run(
            cmd_fallback,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=35
        )
        if os.path.exists(dxf_path) and os.path.getsize(dxf_path) > 100:
            return dxf_path

        erro_log = res.stderr.decode("utf-8", errors="ignore")
        raise RuntimeError(f"Falha na conversão do arquivo DWG pelo LibreDWG: {erro_log[:200]}")
    except Exception as e:
        raise RuntimeError(f"Não foi possível converter o arquivo DWG: {str(e)}")


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


@app.post("/auditar-a1")
async def auditar_e_gerar_a1(file: UploadFile = File(...)):
    filename = file.filename or "desenho.dwg"
    ext = os.path.splitext(filename)[1].lower()
    base_name = os.path.splitext(filename)[0]

    if ext not in [".dwg", ".dxf"]:
        raise HTTPException(
            status_code=400,
            detail="Formato de arquivo incompatível. Envie um arquivo .dwg ou .dxf."
        )

    # 1. Grava o arquivo fisicamente no disco e fecha a stream
    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
        shutil.copyfileobj(file.file, tmp)
        input_path = tmp.name

    dxf_path = input_path
    converted_temporarily = False

    try:
        # 2. Conversão automática caso seja DWG
        if ext == ".dwg":
            dxf_path = converter_dwg_para_dxf(input_path)
            converted_temporarily = True

        # 3. Leitura e auditoria das entidades CAD
        doc = ezdxf.readfile(dxf_path)
        audit_result = executar_auditoria_completa(doc, filename)

        # 4. Geração da prancha de verificação ISO A1
        pdf_filename = f"Verificacao_A1_{base_name}.pdf"
        pdf_gen = A1VerificationPDFGenerator(output_dir=REPORTS_DIR)
        pdf_gen.generate(doc, audit_result, pdf_filename)

        audit_result["pdf_filename"] = pdf_filename
        return audit_result

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro no processamento da prancha: {str(e)}")
    finally:
        # 5. Limpeza de arquivos temporários do servidor
        if os.path.exists(input_path):
            try: os.remove(input_path)
            except: pass
        if converted_temporarily and os.path.exists(dxf_path):
            try: os.remove(dxf_path)
            except: pass


# Rota legada para compatibilidade com chamadas anteriores
@app.post("/auditar-a3")
async def auditar_a3_alias(file: UploadFile = File(...)):
    return await auditar_e_gerar_a1(file)


@app.get("/download-pdf/{filename}")
def download_pdf(filename: str):
    file_path = os.path.join(REPORTS_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Relatório A1 não encontrado.")
    return FileResponse(
        file_path,
        media_type="application/pdf",
        filename=filename
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
