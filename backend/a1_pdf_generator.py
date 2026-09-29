import os
import math
from datetime import datetime
from typing import Dict, Any, List

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle
import numpy as np

import ezdxf
from ezdxf.addons.drawing import RenderContext, Frontend
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
from ezdxf.addons.drawing.properties import LayoutProperties

class A1VerificationPDFGenerator:
    def __init__(self, output_dir: str = "temp_reports"):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)
        # Dimensões ISO A1 Paisagem (841 x 594 mm em polegadas)
        self.width_in = 841.0 / 25.4   # ~33.110 pol
        self.height_in = 594.0 / 25.4  # ~23.386 pol

    def _draw_cloud(self, ax, cx: float, cy: float, radius: float = 55.0, num_arcs: int = 10, color: str = "#DC2626"):
        """Nuvem de revisão técnica com arcos suaves ajustados para prancha A1."""
        arc_angle = (2 * math.pi) / num_arcs
        arc_radius = radius * 0.38

        for i in range(num_arcs):
            angle = i * arc_angle
            ax_pos = cx + math.cos(angle) * radius
            ay_pos = cy + math.sin(angle) * radius
            patch = Circle(
                (ax_pos, ay_pos),
                arc_radius,
                edgecolor=color,
                facecolor="none",
                linewidth=1.2,
                zorder=20
            )
            ax.add_patch(patch)

    def _draw_verified_badge(self, ax, x: float, y: float):
        """Marcador verde sutil (check) para elementos verificados e sem erro."""
        ax.plot(x, y, marker="o", markersize=4.2, color="#059669", zorder=15)
        ax.text(
            x, y, "✓",
            fontsize=5.2,
            fontweight="bold",
            color="#FFFFFF",
            ha="center",
            va="center",
            zorder=16
        )

    def _add_compact_stamp(self, fig, status: str, score: float, total_issues: int, verified_count: int, filename: str):
        """Carimbo de verificação técnico calibrado para o canto inferior direito de prancha A1."""
        is_reprovado = "REPROVADO" in status
        stamp_color = "#DC2626" if is_reprovado else ("#D97706" if "RESSALVA" in status else "#059669")
        today = datetime.now().strftime("%d/%m/%Y %H:%M")

        stamp_text = (
            f"LEAFTEK QA/QC | CÓPIA DE VERIFICAÇÃO TÉCNICA A1\n"
            f"ARQUIVO: {filename[:36]} | EMISSÃO: {today}\n"
            f"STATUS DO PROJETO : {status} | CONFORMIDADE: {score}%\n"
            f"✓ ELEMENTOS CONFORMES: {verified_count} | ✗ NOTAS A REVISAR: {total_issues}\n"
            f"PADRÃO: ABNT NBR 8800 / DENSIDADE DO AÇO: 7.850 kg/m³"
        )

        fig.text(
            0.988, 0.015,
            stamp_text,
            fontsize=6.2,  # Proporcional a texto técnico de 2.2 mm impresso em folha A1
            fontfamily="monospace",
            fontweight="bold",
            color=stamp_color,
            ha="right",
            va="bottom",
            bbox=dict(
                boxstyle="square,pad=0.5",
                facecolor="#FFFFFF",
                edgecolor=stamp_color,
                linewidth=1.4,
                alpha=0.96
            ),
            zorder=35
        )

    def generate(self, doc: ezdxf.document.Drawing, audit_result: Dict[str, Any], output_filename: str) -> str:
        pdf_path = os.path.join(self.output_dir, output_filename)

        fig = plt.figure(figsize=(self.width_in, self.height_in), dpi=300)
        # Margem de 10 mm padrão de plotter em relação à borda física A1
        ax = fig.add_axes([0.015, 0.015, 0.97, 0.97])
        ax.set_aspect("equal", adjustable="datalim")
        ax.axis("off")

        msp = doc.modelspace()
        ctx = RenderContext(doc)
        layout_props = LayoutProperties.from_layout(msp)
        layout_props.set_colors(bg="#FFFFFF", fg="#000000")

        backend = MatplotlibBackend(ax)
        frontend = Frontend(ctx, backend)
        frontend.draw_layout(msp, layout_properties=layout_props, finalize=False)

        # Mapeia coordenadas dos erros para não sobrepor marcador verde no mesmo nó
        inconformidades = audit_result.get("inconformidades", [])
        error_coords = set()
        for err in inconformidades:
            p = err.get("posicao", {})
            error_coords.add((round(float(p.get("x", 0)), 1), round(float(p.get("y", 0)), 1)))

        # 1. MARCAÇÕES EM VERDE (Entidades verificadas e conformes)
        verified_items_count = 0
        for dim in msp.query("DIMENSION"):
            pt = getattr(dim.dxf, "text_midpoint", None) or getattr(dim.dxf, "defpoint", None)
            if pt:
                coord = (round(pt[0], 1), round(pt[1], 1))
                if coord not in error_coords and (pt[0] != 0 or pt[1] != 0):
                    self._draw_verified_badge(ax, pt[0], pt[1])
                    verified_items_count += 1

        for txt in msp.query("TEXT MTEXT"):
            pt = getattr(txt.dxf, "insert", None)
            if pt:
                coord = (round(pt[0], 1), round(pt[1], 1))
                if coord not in error_coords and (pt[0] != 0 or pt[1] != 0):
                    self._draw_verified_badge(ax, pt[0], pt[1])
                    verified_items_count += 1

        # 2. MARCAÇÕES EM VERMELHO (Nuvens e Caixas de Chamada)
        notas_gerais = []
        for err in inconformidades:
            pos = err.get("posicao", {})
            px = float(pos.get("x", 0.0))
            py = float(pos.get("y", 0.0))

            if px != 0.0 or py != 0.0:
                is_crit = err.get("gravidade") == "CRITICA"
                color = "#DC2626" if is_crit else "#D97706"

                # Nuvem proporcional à geometria de prancha A1
                self._draw_cloud(ax, px, py, radius=50.0, color=color)
                ax.plot(px, py, marker="x", markersize=5, color=color, zorder=25)

                # Caixa de chamada reduzida e discreta
                box_text = f"[{err.get('id')}] {err.get('tipo')}\n{err.get('descricao')}"

                ax.annotate(
                    box_text,
                    xy=(px, py),
                    xytext=(px + 60, py + 60),
                    arrowprops=dict(
                        arrowstyle="->",
                        color=color,
                        lw=1.0,
                        shrinkA=3,
                        shrinkB=3
                    ),
                    fontsize=5.2,  # Proporção exata para visualização limpa em A1
                    fontfamily="sans-serif",
                    fontweight="bold",
                    color="#7F1D1D" if is_crit else "#78350F",
                    bbox=dict(
                        boxstyle="round,pad=0.3",
                        fc="#FEF2F2" if is_crit else "#FFFBEB",
                        ec=color,
                        lw=0.9,
                        alpha=0.95
                    ),
                    zorder=28
                )
            else:
                notas_gerais.append(err)

        # 3. QUADRO COMPACTO DE NOTAS GERAIS NO TOPO ESQUERDO
        if notas_gerais:
            linhas = ["QUADRO DE RESSALVAS GERAIS DA FOLHA:"]
            for ng in notas_gerais[:6]:
                linhas.append(f"• [{ng.get('id')}] {ng.get('descricao')}")
            texto_notas = "\n".join(linhas)

            fig.text(
                0.02, 0.98,
                texto_notas,
                fontsize=5.8,
                fontfamily="monospace",
                fontweight="bold",
                color="#DC2626",
                ha="left",
                va="top",
                bbox=dict(
                    boxstyle="square,pad=0.45",
                    facecolor="#FEF2F2",
                    edgecolor="#DC2626",
                    linewidth=1.2,
                    alpha=0.94
                ),
                zorder=35
            )

        # 4. CARIMBO OFICIAL A1
        self._add_compact_stamp(
            fig,
            status=audit_result.get("status_geral", "REPROVADO"),
            score=audit_result.get("score_conformidade", 0.0),
            total_issues=len(inconformidades),
            verified_count=verified_items_count,
            filename=audit_result.get("arquivo", "desenho.dwg")
        )

        backend.finalize()
        fig.savefig(pdf_path, format="pdf", dpi=300, facecolor="#FFFFFF")
        plt.close(fig)
        return pdf_path
