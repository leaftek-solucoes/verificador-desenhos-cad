import re
from typing import Dict, List, Any
import ezdxf

class BOMChecker:
    def __init__(self, tolerance_pct: float = 5.0):
        """
        :param tolerance_pct: Divergência percentual máxima tolerada entre peso calculado e informado.
        """
        self.steel_density_kg_m3 = 7850.0  # Densidade padrão do aço estrutural
        self.tolerance_pct = tolerance_pct

    def _extract_plate_dimensions(self, desc: str) -> tuple[float, float, float] | None:
        """
        Extrai espessura, largura e comprimento de designações de chapa.
        Exemplos: 'PL 12.5 x 200 x 350', '# 1/2" x 200 x 300', 'CH 16 x 150 x 200'
        """
        desc_clean = desc.upper().replace(",", ".").replace('"', "")
        match = re.search(r"(?:PL|CH|#)\s*([0-9.]+)\s*[X*]\s*([0-9.]+)\s*[X*]\s*([0-9.]+)", desc_clean)
        if match:
            try:
                t = float(match.group(1)) # mm
                w = float(match.group(2)) # mm
                l = float(match.group(3)) # mm
                return (t, w, l)
            except ValueError:
                return None
        return None

    def _calculate_plate_weight(self, t_mm: float, w_mm: float, l_mm: float) -> float:
        """Calcula o peso teórico de uma chapa de aço em kg."""
        vol_m3 = (t_mm / 1000.0) * (w_mm / 1000.0) * (l_mm / 1000.0)
        return vol_m3 * self.steel_density_kg_m3

    def check(self, doc: ezdxf.document.Drawing) -> Dict[str, Any]:
        issues: List[Dict[str, Any]] = []
        total_items_bom = 0
        divergent_weights_count = 0

        # Varrer textos e tabelas procurando linhas de lista de material
        spaces = [doc.modelspace()]
        for layout in doc.layouts:
            if layout.name.lower() != "model":
                spaces.append(layout)

        for space in spaces:
            space_name = getattr(space, "name", "Model")
            
            # 1. Varredura por entidades ACAD_TABLE (Tabelas nativas de prancha)
            for table in space.query("ACAD_TABLE"):
                try:
                    for row_idx in range(table.nrows):
                        for col_idx in range(table.ncols):
                            cell_text = table.get_cell_text(row_idx, col_idx).strip()
                            dims = self._extract_plate_dimensions(cell_text)
                            if dims:
                                total_items_bom += 1
                                t, w, l = dims
                                peso_teorico = self._calculate_plate_weight(t, w, l)

                                # Tenta buscar peso indicado na célula vizinha
                                if col_idx + 1 < table.ncols:
                                    next_cell = table.get_cell_text(row_idx, col_idx + 1)
                                    match_peso = re.search(r"[-+]?\d+(?:[.,]\d+)?", next_cell)
                                    if match_peso:
                                        peso_informado = float(match_peso.group(0).replace(",", "."))
                                        erro_pct = abs(peso_informado - peso_teorico) / (peso_teorico or 1) * 100

                                        if erro_pct > self.tolerance_pct:
                                            divergent_weights_count += 1
                                            issues.append({
                                                "id": f"BOM-TAB-{total_items_bom}",
                                                "tipo": "Erro de Peso Teórico na BOM",
                                                "espaco": space_name,
                                                "item": cell_text,
                                                "peso_declarado_kg": round(peso_informado, 2),
                                                "peso_calculado_kg": round(peso_teorico, 2),
                                                "desvio_percentual": round(erro_pct, 1),
                                                "gravidade": "CRITICA",
                                                "descricao": f"Chapa '{cell_text}': peso informado de {peso_informado:.1f} kg diverge do cálculo teórico de {peso_teorico:.1f} kg (desvio de {erro_pct:.1f}%).",
                                                "posicao": {"x": round(table.dxf.insert[0], 2), "y": round(table.dxf.insert[1], 2)}
                                            })
                except Exception:
                    pass

            # 2. Varredura por textos soltos MText/Text contendo chapas com peso declarado
            for txt in space.query("TEXT MTEXT"):
                raw = txt.dxf.text if txt.dxftype() == "TEXT" else txt.text
                if not raw:
                    continue
                dims = self._extract_plate_dimensions(raw)
                if dims:
                    # Procura se há menção a "kg" na mesma linha
                    match_kg = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:KG|kg)", raw)
                    if match_kg:
                        total_items_bom += 1
                        t, w, l = dims
                        peso_teorico = self._calculate_plate_weight(t, w, l)
                        peso_declarado = float(match_kg.group(1).replace(",", "."))
                        erro_pct = abs(peso_declarado - peso_teorico) / (peso_teorico or 1) * 100

                        if erro_pct > self.tolerance_pct:
                            divergent_weights_count += 1
                            pt = getattr(txt.dxf, "insert", [0, 0])
                            issues.append({
                                "id": f"BOM-TXT-{total_items_bom}",
                                "tipo": "Erro de Peso na Anotação",
                                "espaco": space_name,
                                "item": raw.strip(),
                                "peso_declarado_kg": round(peso_declarado, 2),
                                "peso_calculado_kg": round(peso_teorico, 2),
                                "desvio_percentual": round(erro_pct, 1),
                                "gravidade": "ALTA",
                                "descricao": f"Elemento '{raw.strip()}': peso indicado de {peso_declarado:.1f} kg diverge do peso real de {peso_teorico:.1f} kg.",
                                "posicao": {"x": round(pt[0], 2), "y": round(pt[1], 2)}
                            })

        conformidade = (
            round(((total_items_bom - divergent_weights_count) / total_items_bom) * 100, 1)
            if total_items_bom > 0 else 100.0
        )

        return {
            "modulo": "bom_checker",
            "itens_bom_analisados": total_items_bom,
            "pesos_divergentes": divergent_weights_count,
            "conformidade_percentual": conformidade,
            "status": "REPROVADO" if divergent_weights_count > 0 else "APROVADO",
            "inconformidades": issues
        }