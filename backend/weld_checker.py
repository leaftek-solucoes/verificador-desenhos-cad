import re
from typing import Dict, List, Any
import ezdxf

from cad_utils import analysis_spaces, space_name

class WeldChecker:
    """Valida especificações e símbolos de solda estrutural conforme AWS D1.1 / ABNT NBR 8800."""

    def __init__(self):
        # Tabela 19 NBR 8800: Dimensão mínima da perna da solda de filete (z_min) em função da chapa mais grossa (t)
        # t <= 6.35 mm -> z >= 3 mm
        # 6.35 < t <= 12.7 mm -> z >= 5 mm
        # 12.7 < t <= 19.0 mm -> z >= 6 mm
        # t > 19.0 mm -> z >= 8 mm
        # Texto é comparado em maiúsculas: "z=4", "S 5", "FILETE 2MM", "2,5 mm"
        self.weld_regex = re.compile(r"\b[ZS]\s*[:=]?\s*(\d+(?:[\.,]\d+)?)\b|(\d+(?:[\.,]\d+)?)\s*MM\b", re.IGNORECASE)

    def check(self, doc: ezdxf.document.Drawing) -> Dict[str, Any]:
        issues: List[Dict[str, Any]] = []
        weld_callouts = []
        all_texts = []

        for space in analysis_spaces(doc):
            for ent in space.query("TEXT MTEXT MULTILEADER"):
                val = ""
                if ent.dxftype() == "TEXT":
                    val = ent.dxf.text
                elif ent.dxftype() == "MTEXT":
                    val = ent.plain_text()
                else:
                    try:
                        val = ent.get_mtext_content() or ""
                    except Exception:
                        val = ""

                pt = ent.dxf.get("insert", (0, 0, 0))
                clean_txt = val.upper().strip()

                if any(k in clean_txt for k in ["SOLDA", "WELD", "AWS", "E70", "E60", "FILETE"]):
                    weld_callouts.append({
                        "text": clean_txt,
                        "x": float(pt[0]),
                        "y": float(pt[1]),
                        "espaco": space_name(space)
                    })

        # Validação de perna de solda mínima
        issues_count = 0
        for wc in weld_callouts:
            # Procura dimensões declaradas de perna de solda (ex: 3mm, 5mm)
            match = self.weld_regex.search(wc["text"])
            if match:
                size_str = match.group(1) or match.group(2)
                try:
                    size_val = float(size_str.replace(",", "."))
                    # Soldas de filete estruturais não podem ter perna inferior a 3.0 mm (NBR 8800)
                    if size_val < 3.0:
                        issues_count += 1
                        issues.append({
                            "id": f"WELD-LEG-{issues_count}",
                            "tipo": "Perna de Solda Abaixo do Mínimo",
                            "gravidade": "CRITICA",
                            "espaco": wc["espaco"],
                            "descricao": f"Perna de solda especificada com {size_val:.1f} mm. O mínimo por norma é 3.0 mm.",
                            "posicao": {"x": round(wc["x"], 2), "y": round(wc["y"], 2)}
                        })
                except ValueError:
                    pass

        return {
            "modulo": "weld_checker",
            "chamadas_solda_identificadas": len(weld_callouts),
            "status": "REPROVADO" if issues else "APROVADO",
            "inconformidades": issues
        }
