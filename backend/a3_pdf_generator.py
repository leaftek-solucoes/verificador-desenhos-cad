import os
import math
from datetime import datetime
from typing import Dict, Any, List

import matplotlib
matplotlib.use("Agg")  # Execução estritamente em segundo plano (servidor)
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, Rectangle
import numpy as np

import ezdxf
from ezdxf.addons.drawing import RenderContext, Frontend
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
from ezdxf.addons.drawing.properties import LayoutProperties

class A3VerificationPDFGenerator:
    def __init__(self, output_dir: str = "temp_reports"):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)
        # Dimensões exatas de ISO A3 em polegadas para 300 DPI (420 x 297 mm)
        self.width_in = 420.0 / 25.4   # ~16.535 pol
        self.height_in = 297.0 / 25.4  # ~11.693 pol

    def _draw_cloud(self, ax, cx: float, cy: float, radius: float = 60.0, num_arcs: int = 8, color: str = "#DC2626"):
        """Desenha nuvem de revisão vermelha paramétrica ao redor de uma coordenada."""
        arc_angle = (2 * math.pi) / num_arcs
        arc_radius = radius * 0.42

        for i in range(num_arcs):
            angle = i * arc_angle
            ax_pos = cx + math.cos(angle) * radius
            ay_pos = cy + math.sin(angle) * radius
            patch = Circle(
                (ax_pos, ay_pos),
                arc_radius,
                edgecolor=color,
                facecolor="none",
                linewidth=1.8,
                linestyle="-",
                zorder=20
            )
            ax.add_patch(patch)

    def _add_stamp(self, fig, status: str, score: float, total_issues: int, filename: str):
        """Aplica o carimbo executivo de QA/QC no canto inferior direito."""
        is_reprovado = "REPROVADO" in status
        stamp_color = "#DC2626" if is_reprovado else ("#D97706" if "RESSALVA" in status else "#059669")
        today = datetime.now().strftime("%d/%m/%Y - %H:%M")

        stamp_text = (
            "====================================================\n"
            "       LEAFTEK QA/QC - CÓPIA DE VERIFICAÇÃO A3      \n"
            "====================================================\n"
            f"ARQUIVO: {filename[:30]}\n"
            f"STATUS DO DESENHO : {status}\n"
            f"ÍNDICE CONFORMIDADE: {score}% | TOTAL DE NOTAS: {total_issues}\n"
            f"DATA DA AUDITORIA : {today}\n"
            "----------------------------------------------------\n"
            "OBS: PRANCHA RESTRITA A VERIFICAÇÃO DE PROJETO.\n"
            "VEDADA A FABRICAÇÃO ANTES DA BAIXA DAS RESSALVAS.\n"
            "===================================================="
        )

        fig.text(
            0.985, 0.025,
            stamp_text,
            fontsize=6.5,
            fontfamily="monospace",
            fontweight="bold",
            color=stamp_color,
            ha="right",
            va="bottom",
            bbox=dict(
                boxstyle="square,pad=0.6",
                facecolor="#FFFFFF",
                edgecolor=stamp_color,
                linewidth=2.0,
                alpha=0.95
            ),
            zorder=30
        )

    def generate(self, doc: ezdxf.document.Drawing, audit_result: Dict[str, Any], output_filename: str) -> str:
        """
        Gera a prancha A3 contendo o desenho vetorial e as anotações sobrepostas.
        """
        pdf_path = os.path.join(self.output_dir, output_filename)

        fig = plt.figure(figsize=(self.width_in, self.height_in), dpi=300)
        # Margens técnicas para enquadramento da folha A3
        ax = fig.add_axes([0.03, 0.03, 0.94, 0.94])
        ax.set_aspect("equal", adjustable="datalim")
        ax.axis("off")

        # 1. Renderização Vetorial Nativa do DWG/DXF
        # Inspeciona se audita o Model Space ou o Layout ativo
        msp = doc.modelspace()
        ctx = RenderContext(doc)
        
        # Fundo branco com linhas pretas (padrão de impressão/plotagem de engenharia)
        layout_props = LayoutProperties.from_layout(msp)
        layout_props.set_colors(bg="#FFFFFF", fg="#000000")

        backend = MatplotlibBackend(ax)
        frontend = Frontend(ctx, backend)
        frontend.draw_layout(msp, layout_properties=layout_props, finalize=False)

        # 2. Obtenção dos limites geométricos do desenho
        all_x, all_y = [], []
        for entity in msp:
            if hasattr(entity.dxf, "start"):
                all_x.append(entity.dxf.start[0])
                all_y.append(entity.dxf.start[1])
            elif hasattr(entity.dxf, "insert"):
                all_x.append(entity.dxf.insert[0])
                all_y.append(entity.dxf.insert[1])

        if all_x and all_y:
            min_x, max_x = min(all_x), max(all_x)
            min_y, max_y = min(all_y), max(all_y)
        else:
            min_x, max_x = -500.0, 500.0
            min_y, max_y = -500.0, 500.0

        diag = math.sqrt((max_x - min_x) ** 2 + (max_y - min_y) ** 2) or 1000.0
        cloud_radius = max(25.0, diag * 0.025)

        # 3. Sobreposição de Nuvens e Balões de Chamada
        inconformidades = audit_result.get("inconformidades", [])
        notas_gerais = []

        for err in inconformidades:
            pos = err.get("posicao", {})
            px = float(pos.get("x", 0.0))
            py = float(pos.get("y", 0.0))

            # Se o erro possui coordenadas reais no espaço do desenho
            if px != 0.0 or py != 0.0:
                is_crit = err.get("gravidade") == "CRITICA"
                color = "#DC2626" if is_crit else "#D97706"

                # Nuvem de revisão vermelha
                self._draw_cloud(ax, px, py, radius=cloud_radius, color=color)

                # Ponto central
                ax.plot(px, py, marker="o", markersize=4, color=color, zorder=25)

                # Caixa de chamada com texto explicativo
                box_text = f"[{err.get('id')}] {err.get('tipo')}\n{err.get('descricao')}"
                offset_x = cloud_radius * 1.2
                offset_y = cloud_radius * 1.2

                ax.annotate(
                    box_text,
                    xy=(px, py),
                    xytext=(px + offset_x, py + offset_y),
                    arrowprops=dict(
                        arrowstyle="->",
                        color=color,
                        lw=1.5,
                        shrinkA=5,
                        shrinkB=5
                    ),
                    fontsize=5.5,
                    fontfamily="sans-serif",
                    fontweight="bold",
                    color="#991B1B" if is_crit else "#92400E",
                    bbox=dict(
                        boxstyle="round,pad=0.4",
                        fc="#FEF2F2" if is_crit else "#FFFBEB",
                        ec=color,
                        lw=1.2,
                        alpha=0.92
                    ),
                    zorder=28
                )
            else:
                # Notas globais (ex: carimbo ausente, nota de solda geral ausente)
                notas_gerais.append(err)

        # 4. Quadro de Notas Técnicas Gerais no Canto Superior Esquerdo
        if notas_gerais:
            linhas_nota = ["QUADRO DE RESSALVAS GERAIS DA FOLHA:"]
            for idx, ng in enumerate(notas_gerais, 1):
                linhas_nota.append(f"{idx}. [{ng.get('id')}] {ng.get('tipo')}: {ng.get('descricao')}")
            texto_notas = "\n".join(linhas_nota)

            fig.text(
                0.035, 0.965,
                texto_notas,
                fontsize=6.5,
                fontfamily="monospace",
                fontweight="bold",
                color="#DC2626",
                ha="left",
                va="top",
                bbox=dict(
                    boxstyle="square,pad=0.5",
                    facecolor="#FEF2F2",
                    edgecolor="#DC2626",
                    linewidth=1.5,
                    alpha=0.9
                ),
                zorder=30
            )

        # 5. Aplicação do Carimbo
        self._add_stamp(
            fig,
            status=audit_result.get("status_geral", "REPROVADO"),
            score=audit_result.get("score_conformidade", 0.0),
            total_issues=len(inconformidades),
            filename=audit_result.get("arquivo", "desenho.dxf")
        )

        backend.finalize()
        fig.savefig(pdf_path, format="pdf", dpi=300, facecolor="#FFFFFF")
        plt.close(fig)

        return pdf_path
