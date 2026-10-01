cd /workspaces/verificador-desenhos-cad/backend 2>/dev/null || cd backend

cat << 'EOF' > bom_checker.py
import re
from typing import Dict, List, Any, Tuple
import ezdxf

class BOMChecker:
    def __init__(self, steel_density: float = 7850.0, tolerance_kg: float = 0.15):
        # Densidade do aço em kg/m³ e tolerância para arredondamentos
        self.steel_density = steel_density
        self.tolerance_kg = tolerance_kg

    def _extract_all_texts(self, layout) -> List[Dict[str, Any]]:
        """Extrai todos os textos e MTexts do espaço com suas coordenadas."""
        texts = []
        for ent in layout.query("TEXT MTEXT"):
            val = ""
            if ent.dxftype() == "TEXT":
                val = ent.dxf.text
            elif ent.dxftype() == "MTEXT":
                val = ent.text
            
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
        """Converte strings numéricas com vírgula ou ponto para float."""
        match = re.search(r"(\d+[\.,]\d+|\d+)", text)
        if match:
            return float(match.group(1).replace(",", "."))
        return 0.0

    def check(self, doc: ezdxf.document.Drawing) -> Dict[str, Any]:
        issues: List[Dict[str, Any]] = []
        
        # Localiza o layout principal
        target_layout = doc.modelspace()
        for lay in doc.layouts:
            if lay.name.lower() != "model":
                ents = [e for e in lay if e.dxftype() != "VIEWPORT"]
                if len(ents) > 10:
                    target_layout = lay
                    break

        texts = self._extract_all_texts(target_layout)

        # 1. Localiza o bloco ou cabeçalho da Lista de Material
        bom_header = None
        peso_total_decl = None
        peso_total_pos = {"x": 0.0, "y": 0.0}
        peso_total_valor = 0.0

        for t in texts:
            txt_upper = t["text"].upper()
            if "LISTA DE MATERIAL" in txt_upper or "LISTA DE MATERIAIS" in txt_upper:
                bom_header = t
            if "PESO TOTAL" in txt_upper:
                peso_total_decl = t
                peso_total_pos = {"x": t["x"], "y": t["y"]}
                peso_total_valor = self._parse_float(t["text"])

        if not bom_header and not peso_total_decl:
            return {
                "modulo": "bom_checker",
                "status": "APROVADO",
                "mensagem": "Nenhuma Lista de Material identificada na folha.",
                "inconformidades": []
            }

        # 2. Varredura espacial dos textos da tabela de materiais
        # Delimita a região da tabela com base na proximidade do cabeçalho / peso total
        ref_x = peso_total_pos["x"] if peso_total_decl else bom_header["x"]
        ref_y = peso_total_pos["y"] if peso_total_decl else bom_header["y"]

        table_texts = [
            t for t in texts
            if abs(t["x"] - ref_x) < 350.0 and abs(t["y"] - ref_y) < 300.0
        ]

        # 3. Extração e reconciliação dos itens da tabela
        # Agrupa textos que compartilham a mesma linha (Y aproximado)
        rows_by_y: Dict[float, List[Dict[str, Any]]] = {}
        for t in table_texts:
            # Agrupa com tolerância de 5mm na coordenada Y
            matched_y = None
            for ry in rows_by_y.keys():
                if abs(t["y"] - ry) < 5.0:
                    matched_y = ry
                    break
            if matched_y is not None:
                rows_by_y[matched_y].append(t)
            else:
                rows_by_y[t["y"]] = [t]

        soma_pesos_calculada = 0.0
        linhas_processadas = 0

        for y_coord, row_items in rows_by_y.items():
            # Ordena os textos da linha da esquerda para a direita (coordenada X crescente)
            row_items.sort(key=lambda item: item["x"])
            row_str = " | ".join([it["text"] for it in row_items])
            
            # Pula cabeçalhos e a linha do próprio peso total
            if "POS" in row_str.upper() or "QTD" in row_str.upper() or "PESO TOTAL" in row_str.upper():
                continue

            # Tenta extrair: Quantidade e Peso (Unitário ou da Linha)
            nums = []
            for it in row_items:
                fval = self._parse_float(it["text"])
                if fval > 0.0:
                    nums.append((fval, it))

            # Se a linha contiver números compatíveis com Qtd e Peso
            if len(nums) >= 2:
                # O último número da linha geralmente é o Peso Total do Item ou Peso Unitário
                peso_val, peso_item = nums[-1]
                qtd_val = nums[0][0]

                if 0.0 < peso_val < 5000.0:
                    soma_pesos_calculada += peso_val
                    linhas_processadas += 1

        # 4. Auditoria de Divergência do Peso Total
        if peso_total_valor > 0.0 and soma_pesos_calculada > 0.0:
            diferenca = abs(peso_total_valor - soma_pesos_calculada)

            if diferenca > self.tolerance_kg:
                issues.append({
                    "id": "BOM-PESO-01",
                    "tipo": "Erro na Soma da Lista de Materiais",
                    "gravidade": "CRITICA",
                    "descricao": (
                        f"Divergência no Peso Total: Declarado = {peso_total_valor:.2f} kg, "
                        f"Soma calculada dos itens = {soma_pesos_calculada:.2f} kg "
                        f"(Diferença: {diferenca:.2f} kg)."
                    ),
                    "posicao": peso_total_pos
                })

        conformidade = 100.0 if len(issues) == 0 else 0.0

        return {
            "modulo": "bom_checker",
            "peso_total_declarado_kg": peso_total_valor,
            "peso_total_calculado_kg": round(soma_pesos_calculada, 2),
            "itens_auditados": linhas_processadas,
            "conformidade_percentual": conformidade,
            "status": "REPROVADO" if len(issues) > 0 else "APROVADO",
            "inconformidades": issues
        }
EOF
