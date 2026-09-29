from typing import Dict, List, Any
import ezdxf

class StandardChecker:
    def __init__(self):
        # Padrão ISO de pranchas em milímetros (tolerância de +/- 5 mm)
        self.standard_sheet_sizes = {
            "ISO A1": (841.0, 594.0),
            "ISO A2": (594.0, 420.0),
            "ISO A3": (420.0, 297.0),
            "ISO A0": (1189.0, 841.0)
        }

    def check(self, doc: ezdxf.document.Drawing) -> Dict[str, Any]:
        issues: List[Dict[str, Any]] = []
        layouts = [l for l in doc.layouts if l.name.lower() != "model"]

        unlocked_viewports = 0
        title_block_found = False
        total_layouts = len(layouts)

        # 1. Auditoria de Viewports destravadas no Paper Space
        for layout in layouts:
            viewports = layout.query("VIEWPORT")
            for vp in viewports:
                # Viewport com ID 1 é a viewport padrão do sistema da folha (ignora)
                if vp.dxf.get("id", 0) <= 1:
                    continue

                # Status bit 16384 (0x4000) indica Display Locked no AutoCAD DXF
                status_flag = vp.dxf.get("status_flag", 0)
                is_locked = bool(status_flag & 16384)

                if not is_locked:
                    unlocked_viewports += 1
                    center = vp.dxf.get("center", [0, 0])
                    issues.append({
                        "id": f"VP-UNLOCK-{unlocked_viewports}",
                        "tipo": "Viewport Destravada",
                        "espaco": layout.name,
                        "gravidade": "ALTA",
                        "descricao": f"Viewport no layout '{layout.name}' está com Display Locked = Não. Risco de alteração acidental de escala pelo desenhista.",
                        "posicao": {"x": round(center[0], 2), "y": round(center[1], 2)}
                    })

            # 2. Auditoria do Carimbo (Title Block) no Layout
            # Procura por blocos inseridos no canto inferior direito do Layout
            for insert in layout.query("INSERT"):
                block_name = insert.dxf.name.upper()
                if any(tag in block_name for tag in ["CARIMBO", "TITLE", "SELO", "LEGENDA", "FOLHA"]):
                    title_block_found = True
                    break

        if not title_block_found and total_layouts > 0:
            issues.append({
                "id": "STD-NO-TITLEBLOCK",
                "tipo": "Carimbo Não Identificado",
                "espaco": "Layouts",
                "gravidade": "CRITICA",
                "descricao": "Bloco padrão de carimbo/legenda não localizado nos layouts do projeto.",
                "posicao": {"x": 500.0, "y": 100.0}
            })

        total_falhas = unlocked_viewports + (0 if title_block_found or total_layouts == 0 else 1)
        conformidade = max(0.0, round(100.0 - (total_falhas * 20.0), 1))

        return {
            "modulo": "standard_checker",
            "total_layouts_analisados": total_layouts,
            "viewports_destravadas": unlocked_viewports,
            "carimbo_homologado": title_block_found or total_layouts == 0,
            "conformidade_percentual": conformidade,
            "status": "REPROVADO" if total_falhas > 0 else "APROVADO",
            "inconformidades": issues
        }