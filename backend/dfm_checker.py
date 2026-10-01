import math
from typing import Dict, List, Any, Tuple
import ezdxf

class DFMChecker:
    """Auditoria de Fabricabilidade (Design for Manufacturing) conforme ABNT NBR 8800 / AISC."""
    
    def __init__(self, min_edge_factor: float = 1.5, min_pitch_factor: float = 3.0):
        self.min_edge_factor = min_edge_factor    # Distância à borda: e >= 1.5 * d
        self.min_pitch_factor = min_pitch_factor  # Passo entre furos: p >= 3.0 * d

    def _extract_holes_and_boundaries(self, layout) -> Tuple[List[Dict[str, Any]], List[Any]]:
        """Extrai todos os furos cilíndricos e contornos de chapas do layout."""
        holes = []
        boundaries = []

        for entity in layout:
            dxftype = entity.dxftype()
            if dxftype == "VIEWPORT":
                continue

            # Furos (círculos de diâmetro padrão de parafusos: 5 mm a 60 mm)
            if dxftype == "CIRCLE":
                radius = float(entity.dxf.radius)
                diameter = radius * 2.0
                if 4.0 <= diameter <= 80.0:
                    center = entity.dxf.center
                    holes.append({
                        "x": float(center[0]),
                        "y": float(center[1]),
                        "radius": radius,
                        "diameter": diameter,
                        "entity": entity
                    })
            
            # Contornos de chapa (LWPOLYLINE fechadas ou linhas de contorno)
            elif dxftype == "LWPOLYLINE":
                pts = entity.get_points("xy")
                if len(pts) >= 3:
                    boundaries.append(pts)

        return holes, boundaries

    def _point_to_segment_distance(self, px: float, py: float, x1: float, y1: float, x2: float, y2: float) -> float:
        """Calcula a menor distância ortogonal de um ponto a um segmento de reta."""
        dx = x2 - x1
        dy = y2 - y1
        if dx == 0 and dy == 0:
            return math.hypot(px - x1, py - y1)

        t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
        proj_x = x1 + t * dx
        proj_y = y1 + t * dy
        return math.hypot(px - proj_x, py - proj_y)

    def check(self, doc: ezdxf.document.Drawing) -> Dict[str, Any]:
        issues: List[Dict[str, Any]] = []
        
        target_layout = doc.modelspace()
        for lay in doc.layouts:
            if lay.name.lower() != "model":
                if sum(1 for e in lay if e.dxftype() != "VIEWPORT") > 10:
                    target_layout = lay
                    break

        holes, boundaries = self._extract_holes_and_boundaries(target_layout)
        total_holes = len(holes)
        issues_count = 0

        # 1. VERIFICAÇÃO DE ESPAÇAMENTO ENTRE FUROS ADJACENTES (PASSO p >= 3.0 * d)
        for i in range(len(holes)):
            for j in range(i + 1, len(holes)):
                h1 = holes[i]
                h2 = holes[j]
                center_dist = math.hypot(h1["x"] - h2["x"], h1["y"] - h2["y"])
                
                # Considera apenas furos do mesmo conjunto (até 250 mm de distância)
                if center_dist < 250.0:
                    d_ref = max(h1["diameter"], h2["diameter"])
                    min_allowed_pitch = self.min_pitch_factor * d_ref
                    
                    if center_dist < min_allowed_pitch:
                        issues_count += 1
                        issues.append({
                            "id": f"DFM-PITCH-{issues_count}",
                            "tipo": "Espaçamento Insuficiente entre Furos",
                            "gravidade": "CRITICA",
                            "descricao": (
                                f"Distância entre centros ({center_dist:.1f} mm) inferior ao mínimo de norma "
                                f"NBR 8800 (p >= 3d = {min_allowed_pitch:.1f} mm para furo Ø{d_ref:.1f} mm)."
                            ),
                            "posicao": {
                                "x": round((h1["x"] + h2["x"]) / 2.0, 2),
                                "y": round((h1["y"] + h2["y"]) / 2.0, 2)
                            }
                        })

        # 2. VERIFICAÇÃO DE DISTÂNCIA DO FURO À BORDA DA CHAPA (e >= 1.5 * d)
        for h in holes:
            min_edge_dist = float("inf")
            for poly in boundaries:
                n = len(poly)
                for k in range(n):
                    x1, y1 = poly[k]
                    x2, y2 = poly[(k + 1) % n]
                    dist = self._point_to_segment_distance(h["x"], h["y"], x1, y1, x2, y2)
                    if dist < min_edge_dist:
                        min_edge_dist = dist

            if min_edge_dist != float("inf"):
                req_edge = self.min_edge_factor * h["diameter"]
                if min_edge_dist < req_edge:
                    issues_count += 1
                    issues.append({
                        "id": f"DFM-EDGE-{issues_count}",
                        "tipo": "Furo Próximo da Borda da Chapa",
                        "gravidade": "ALTA",
                        "descricao": (
                            f"Furo Ø{h['diameter']:.1f} mm a {min_edge_dist:.1f} mm da borda. "
                            f"Mínimo por norma NBR 8800: e >= 1.5d ({req_edge:.1f} mm) para evitar rasgamento."
                        ),
                        "posicao": {"x": round(h["x"], 2), "y": round(h["y"], 2)}
                    })

        return {
            "modulo": "dfm_checker",
            "total_furos_analisados": total_holes,
            "status": "REPROVADO" if issues else "APROVADO",
            "inconformidades": issues
        }
