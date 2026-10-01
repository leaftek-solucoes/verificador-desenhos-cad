import csv
import os
from datetime import datetime
from typing import Dict, Any

class ReportExporter:
    """Gera laudos tabulares de auditoria de fabricação para controle de qualidade."""
    
    def __init__(self, output_dir: str = "temp_reports"):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

    def export_csv(self, audit_result: Dict[str, Any], output_filename: str) -> str:
        filepath = os.path.join(self.output_dir, output_filename)
        
        with open(filepath, mode="w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f, delimiter=";")
            
            # Cabeçalho do Laudo
            writer.writerow(["LEAFTEK CAD QA/QC - LAUDO DE CONFORMIDADE TÉCNICA"])
            writer.writerow(["Arquivo Auditado", audit_result.get("arquivo", "")])
            writer.writerow(["Data da Verificação", audit_result.get("data_verificacao", "")])
            writer.writerow(["Status Geral", audit_result.get("status_geral", "")])
            writer.writerow(["Índice de Conformidade", f"{audit_result.get('score_conformidade', 0)}%"])
            writer.writerow([])
            
            # Detalhes da Lista de Materiais
            bom = audit_result.get("detalhes_bom", {})
            writer.writerow(["DADOS DA LISTA DE MATERIAIS"])
            writer.writerow(["Peso Total Declarado (kg)", bom.get("peso_declarado_kg", 0.0)])
            writer.writerow(["Peso Total Calculado (kg)", bom.get("peso_calculado_kg", 0.0)])
            writer.writerow(["Itens Auditados na Tabela", bom.get("itens_auditados", 0)])
            writer.writerow([])
            
            # Tabela de Inconformidades
            writer.writerow(["ID", "GRAVIDADE", "MÓDULO / TIPO", "DESCRIÇÃO DA NÃO CONFORMIDADE", "POSIÇÃO X", "POSIÇÃO Y"])
            for err in audit_result.get("inconformidades", []):
                pos = err.get("posicao", {})
                writer.writerow([
                    err.get("id", ""),
                    err.get("gravidade", ""),
                    err.get("tipo", ""),
                    err.get("descricao", ""),
                    pos.get("x", 0.0),
                    pos.get("y", 0.0)
                ])
                
        return filepath
