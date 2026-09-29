import os
import matplotlib
matplotlib.use("Agg")  # Operação em modo servidor (headless)
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon, Rectangle
import numpy as np

import ezdxf
from ezdxf.addons.drawing import RenderContext, Frontend
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend

class A3VerificationPDFGenerator:
    def __init__(self, output_dir: str = "temp_reports"):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)
        # Dimensões ISO A3 em polegadas para Matplotlib (420 x 297 mm)
        self.a3_width_in = 420.0 / 25.4   # ~16.53 pol
        self.a3_height_in = 297.0 / 25.4  # ~11.69 pol

    def _draw_cloud(self, ax, cx, cy, radius=120.0, num_arcs=8, color="#DC2626"):
        """Desenha nuvem de revisão vermelha paramétrica centrada nas coordenadas do erro."""
        angles = np.linspace(0, 2 * np.pi, num_arcs, endpoint=False)
        for a in angles:
            arc_x = cx + np.cos(a) * radius
            arc_y = cy + np.sin(a) * radius
            circle = plt.Circle((arc_x, arc_y), radius * 0.45, color=color, fill=False, linewidth=1.8, zorder=10)
            ax.add_patch(circle)

    def generate(self, doc: ezdxf.document.Drawing, audit_result: dict, output_filename: str) -> str:
        pdf_path = os.path.join(self.output_dir, output_filename)

        fig = plt.figure(figsize=(self.a3_width_in, self.a3_height_in), dpi=300)
        ax = fig.add_axes([0, 0, 1, 1])

        # 1. Renderiza as entidades vetoriais do Model Space do DXF
        msp = doc.modelspace()
        ctx = RenderContext(doc)
        backend = MatplotlibBackend(ax)
        frontend = Frontend(ctx, backend)
        frontend.draw_layout(msp, finalize=True)

        # 2. Desenha nuvens de revisão vermelhas e tags sobre as coordenadas reais
        inconformidades = audit_result.get("inconformidades", [])
        for err in inconformidades:
            pos = err.get("posicao", {})
            px = pos.get("x", 0.0)
            py = pos.get("y", 0.0)

            # Desenha nuvem apenas se não estiver em (0,0) genérico
            if px != 0.0 or py != 0.0:
                self._draw_cloud(ax, px, py, radius=80.0, color="#DC2626")
                ax.text(
                    px + 90, py + 90,
                    f"[{err.get('id')}] {err.get('tipo')}\n{err.get('descricao')}",
                    fontsize=5,
                    fontweight="bold",
                    color="#DC2626",
                    bbox=dict(boxstyle="round,pad=0.3", fc="#FEF2F2", ec="#DC2626", lw=0.8),
                    zorder=12
                )

        # 3. Adiciona Carimbo Oficial de Cópia de Verificação no canto inferior direito
        status = audit_result.get("status_geral", "REPROVADO")
        stamp_color = "#DC2626" if "REPROVADO" in status else "#059669"
        
        # Carimbo com posição normalizada na folha (inferior direito)
        fig.text(
            0.82, 0.05,
            f"LEAFTEK QA/QC - CÓPIA DE VERIFICAÇÃO A3\n"
            f"STATUS: {status}\n"
            f"CONFORMIDADE: {audit_result.get('score_conformidade')}% | FALHAS: {len(inconformidades)}\n"
            f"DATA: {np.datetime64('today')}",
            fontsize=7,
            fontfamily="monospace",
            fontweight="bold",
            color=stamp_color,
            bbox=dict(boxstyle="square,pad=0.6", fc="white", ec=stamp_color, lw=2.0)
        )

        fig.savefig(pdf_path, format="pdf", dpi=300)
        plt.close(fig)
        return pdf_path
