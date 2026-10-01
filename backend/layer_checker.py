from typing import Dict, List, Any
import ezdxf

class LayerChecker:
    def __init__(self, allowed_layers: List[str] = None):
        self.prohibited_drawing_layers = {"0", "defpoints"}
        self.allowed_layers = [lay.upper() for lay in allowed_layers] if allowed_layers else None

    def _get_entity_coords(self, entity: Any) -> Dict[str, float]:
        """Extrai as coordenadas cartesianas reais do centroide de qualquer entidade CAD."""
        dxftype = entity.dxftype()
        try:
            # Círculos, furos de fixação e arcos
            if dxftype in ("CIRCLE", "ARC"):
                c = entity.dxf.center
                return {"x": round(float(c[0]), 2), "y": round(float(c[1]), 2)}

            # Polilinhas (contornos de chapas, dobras, perfis)
            if dxftype == "LWPOLYLINE":
                pts = entity.get_points("xy")
                if pts:
                    xs = [p[0] for p in pts]
                    ys = [p[1] for p in pts]
                    return {
                        "x": round(float(sum(xs) / len(xs)), 2),
                        "y": round(float(sum(ys) / len(ys)), 2)
                    }

            # Segmentos de linha
            if dxftype == "LINE":
                s = entity.dxf.start
                e = entity.dxf.end
                return {
                    "x": round(float((s[0] + e[0]) / 2.0), 2),
                    "y": round(float((s[1] + e[1]) / 2.0), 2)
                }

            # Polilinhas 2D/3D pesadas
            if dxftype == "POLYLINE":
                verts = list(entity.vertices)
                if verts:
                    xs = [v.dxf.location[0] for v in verts]
                    ys = [v.dxf.location[1] for v in verts]
                    return {
                        "x": round(float(sum(xs) / len(xs)), 2),
                        "y": round(float(sum(ys) / len(ys)), 2)
                    }

            # Textos, blocos e símbolos
            if hasattr(entity.dxf, "insert"):
                ins = entity.dxf.insert
                return {"x": round(float(ins[0]), 2), "y": round(float(ins[1]), 2)}

            # Defpoints de cotas
            if hasattr(entity.dxf, "defpoint"):
                dp = entity.dxf.defpoint
                return {"x": round(float(dp[0]), 2), "y": round(float(dp[1]), 2)}

        except Exception:
            pass

        return {"x": 0.0, "y": 0.0}

    def check(self, doc: ezdxf.document.Drawing) -> Dict[str, Any]:
        issues: List[Dict[str, Any]] = []
        total_entities = 0
        layer_0_count = 0
        defpoints_count = 0
        non_bylayer_count = 0

        spaces = [doc.modelspace()]
        for layout in doc.layouts:
            if layout.name.lower() != "model":
                spaces.append(layout)

        for space in spaces:
            space_name = getattr(space, "name", "Model")

            for entity in space:
                if entity.dxftype() == "VIEWPORT":
                    continue

                total_entities += 1
                layer_name = entity.dxf.get("layer", "0")
                layer_lower = layer_name.lower().strip()
                coords = self._get_entity_coords(entity)

                # 1. Objeto desenhado na Layer 0
                if layer_lower == "0":
                    layer_0_count += 1
                    issues.append({
                        "id": f"LAY-0-{layer_0_count}",
                        "tipo": "Objeto na Layer 0",
                        "entidade": entity.dxftype(),
                        "espaco": space_name,
                        "layer": layer_name,
                        "gravidade": "ALTA",
                        "descricao": f"Elemento '{entity.dxftype()}' desenhado na 'Layer 0'. Alocar na camada técnica correspondente.",
                        "posicao": coords
                    })

                # 2. Objeto desenhado na Defpoints
                elif layer_lower == "defpoints":
                    defpoints_count += 1
                    issues.append({
                        "id": f"LAY-DEF-{defpoints_count}",
                        "tipo": "Objeto na Defpoints",
                        "entidade": entity.dxftype(),
                        "espaco": space_name,
                        "layer": layer_name,
                        "gravidade": "CRITICA",
                        "descricao": f"Elemento '{entity.dxftype()}' na camada Defpoints (não será impresso na plotagem de fabricação).",
                        "posicao": coords
                    })

                # 3. Propriedades manuais fora de ByLayer
                entity_color = entity.dxf.get("color", 256)
                entity_linetype = entity.dxf.get("linetype", "BYLAYER").upper()

                if entity_color != 256 or entity_linetype != "BYLAYER":
                    non_bylayer_count += 1
                    issues.append({
                        "id": f"BYL-{non_bylayer_count}",
                        "tipo": "Propriedade Fora de ByLayer",
                        "entidade": entity.dxftype(),
                        "espaco": space_name,
                        "layer": layer_name,
                        "gravidade": "MEDIA",
                        "descricao": "Objeto com cor ou tipo de linha forçado manualmente em vez de ByLayer.",
                        "posicao": coords
                    })

        total_falhas = layer_0_count + defpoints_count + non_bylayer_count
        conformidade = (
            round(((total_entities - total_falhas) / total_entities) * 100, 1)
            if total_entities > 0 else 100.0
        )

        return {
            "modulo": "layer_checker",
            "total_entidades_analisadas": total_entities,
            "objetos_layer_0": layer_0_count,
            "objetos_defpoints": defpoints_count,
            "propriedades_fora_bylayer": non_bylayer_count,
            "conformidade_percentual": max(0.0, conformidade),
            "status": "REPROVADO" if (layer_0_count > 0 or defpoints_count > 0) else "APROVADO",
            "inconformidades": issues
        }
