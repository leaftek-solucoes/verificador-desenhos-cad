from typing import Dict, List, Any
import ezdxf

class LayerChecker:
    def __init__(self, allowed_layers: List[str] = None):
        """
        :param allowed_layers: Lista opcional de nomes de camadas homologadas pela empresa.
        """
        # Camadas reservadas do CAD que nunca devem conter peças de projeto
        self.prohibited_drawing_layers = {"0", "defpoints"}
        self.allowed_layers = [lay.upper() for lay in allowed_layers] if allowed_layers else None

    def _get_entity_coords(self, entity: Any) -> Dict[str, float]:
        """Extrai as coordenadas aproximadas da entidade para posicionar a nuvem de revisão."""
        # Se for linha
        if entity.dxftype() == "LINE":
            pt = entity.dxf.start
            return {"x": round(pt[0], 2), "y": round(pt[1], 2)}
        # Se for bloco ou texto
        if hasattr(entity.dxf, "insert"):
            pt = entity.dxf.insert
            return {"x": round(pt[0], 2), "y": round(pt[1], 2)}
        # Se for polilinha
        if entity.dxftype() in ("LWPOLYLINE", "POLYLINE"):
            try:
                pts = list(entity.points())
                if pts:
                    return {"x": round(pts[0][0], 2), "y": round(pts[0][1], 2)}
            except Exception:
                pass
        return {"x": 0.0, "y": 0.0}

    def check(self, doc: ezdxf.document.Drawing) -> Dict[str, Any]:
        """
        Audita todas as entidades do documento (Model e Layouts) procurando irregularidades de camadas.
        """
        issues: List[Dict[str, Any]] = []
        total_entities = 0
        layer_0_count = 0
        defpoints_count = 0
        non_bylayer_count = 0

        # Espaços a inspecionar
        spaces = [doc.modelspace()]
        for layout in doc.layouts:
            if layout.name.lower() != "model":
                spaces.append(layout)

        for space in spaces:
            space_name = getattr(space, "name", "Model")

            for entity in space:
                # Ignora Viewports do layout para não gerar falsos positivos
                if entity.dxftype() == "VIEWPORT":
                    continue

                total_entities += 1
                layer_name = entity.dxf.get("layer", "0")
                layer_lower = layer_name.lower().strip()
                coords = self._get_entity_coords(entity)

                # 1. Checagem de Layer 0
                if layer_lower == "0":
                    layer_0_count += 1
                    issues.append({
                        "id": f"LAY-0-{layer_0_count}",
                        "tipo": "Objeto na Layer 0",
                        "entidade": entity.dxftype(),
                        "espaco": space_name,
                        "layer": layer_name,
                        "gravidade": "ALTA",
                        "descricao": f"Entidade '{entity.dxftype()}' desenhada na 'Layer 0'. Deve ser alocada na camada técnica correspondente.",
                        "posicao": coords
                    })

                # 2. Checagem de Defpoints
                elif layer_lower == "defpoints":
                    defpoints_count += 1
                    issues.append({
                        "id": f"LAY-DEF-{defpoints_count}",
                        "tipo": "Objeto na Defpoints",
                        "entidade": entity.dxftype(),
                        "espaco": space_name,
                        "layer": layer_name,
                        "gravidade": "CRITICA",
                        "descricao": f"Entidade '{entity.dxftype()}' na camada 'Defpoints'. O objeto não será impresso nem aparecerá na plotagem.",
                        "posicao": coords
                    })

                # 3. Checagem de ByLayer (Cor fixa ou linetype forçado manualmente)
                # No padrão DXF: cor 256 = ByLayer, tipo de linha 'BYLAYER'
                entity_color = entity.dxf.get("color", 256)
                entity_linetype = entity.dxf.get("linetype", "BYLAYER").upper()

                if entity_color != 256 or entity_linetype != "BYLAYER":
                    non_bylayer_count += 1
                    detalhes = []
                    if entity_color != 256:
                        detalhes.append(f"Cor manual (índice {entity_color})")
                    if entity_linetype != "BYLAYER":
                        detalhes.append(f"Linetype manual ({entity_linetype})")

                    issues.append({
                        "id": f"BYL-{non_bylayer_count}",
                        "tipo": "Propriedade fora de ByLayer",
                        "entidade": entity.dxftype(),
                        "espaco": space_name,
                        "layer": layer_name,
                        "gravidade": "MEDIA",
                        "descricao": f"Objeto com {' e '.join(detalhes)} forçado em vez de herdar da camada.",
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