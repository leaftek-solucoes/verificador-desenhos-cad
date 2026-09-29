import re
from typing import Dict, List, Any
import ezdxf
from ezdxf.entities.dimension import Dimension

class DimensionChecker:
    def __init__(self, tolerance_mm: float = 1.0):
        self.tolerance_mm = tolerance_mm

    def _clean_dimension_text(self, raw_text: str) -> str:
        if not raw_text:
            return ""
        cleaned = re.sub(r"\\[A-Za-z0-9]+;", "", raw_text)
        cleaned = cleaned.replace(r"\P", " ").replace("{", "").replace("}", "").strip()
        return cleaned

    def _extract_numeric_value(self, text: str) -> float | None:
        match = re.search(r"[-+]?\d+(?:[.,]\d+)?", text)
        if match:
            try:
                return float(match.group(0).replace(",", "."))
            except ValueError:
                return None
        return None

    def _get_dimension_coordinates(self, dim: Dimension) -> Dict[str, float]:
        if hasattr(dim.dxf, "text_midpoint") and dim.dxf.text_midpoint:
            pt = dim.dxf.text_midpoint
            return {"x": round(pt[0], 2), "y": round(pt[1], 2)}
        if hasattr(dim.dxf, "defpoint") and dim.dxf.defpoint:
            pt = dim.dxf.defpoint
            return {"x": round(pt[0], 2), "y": round(pt[1], 2)}
        return {"x": 0.0, "y": 0.0}

    def check(self, doc: ezdxf.document.Drawing) -> Dict[str, Any]:
        issues: List[Dict[str, Any]] = []
        total_dimensions = 0
        overridden_count = 0

        spaces = [doc.modelspace()]
        for layout in doc.layouts:
            if layout.name.lower() != "model":
                spaces.append(layout)

        for space in spaces:
            space_name = getattr(space, "name", "Model")
            for dim in space.query("DIMENSION"):
                total_dimensions += 1
                raw_override = dim.dxf.get("text", "").strip()
                cleaned_override = self._clean_dimension_text(raw_override)

                has_override = bool(cleaned_override and "<>" not in raw_override)

                if has_override:
                    overridden_count += 1
                    coords = self._get_dimension_coordinates(dim)
                    try:
                        actual_measurement = dim.get_measurement()
                    except Exception:
                        actual_measurement = 0.0

                    stated_value = self._extract_numeric_value(cleaned_override)
                    delta = abs(stated_value - actual_measurement) if stated_value is not None else 0.0
                    is_fraudulent = stated_value is not None and delta > self.tolerance_mm

                    issues.append({
                        "id": f"DIM-{total_dimensions}",
                        "tipo": "Cota Sobrescrita (Override)",
                        "espaco": space_name,
                        "layer": dim.dxf.layer,
                        "texto_exibido": cleaned_override,
                        "medida_real": round(actual_measurement, 2),
                        "diferenca_mm": round(delta, 2),
                        "gravidade": "CRITICA" if is_fraudulent else "MEDIA",
                        "posicao": coords
                    })

        return {
            "modulo": "dimension_checker",
            "total_cotas_analisadas": total_dimensions,
            "cotas_adulteradas": overridden_count,
            "status": "REPROVADO" if overridden_count > 0 else "APROVADO",
            "inconformidades": issues
        }