import re
from typing import Dict, List, Any
import ezdxf

class WeldChecker:
    """Valida especificações e símbolos de solda estrutural conforme AWS D1.1 / ABNT NBR 8800."""

    def __init__(self):
        # Tabela 19 NBR 8800: Dimensão mínima da perna da solda de filete (z_min) em função da chapa mais grossa (t)
        # t <= 6.35 mm -> z >= 3 mm
        # 6.35 < t <= 12.7 mm -> z >= 5 mm
        # 12.7 < t <= 19.0 mm -> z >= 6 mm
        # t > 19.0 mm -> z >= 8 mm
        self.weld_regex = re.compile(r"(\b[zZsS]\s*[:=]?\s*(\d+[\.,]?\d*)\b|\b(\d+)\s*mm\b)")

    def check(self, doc: ezdxf.document.Drawing) -> Dict[str, Any]:
        issues: List[Dict[str, Any]] = []
        weld_callouts = []
        all_texts = []

        target_layout = doc.modelspace()
        for lay in doc.layouts:
            if lay.name.lower() != "model":
                if sum(1 for e in lay if e.dxftype() != "VIEWPORT") > 10:
                    target_layout = lay
                    break

        for ent in target_layout.query("TEXT MTEXT LEADER MULTILEADER"):
            val = ""
            if ent.dxftype() == "TEXT":
                val = ent.dxf.text
            elif ent.dxftype() == "MTEXT":
                val = ent.text
            elif ent.dxftype() in ("LEADER", "MULTILEADER"):
                val = getattr(ent, "text", "") or ""

            pt = getattr(ent.dxf, "insert", (0, 0, 0))
            clean_txt = val.upper().strip()

            if any(k in clean_txt for k in ["SOLDA", "WELD", "AWS", "E70", "E60", "FILETE"]):
                weld_callouts.append({
                    "text": clean_txt,
                    "x": float(pt[0]),
                    "y": float(pt[1])
                })

        # Validação de perna de solda mínima
        issues_count = 0
        for wc in weld_callouts:
            # Procura dimensões declaradas de perna de solda (ex: 3mm, 5mm)
            match = self.weld_regex.search(wc["text"])
            if match:
                size_str = match.group(2) or match.group(3)
                try:
                    size_val = float(size_str.replace(",", "."))
                    # Soldas de filete estruturais não podem ter perna inferior a 3.0 mm (NBR 8800)
                    if size_val < 3.0:
                        issues_count += 1
                        issues.append({
                            "id": f"WELD-LEG-{issues_count}",
                            "tipo": "Perna de Solda Abaixo do Mínimo",
                            "gravidade": "CRITICA",
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
