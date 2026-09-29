import re
from typing import Dict, List, Any
import ezdxf

class TextChecker:
    def __init__(self):
        # Dicionário de erros ortográficos frequentes em detalhamento técnico
        self.common_typos = {
            r"\bdimen[cç][oõ]es\b": "dimensões",
            r"\bfabrica[cç][aã]o\b": "fabricação",
            r"\bfabri[cç][aã]o\b": "fabricação",
            r"\bsoladgem\b": "soldagem",
            r"\bsoldajem\b": "soldagem",
            r"\beletr[oó]do\b": "eletrodo",
            r"\bchanfo\b": "chanfro",
            r"\bparafuso\b": "parafuso",
            r"\bespefica[cç][aã]o\b": "especificação",
            r"\btoler[aâ]ncia\b": "tolerância",
            r"\bparafuzo\b": "parafuso",
            r"\bcomprimento\b": "comprimento"
        }

        # Notas e termos técnicos mandatórios em pranchas estruturais
        self.mandatory_notes = [
            {
                "chave": "UNIDADES_MM",
                "regex": r"(?:DIMENS[OÕ]ES|COTAS)\s+EM\s+MIL[IÍ]METROS",
                "descricao": "Nota obrigatória: 'DIMENSÕES EM MILÍMETROS' não encontrada na prancha."
            },
            {
                "chave": "SOLDA_AWS",
                "regex": r"AWS\s+E7018|E-7018",
                "descricao": "Especificação obrigatória de solda estrutural (AWS E7018) não localizada."
            },
            {
                "chave": "PINTURA_TRATAMENTO",
                "regex": r"PINTURA|GALVANIZA[CÇ][AÃ]O|TRATAMENTO\s+SUPERFICIAL",
                "descricao": "Nota obrigatória de acabamento/pintura ou proteção superficial ausente."
            }
        ]

    def _extract_all_texts(self, doc: ezdxf.document.Drawing) -> List[Dict[str, Any]]:
        extracted = []
        spaces = [doc.modelspace()]
        for layout in doc.layouts:
            if layout.name.lower() != "model":
                spaces.append(layout)

        for space in spaces:
            space_name = getattr(space, "name", "Model")
            for ent in space.query("TEXT MTEXT"):
                text_content = ent.dxf.text if ent.dxftype() == "TEXT" else ent.text
                if not text_content:
                    continue

                # Remove tags de formatação do AutoCAD
                cleaned = re.sub(r"\\[A-Za-z0-9]+;", "", text_content)
                cleaned = cleaned.replace(r"\P", " ").replace("{", "").replace("}", "").strip()

                pt = getattr(ent.dxf, "insert", [0, 0])
                extracted.append({
                    "raw": cleaned,
                    "espaco": space_name,
                    "posicao": {"x": round(pt[0], 2), "y": round(pt[1], 2)}
                })
        return extracted

    def check(self, doc: ezdxf.document.Drawing) -> Dict[str, Any]:
        texts = self._extract_all_texts(doc)
        issues: List[Dict[str, Any]] = []
        typo_count = 0
        missing_notes_count = 0

        # Unifica todo o conteúdo do projeto para conferir notas globais
        full_project_corpus = " ".join([t["raw"] for t in texts]).upper()

        # 1. Auditoria de Erros Ortográficos em cada texto individual
        for idx, item in enumerate(texts):
            text_str = item["raw"]
            for pattern, correct_word in self.common_typos.items():
                match = re.search(pattern, text_str, re.IGNORECASE)
                if match:
                    # Se não for idêntica à palavra correta formal
                    if match.group(0).lower() != correct_word.lower():
                        typo_count += 1
                        issues.append({
                            "id": f"TYPO-{typo_count}",
                            "tipo": "Erro Ortográfico Técnico",
                            "espaco": item["espaco"],
                            "termo_encontrado": match.group(0),
                            "termo_sugerido": correct_word,
                            "gravidade": "MEDIA",
                            "descricao": f"Possível desvio ortográfico: '{match.group(0)}'. Sugestão de correção: '{correct_word}'.",
                            "posicao": item["posicao"]
                        })

            # Detecta eletrodo inadequado (ex.: AWS E6013 em detalhamento industrial pesado)
            if re.search(r"AWS\s+E6013|E-6013", text_str, re.IGNORECASE):
                issues.append({
                    "id": f"WELD-ERR-{idx}",
                    "tipo": "Especificação Inadequada de Solda",
                    "espaco": item["espaco"],
                    "gravidade": "CRITICA",
                    "descricao": "Identificado eletrodo AWS E6013. Projetos estruturais industriais exigem eletrodo de baixo hidrogênio (ex: AWS E7018).",
                    "posicao": item["posicao"]
                })

        # 2. Auditoria de Notas Obrigatórias Globais
        for note in self.mandatory_notes:
            if not re.search(note["regex"], full_project_corpus):
                missing_notes_count += 1
                issues.append({
                    "id": f"NOTE-MISS-{missing_notes_count}",
                    "tipo": "Nota Mandatória Ausente",
                    "espaco": "Geral / Prancha",
                    "gravidade": "ALTA",
                    "descricao": note["descricao"],
                    "posicao": {"x": 100.0, "y": 50.0}
                })

        total_falhas = typo_count + missing_notes_count
        score = max(0.0, round(100.0 - (total_falhas * 12.5), 1))

        return {
            "modulo": "text_checker",
            "total_textos_examinados": len(texts),
            "erros_ortograficos": typo_count,
            "notas_ausentes": missing_notes_count,
            "conformidade_percentual": score,
            "status": "REPROVADO" if total_falhas > 0 else "APROVADO",
            "inconformidades": issues
        }