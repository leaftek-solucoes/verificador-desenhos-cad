import math
from typing import Dict, List, Any, Tuple
import ezdxf

from cad_utils import analysis_spaces, space_name

class DFMChecker:
    """Auditoria de Fabricabilidade (Design for Manufacturing) conforme ABNT NBR 8800 / AISC."""
    
    def __init__(self, min_edge_factor: float = 1.5, min_pitch_factor: float = 3.0):
        self.min_edge_factor = min_edge_factor    # Distância à borda: e >= 1.5 * d
        self.min_pitch_factor = min_pitch_factor  # Passo entre furos: p >= 3.0 * d

    def _extract_holes_and_boundaries(self, layout) -> Tuple[List[Dict[str, Any]], List[Any]]:
        """Extrai furos cilíndricos e contornos fechados de chapas do layout."""
        circles = []
        boundaries = []
        text_pts = []

        for entity in layout:
            dxftype = entity.dxftype()
            if dxftype == "VIEWPORT":
                continue

            # Furos (círculos de diâmetro compatível com parafusos)
            if dxftype == "CIRCLE":
                radius = float(entity.dxf.radius)
                diameter = radius * 2.0
                if 4.0 <= diameter <= 80.0:
                    center = entity.dxf.center
                    circles.append({
                        "x": float(center[0]),
                        "y": float(center[1]),
                        "radius": radius,
                        "diameter": diameter,
                        "entity": entity
                    })

            # Contornos de chapa: somente LWPOLYLINE fechada
            elif dxftype == "LWPOLYLINE":
                pts = [tuple(p) for p in entity.get_points("xy")]
                if len(pts) >= 3 and (entity.closed or pts[0] == pts[-1]):
                    boundaries.append(pts)

            elif dxftype in ("TEXT", "MTEXT"):
                ins = entity.dxf.get("insert")
                if ins is not None:
                    text_pts.append((float(ins[0]), float(ins[1])))

        # Balões de posição (círculo com texto dentro) não são furos
        circles = [
            c for c in circles
            if not any(math.hypot(tx - c["x"], ty - c["y"]) < c["radius"] for tx, ty in text_pts)
        ]

        # Círculos concêntricos (arruela, cabeça do parafuso): mantém só o menor como furo
        circles.sort(key=lambda c: c["radius"])
        holes: List[Dict[str, Any]] = []
        for c in circles:
            if not any(math.hypot(c["x"] - h["x"], c["y"] - h["y"]) < 0.01 for h in holes):
                holes.append(c)

        return holes, boundaries

    @staticmethod
    def _point_in_polygon(px: float, py: float, poly: List[Tuple[float, float]]) -> bool:
        inside = False
        n = len(poly)
        for k in range(n):
            x1, y1 = poly[k]
            x2, y2 = poly[(k + 1) % n]
            if (y1 > py) != (y2 > py):
                x_cross = x1 + (py - y1) * (x2 - x1) / (y2 - y1)
                if px < x_cross:
                    inside = not inside
        return inside

    @staticmethod
    def _polygon_area(poly: List[Tuple[float, float]]) -> float:
        n = len(poly)
        return abs(sum(poly[k][0] * poly[(k + 1) % n][1] - poly[(k + 1) % n][0] * poly[k][1] for k in range(n))) / 2.0

    def _containing_plate(self, h: Dict[str, Any], boundaries: List[Any]) -> int:
        """Índice do menor contorno fechado que contém o furo (-1 se nenhum)."""
        best, best_area = -1, float("inf")
        for idx, poly in enumerate(boundaries):
            if self._point_in_polygon(h["x"], h["y"], poly):
                area = self._polygon_area(poly)
                if area < best_area:
                    best, best_area = idx, area
        return best

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
        total_holes = 0
        issues_count = 0

        for space in analysis_spaces(doc):
            espaco = space_name(space)
            holes, boundaries = self._extract_holes_and_boundaries(space)
            total_holes += len(holes)
            for h in holes:
                h["plate"] = self._containing_plate(h, boundaries)

            # 1. ESPAÇAMENTO ENTRE FUROS DA MESMA CHAPA (PASSO p >= 3.0 * d)
            for i in range(len(holes)):
                for j in range(i + 1, len(holes)):
                    h1 = holes[i]
                    h2 = holes[j]
                    if h1["plate"] != h2["plate"]:
                        continue
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
                                "espaco": espaco,
                                "descricao": (
                                    f"Distância entre centros ({center_dist:.1f} mm) inferior ao mínimo de norma "
                                    f"NBR 8800 (p >= 3d = {min_allowed_pitch:.1f} mm para furo Ø{d_ref:.1f} mm)."
                                ),
                                "posicao": {
                                    "x": round((h1["x"] + h2["x"]) / 2.0, 2),
                                    "y": round((h1["y"] + h2["y"]) / 2.0, 2)
                                }
                            })

            # 2. DISTÂNCIA DO FURO À BORDA DA CHAPA QUE O CONTÉM (e >= 1.5 * d)
            for h in holes:
                if h["plate"] < 0:
                    continue
                poly = boundaries[h["plate"]]
                n = len(poly)
                min_edge_dist = min(
                    self._point_to_segment_distance(h["x"], h["y"], *poly[k], *poly[(k + 1) % n])
                    for k in range(n)
                )
                req_edge = self.min_edge_factor * h["diameter"]
                if min_edge_dist < req_edge:
                    issues_count += 1
                    issues.append({
                        "id": f"DFM-EDGE-{issues_count}",
                        "tipo": "Furo Próximo da Borda da Chapa",
                        "gravidade": "ALTA",
                        "espaco": espaco,
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
