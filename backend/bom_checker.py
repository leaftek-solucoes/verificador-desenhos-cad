import re
from typing import Dict, List, Any, Optional
import ezdxf

from cad_utils import primary_layout, analysis_spaces, space_name

NUM_RE = re.compile(r"\d{1,3}(?:\.\d{3})+,\d+|\d+[\.,]\d+|\d+")
# Chapa: "CH 6,35x200x300", "CHAPA #9,5 X 100 X 150"
PLATE_RE = re.compile(
    r"\bCH(?:APA)?\.?\s*#?\s*(\d+(?:[.,]\d+)?)\s*[xX×]\s*(\d+(?:[.,]\d+)?)\s*[xX×]\s*(\d+(?:[.,]\d+)?)",
    re.IGNORECASE,
)


class BOMChecker:
    def __init__(self, steel_density: float = 7850.0, tolerance_kg: float = 0.15, row_tolerance_pct: float = 1.0):
        # Densidade do aço em kg/m³ e tolerância para arredondamentos
        self.steel_density = steel_density
        self.tolerance_kg = tolerance_kg
        self.row_tolerance_pct = row_tolerance_pct

    def _extract_all_texts(self, layout) -> List[Dict[str, Any]]:
        """Extrai todos os textos e MTexts do espaço com suas coordenadas."""
        texts = []
        for ent in layout.query("TEXT MTEXT"):
            val = ""
            if ent.dxftype() == "TEXT":
                val = ent.dxf.text
            elif ent.dxftype() == "MTEXT":
                val = ent.plain_text()

            # Limpa formatações internas de AutoCAD (\P, \A1, etc.)
            clean_val = re.sub(r"\\[A-Za-z0-9]+;?", " ", val).strip()
            clean_val = clean_val.replace("\\P", " ").strip()

            pt = getattr(ent.dxf, "insert", (0, 0, 0))
            if clean_val:
                texts.append({
                    "text": clean_val,
                    "x": float(pt[0]),
                    "y": float(pt[1]),
                    "entity": ent
                })
        return texts

    def _parse_float(self, text: str) -> float:
        """Converte '12,5', '12.5' e '1.234,56' para float."""
        match = NUM_RE.search(text)
        if not match:
            return 0.0
        s = match.group(0)
        if "." in s and "," in s:
            s = s.replace(".", "")
        return float(s.replace(",", "."))

    @staticmethod
    def _group_rows(texts: List[Dict[str, Any]], tol: float = 5.0) -> Dict[float, List[Dict[str, Any]]]:
        rows: Dict[float, List[Dict[str, Any]]] = {}
        for t in texts:
            key = next((ry for ry in rows if abs(t["y"] - ry) < tol), None)
            rows.setdefault(t["y"] if key is None else key, []).append(t)
        for items in rows.values():
            items.sort(key=lambda it: it["x"])
        return rows

    def _check_texts(self, texts: List[Dict[str, Any]], espaco: str) -> Optional[Dict[str, Any]]:
        issues: List[Dict[str, Any]] = []

        # 1. Localiza o cabeçalho da Lista de Material e o Peso Total declarado
        # Células de título de coluna "QTD" (a linha delas é o cabeçalho da tabela)
        qtd_cells = [t for t in texts if re.match(r"^\s*(QTD|QTDE|QUANT)", t["text"].upper())]

        bom_header = None
        peso_total_decl = None
        for t in texts:
            txt_upper = t["text"].upper()
            if "LISTA DE MATERIA" in txt_upper:
                bom_header = t
            # Ignora "PESO TOTAL" usado como título de coluna na linha do cabeçalho
            if "PESO TOTAL" in txt_upper and not any(abs(t["y"] - q["y"]) < 5.0 for q in qtd_cells):
                if peso_total_decl is None or NUM_RE.search(t["text"]):
                    peso_total_decl = t

        if not bom_header and not peso_total_decl:
            return None

        peso_total_pos = {"x": 0.0, "y": 0.0}
        peso_total_valor = 0.0
        if peso_total_decl:
            peso_total_pos = {"x": peso_total_decl["x"], "y": peso_total_decl["y"]}
            peso_total_valor = self._parse_float(peso_total_decl["text"])
            if peso_total_valor == 0.0:
                # Valor em célula separada, à direita do rótulo "PESO TOTAL"
                vizinhos = sorted(
                    (t for t in texts
                     if abs(t["y"] - peso_total_decl["y"]) < 5.0 and t["x"] > peso_total_decl["x"]
                     and self._parse_float(t["text"]) > 0.0),
                    key=lambda t: t["x"],
                )
                if vizinhos:
                    peso_total_valor = self._parse_float(vizinhos[0]["text"])
                    peso_total_pos = {"x": vizinhos[0]["x"], "y": vizinhos[0]["y"]}

        # 2. Região da tabela em torno do peso total / cabeçalho
        ref = peso_total_decl or bom_header
        table_texts = [
            t for t in texts
            if abs(t["x"] - ref["x"]) < 350.0 and abs(t["y"] - ref["y"]) < 300.0
        ]
        rows_by_y = self._group_rows(table_texts)

        # Linha de títulos das colunas (POS / QTD / PESO ...)
        header_y = None
        qtd_x = None
        for y, items in rows_by_y.items():
            hit = next((it for it in items if it in qtd_cells), None)
            if hit:
                header_y, qtd_x = y, hit["x"]
                break

        soma_pesos_calculada = 0.0
        linhas_processadas = 0
        issues_count = 0

        for y_coord, row_items in rows_by_y.items():
            row_str = " | ".join(it["text"] for it in row_items).upper()

            if y_coord == header_y or "PESO TOTAL" in row_str or "LISTA DE MATERIA" in row_str:
                continue
            # Com cabeçalho e peso total identificados, só considera as linhas entre os dois
            # (a tabela pode crescer para cima ou para baixo)
            if header_y is not None and peso_total_decl:
                lo, hi = sorted((header_y, peso_total_decl["y"]))
                if not (lo < y_coord < hi):
                    continue

            nums = [(self._parse_float(it["text"]), it) for it in row_items]
            nums = [n for n in nums if n[0] > 0.0]
            if len(nums) < 2:
                continue

            # A última coluna numérica é tratada como o peso total da linha
            peso_val, peso_item = nums[-1]
            if not (0.0 < peso_val < 5000.0):
                continue
            soma_pesos_calculada += peso_val
            linhas_processadas += 1

            # 3. Conferência do peso de chapas pela geometria (t x L x C x densidade)
            plate = PLATE_RE.search(row_str)
            if plate and qtd_x is not None:
                qtd_cell = min(row_items, key=lambda it: abs(it["x"] - qtd_x))
                qtd = self._parse_float(qtd_cell["text"])
                if abs(qtd_cell["x"] - qtd_x) > 25.0 or qtd <= 0:
                    continue
                t, w, c = (float(v.replace(",", ".")) for v in plate.groups())
                peso_unit = t * w * c * 1e-9 * self.steel_density
                esperado = peso_unit * qtd
                tol = max(self.tolerance_kg, esperado * self.row_tolerance_pct / 100.0)
                if abs(peso_val - esperado) > tol:
                    issues_count += 1
                    issues.append({
                        "id": f"BOM-ITEM-{issues_count}",
                        "tipo": "Peso de Item Divergente",
                        "gravidade": "ALTA",
                        "espaco": espaco,
                        "descricao": (
                            f"Item '{plate.group(0)}' (qtd {qtd:g}): declarado {peso_val:.2f} kg, "
                            f"calculado {esperado:.2f} kg ({peso_unit:.2f} kg/un a {self.steel_density:.0f} kg/m³)."
                        ),
                        "posicao": {"x": round(peso_item["x"], 2), "y": round(peso_item["y"], 2)}
                    })

        # 4. Auditoria de Divergência do Peso Total
        if peso_total_valor > 0.0 and soma_pesos_calculada > 0.0:
            diferenca = abs(peso_total_valor - soma_pesos_calculada)
            if diferenca > self.tolerance_kg:
                issues.append({
                    "id": "BOM-PESO-01",
                    "tipo": "Erro na Soma da Lista de Materiais",
                    "gravidade": "CRITICA",
                    "espaco": espaco,
                    "descricao": (
                        f"Divergência no Peso Total: Declarado = {peso_total_valor:.2f} kg, "
                        f"Soma calculada dos itens = {soma_pesos_calculada:.2f} kg "
                        f"(Diferença: {diferenca:.2f} kg)."
                    ),
                    "posicao": peso_total_pos
                })

        return {
            "peso_total_declarado_kg": peso_total_valor,
            "peso_total_calculado_kg": round(soma_pesos_calculada, 2),
            "itens_auditados": linhas_processadas,
            "issues": issues,
        }

    def check(self, doc: ezdxf.document.Drawing) -> Dict[str, Any]:
        # Procura a lista primeiro no layout principal (folha), depois nos demais espaços
        principal = primary_layout(doc)
        spaces = [principal] + [s for s in analysis_spaces(doc) if space_name(s) != space_name(principal)]

        res = None
        for space in spaces:
            res = self._check_texts(self._extract_all_texts(space), space_name(space))
            if res:
                break

        if not res:
            return {
                "modulo": "bom_checker",
                "status": "APROVADO",
                "mensagem": "Nenhuma Lista de Material identificada na folha.",
                "inconformidades": []
            }

        issues = res["issues"]
        return {
            "modulo": "bom_checker",
            "peso_total_declarado_kg": res["peso_total_declarado_kg"],
            "peso_total_calculado_kg": res["peso_total_calculado_kg"],
            "itens_auditados": res["itens_auditados"],
            "conformidade_percentual": 100.0 if not issues else 0.0,
            "status": "REPROVADO" if issues else "APROVADO",
            "inconformidades": issues
        }
