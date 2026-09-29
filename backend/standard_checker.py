from typing import Dict, List, Any
import ezdxf

class StandardChecker:
    def __init__(self):
        # Palavras-chave homologadas para carimbos e selos industriais
        self.title_block_keywords = [
            "CARIMBO", "TITLE", "SELO", "LEGENDA", "FOLHA",
            "FORMATO", "PRANCHA", "DRAFT", "VALE", "A1", "A2", "A3", "A0"
        ]

    def check(self, doc: ezdxf.document.Drawing) -> Dict[str, Any]:
        issues: List[Dict[str, Any]] = []
        layouts = [l for l in doc.layouts if l.name.lower() != "model"]

        unlocked_viewports = 0
        title_block_found = False
        total_layouts = len(layouts)

        # 1. Varredura nos layouts (Paper Space)
        for layout in layouts:
            for vp in layout.query("VIEWPORT"):
                if vp.dxf.get("id", 0) <= 1:
                    continue
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
                        "descricao": f"Viewport no layout '{layout.name}' com trava desativada.",
                        "posicao": {"x": round(center[0], 2), "y": round(center[1], 2)}
                    })

            for insert in layout.query("INSERT"):
                block_name = insert.dxf.name.upper()
                if any(kw in block_name for kw in self.title_block_keywords):
                    title_block_found = True
                    break

        # 2. Varredura alternativa no Model Space
        if not title_block_found:
            msp = doc.modelspace()
            for insert in msp.query("INSERT"):
                block_name = insert.dxf.name.upper()
                if any(kw in block_name for kw in self.title_block_keywords):
                    title_block_found = True
                    break

        if not title_block_found and total_layouts > 0:
            issues.append({
                "id": "STD-NO-TITLEBLOCK",
                "tipo": "Carimbo Não Identificado",
                "espaco": "Geral / Prancha",
                "gravidade": "CRITICA",
                "descricao": "Bloco padrão de carimbo/legenda homologado não localizado.",
                "posicao": {"x": 0.0, "y": 0.0}
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
