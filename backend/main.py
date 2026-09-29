import os
import shutil
import tempfile
from typing import Dict, Any, List
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import ezdxf

from dimension_checker import DimensionChecker
from layer_checker import LayerChecker
from bom_checker import BOMChecker
from text_checker import TextChecker
from standard_checker import StandardChecker

app = FastAPI(
    title="LeafTek CAD Engine - QA/QC Checker",
    description="Motor de auditoria automatizada para desenhos técnicos DWG/DXF",
    version="1.0.1"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SEVERITY_WEIGHT = {
    "CRITICA": 4,
    "ALTA": 3,
    "MEDIA": 2,
    "BAIXA": 1
}

@app.get("/")
def health_check():
    return {
        "sistema": "LeafTek CAD QA/QC Engine",
        "status": "Online",
        "versao": "1.0.1"
    }

@app.post("/auditar")
async def auditar_desenho(file: UploadFile = File(...)) -> Dict[str, Any]:
    filename = file.filename or "desenho.dxf"
    ext = os.path.splitext(filename)[1].lower()

    if ext not in [".dxf", ".dwg"]:
        raise HTTPException(
            status_code=400,
            detail="Formato inválido. O sistema aceita apenas arquivos .dxf ou .dwg."
        )

    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    try:
        doc = ezdxf.readfile(tmp_path)

        # 1. Execução dos verificadores
        dim_res = DimensionChecker(tolerance_mm=1.0).check(doc)
        lay_res = LayerChecker().check(doc)
        bom_res = BOMChecker(tolerance_pct=5.0).check(doc)
        txt_res = TextChecker().check(doc)
        std_res = StandardChecker().check(doc)

        # 2. Consolidação de inconformidades
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

        # 3. Cálculo tolerante a falhas das notas percentuais
        scores = [
            dim_res.get("conformidade_percentual", 100.0),
            lay_res.get("conformidade_percentual", 100.0),
            bom_res.get("conformidade_percentual", 100.0),
            txt_res.get("conformidade_percentual", 100.0),
            std_res.get("conformidade_percentual", 100.0)
        ]
        score_geral = round(sum(scores) / len(scores), 1)

        # 4. Status final do projeto
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

    except ezdxf.DXFStructureError as e:
        raise HTTPException(
            status_code=422,
            detail=f"Arquivo DXF corrompido ou formato incompatível: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erro interno durante a análise do desenho: {str(e)}"
        )
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
