"""Funções compartilhadas pelos módulos de verificação e pelo gerador do PDF."""
from typing import List, Optional, Tuple

import ezdxf


def primary_layout(doc: ezdxf.document.Drawing):
    """Layout renderizado no PDF: primeiro Paper Space com conteúdo, senão o Model Space."""
    for lay in doc.layouts:
        if lay.name.lower() != "model":
            if sum(1 for e in lay if e.dxftype() != "VIEWPORT") > 10:
                return lay
    return doc.modelspace()


def analysis_spaces(doc: ezdxf.document.Drawing) -> List:
    """Model Space + layouts de papel. Cada espaço é analisado com suas próprias coordenadas."""
    spaces = [doc.modelspace()]
    spaces += [lay for lay in doc.layouts if lay.name.lower() != "model"]
    return spaces


def space_name(space) -> str:
    return getattr(space, "name", "Model") or "Model"


def to_layout_coords(doc: ezdxf.document.Drawing, layout, espaco: Optional[str],
                     x: float, y: float) -> Optional[Tuple[float, float]]:
    """Converte a posição de um apontamento para as coordenadas do layout renderizado.

    Retorna None quando o ponto não aparece nesse layout (outro layout de papel, ou ponto
    do Model Space fora de todas as viewports), para não marcar o PDF no lugar errado.
    """
    target = space_name(layout)
    if espaco is None or espaco == target:
        return x, y
    if espaco != "Model" or target == "Model":
        return None
    for vp in layout.query("VIEWPORT"):
        if vp.dxf.get("id", 0) == 1 or vp.dxf.get("status", 1) <= 0:
            continue  # viewport geral do papel ou desligada
        try:
            x0, y0, x1, y1 = vp.get_modelspace_limits()
            if x0 <= x <= x1 and y0 <= y <= y1:
                p = vp.get_transformation_matrix().transform((x, y, 0))
                return float(p[0]), float(p[1])
        except Exception:
            continue
    return None
