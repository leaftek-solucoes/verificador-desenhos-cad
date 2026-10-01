import re
from typing import Dict, List, Any
import ezdxf

class StandardNotesChecker:
    """Valida a presença de notas obrigatórias de caldeiraria e estruturas metálicas."""

    MANDATORY_RULES = [
        {
            "id": "NOTE-UNID",
            "tipo": "Unidade de Medida",
            "regex": r"\b(MIL[IÍ]METROS?|MM)\b",
            "gravidade": "MEDIA",
            "descricao": "Nota de unidade de fabricação ausente ('DIMENSÕES EM MILÍMETROS')."
        },
        {
            "id": "NOTE-MAT",
            "tipo": "Especificação do Aço",
            "regex": r"\b(ASTM\s*A-?36|ASTM\s*A-?572|SAC\s*350|USI\s*CIVIL|AÇO\s*ESTRUTURAL)\b",
            "gravidade": "ALTA",
            "descricao": "Especificação do material estrutural (ex: ASTM A36 / A572) não declarada nas notas."
        },
        {
            "id": "NOTE-WELD",
            "tipo": "Consumível de Soldagem",
            "regex": r"\b(AWS\s*D1\.1|AWS\s*A5\.\d|E-?7018|E-?70S|E-?71T)\b",
            "gravidade": "MEDIA",
            "descricao": "Especificação de consumíveis ou norma de soldagem (AWS D1.1 / E7018) ausente."
        },
        {
            "id": "NOTE-BURR",
            "tipo": "Rebarbação e Arestas",
            "regex": r"\b(REBARBA|CANTOS?\s*VIVOS?|ESMERILH|QUEBRAR\s*CANTOS?)\b",
            "gravidade": "BAIXA",
            "descricao": "Nota técnica de acabamento ausente ('REMOVER TODAS AS REBARBAS E CANTOS VIVOS')."
        },
        {
            "id": "NOTE-TOL",
            "tipo": "Tolerâncias Gerais",
            "regex": r"\b(TOLER[AÂ]NCIA|ISO\s*2768|NBR\s*8800)\b",
            "gravidade": "BAIXA",
            "descricao": "Indicação de tolerâncias gerais lineares e angulares não identificada."
        }
    ]

    def check(self, doc: ezdxf.document.Drawing) -> Dict[str, Any]:
        issues: List[Dict[str, Any]] = []
        all_text = ""

        # Varre model space e layouts
        for entity in doc.modelspace().query("TEXT MTEXT"):
            t = entity.dxf.text if entity.dxftype() == "TEXT" else entity.text
            all_text += " " + t.upper()

        for lay in doc.layouts:
            if lay.name.lower() != "model":
                for entity in lay.query("TEXT MTEXT"):
                    t = entity.dxf.text if entity.dxftype() == "TEXT" else entity.text
                    all_text += " " + t.upper()

        # Limpeza de caracteres de controle de AutoCAD
        all_text = re.sub(r"\\[A-Z0-9]+;?", " ", all_text)

        reprovacoes = 0
        for rule in self.MANDATORY_RULES:
            if not re.search(rule["regex"], all_text, re.IGNORECASE):
                reprovacoes += 1
                issues.append({
                    "id": rule["id"],
                    "tipo": rule["tipo"],
                    "gravidade": rule["gravidade"],
                    "descricao": rule["descricao"],
                    "posicao": {"x": 0.0, "y": 0.0}
                })

        conformidade = round(((len(self.MANDATORY_RULES) - reprovacoes) / len(self.MANDATORY_RULES)) * 100, 1)

        return {
            "modulo": "notes_checker",
            "notas_verificadas": len(self.MANDATORY_RULES),
            "notas_em_falta": reprovacoes,
            "conformidade_percentual": conformidade,
            "status": "REPROVADO" if any(e["gravidade"] == "ALTA" for e in issues) else ("APROVADO COM RESSALVA" if issues else "APROVADO"),
            "inconformidades": issues
        }
