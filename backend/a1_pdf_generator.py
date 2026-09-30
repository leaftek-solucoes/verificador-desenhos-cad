import os
import math
from datetime import datetime
from typing import Dict, Any, List

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle

import ezdxf
from ezdxf.addons.drawing import RenderContext, Frontend
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
from ezdxf.addons.drawing.properties import LayoutProperties

class A1VerificationPDFGenerator:
    def __init__(self, output_dir: str = "temp_reports"):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)
        # Dimensões exatas de ISO A1 Paisagem (841 x 594 mm em polegadas)
        self.width_in = 841.0 / 25.4   # ~33.11 pol
        self.height_in = 594.0 / 25.4  # ~23.38 pol

    def _draw_cloud(self, ax, cx: float, cy: float, radius: float = 18.0, num_arcs: int = 12, color: str = "#DC2626"):
        """Desenha nuvem de revisão técnica compacta na escala de prancha A1."""
        arc_angle = (2 * math.pi) / num_arcs
        arc_radius = radius * 0.32

        for i in range(num_arcs):
            angle = i * arc_angle
            ax_pos = cx + math.cos(angle) * radius
            ay_pos = cy + math.sin(angle) * radius
            patch = Circle(
                (ax_pos, ay_pos),
                arc_radius,
                edgecolor=color,
                facecolor="none",
                linewidth=0.7,
                zorder=20
            )
            ax.add_patch(patch)

    def _draw_verified_badge(self, ax, x: float, y: float):
        """Marcador verde técnico discreto para cotas e itens conformes."""
        ax.plot(x, y, marker="o", markersize=3.0, color="#059669", zorder=15)
        ax.text(
            x, y, "✓",
            fontsize=3.6,
            fontweight="bold",
            color="#FFFFFF",
            ha="center",
            va="center",
            zorder=16
        )

    def _add_compact_stamp(self, fig, status: str, score: float, total_issues: int, verified_count: int, filename: str):
        """Carimbo executivo reduzido e harmônico para o canto inferior direito de folha A1."""
        is_reprovado = "REPROVADO" in status
        stamp_color = "#DC2626" if is_reprovado else ("#D97706" if "RESSALVA" in status else "#059669")
        today = datetime.now().strftime("%d/%m/%Y %H:%M")

        stamp_text = (
            f"LEAFTEK QA/QC | VERIFICAÇÃO A1\n"
            f"ARQUIVO: {filename[:30]} | {today}\n"
            f"STATUS: {status} | CONFORMIDADE: {score}%\n"
            f"✓ CONFORMES: {verified_count} | ✗ NOTAS A REVISAR: {total_issues}\n"
            f"PADRÃO: ABNT NBR 8800 / AWS E7018"
        )

        fig.text(
            0.988, 0.012,
            stamp_text,
            fontsize=4.0,  # Proporção harmonizada para padrão de plotagem A1
            fontfamily="monospace",
            fontweight="bold",
            color=stamp_color,
            ha="right",
            va="bottom",
            bbox=dict(
                boxstyle="square,pad=0.35",
                facecolor="#FFFFFF",
                edgecolor=stamp_color,
                linewidth=0.8,
                alpha=0.96
            ),
            zorder=35
        )

    def generate(self, doc: ezdxf.document.Drawing, audit_result: Dict[str, Any], output_filename: str) -> str:
        pdf_path = os.path.join(self.output_dir, output_filename)

        fig = plt.figure(figsize=(self.width_in, self.height_in), dpi=300)
        ax = fig.add_axes([0.012, 0.012, 0.976, 0.976])
        ax.set_aspect("equal", adjustable="datalim")
        ax.axis("off")

        msp = doc.modelspace()
        ctx = RenderContext(doc)
        layout_props = LayoutProperties.from_layout(msp)
        layout_props.set_colors(bg="#FFFFFF", fg="#000000")

        backend = MatplotlibBackend(ax)
        frontend = Frontend(ctx, backend)
        frontend.draw_layout(msp, layout_properties=layout_props, finalize=False)

        # Atualiza e obtém os limites exatos da folha/geometria desenhada
        ax.autoscale_view()
        min_x, max_x = ax.get_xlim()
        min_y, max_y = ax.get_ylim()
        span_x = max_x - min_x
        span_y = max_y - min_y

        # Define margens de segurança para impedir que anotações saiam da folha
        safe_margin_x = span_x * 0.025
        safe_margin_y = span_y * 0.025
        mid_x = (min_x + max_x) / 2.0
        mid_y = (min_y + max_y) / 2.0

        # Tamanho adaptado e compacto de nuvem e deslocamento da chamada
        cloud_radius = max(8.0, min(span_x * 0.012, 22.0))
        offset_dist_x = max(18.0, min(span_x * 0.035, 45.0))
        offset_dist_y = max(18.0, min(span_y * 0.035, 45.0))

        inconformidades = audit_result.get("inconformidades", [])
        error_coords = set()
        for err in inconformidades:
            p = err.get("posicao", {})
            error_coords.add((round(float(p.get("x", 0)), 1), round(float(p.get("y", 0)), 1)))

        # 1. MARCAÇÕES EM VERDE (Itens aprovados)
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

        # 2. MARCAÇÕES EM VERMELHO (Nuvens e Caixas com Trava de Margem)
        notas_gerais = []
        for err in inconformidades:
            pos = err.get("posicao", {})
            px = float(pos.get("x", 0.0))
            py = float(pos.get("y", 0.0))

            if px != 0.0 or py != 0.0:
                is_crit = err.get("gravidade") == "CRITICA"
                color = "#DC2626" if is_crit else "#D97706"

                # Nuvem reduzida
                self._draw_cloud(ax, px, py, radius=cloud_radius, color=color)
                ax.plot(px, py, marker="x", markersize=3.0, color=color, zorder=25)

                # Direcionamento inteligente da chamada (aponta sempre para dentro da folha)
                dx = -offset_dist_x if px > mid_x else offset_dist_x
                dy = -offset_dist_y if py > mid_y else offset_dist_y

                tx = px + dx
                ty = py + dy

                # Bloqueio estrito (clamp): o texto nunca ultrapassa a borda da prancha
                tx = max(min_x + safe_margin_x, min(tx, max_x - safe_margin_x))
                ty = max(min_y + safe_margin_y, min(ty, max_y - safe_margin_y))

                box_text = f"[{err.get('id')}] {err.get('tipo')}\n{err.get('descricao')}"

                ax.annotate(
                    box_text,
                    xy=(px, py),
                    xytext=(tx, ty),
                    ha="right" if dx < 0 else "left",
                    va="top" if dy < 0 else "bottom",
                    arrowprops=dict(
                        arrowstyle="->",
                        color=color,
                        lw=0.6,
                        shrinkA=2,
                        shrinkB=2
                    ),
                    fontsize=3.8,  # Letra reduzida e proporcional para detalhamento A1
                    fontfamily="sans-serif",
                    fontweight="bold",
                    color="#7F1D1D" if is_crit else "#78350F",
                    bbox=dict(
                        boxstyle="round,pad=0.2",
                        fc="#FEF2F2" if is_crit else "#FFFBEB",
                        ec=color,
                        lw=0.6,
                        alpha=0.95
                    ),
                    zorder=28
                )
            else:
                notas_gerais.append(err)

        # 3. QUADRO COMPACTO DE NOTAS GERAIS NO TOPO ESQUERDO
        if notas_gerais:
            linhas = ["RESSALVAS GERAIS:"]
            for ng in notas_gerais[:5]:
                linhas.append(f"• [{ng.get('id')}] {ng.get('descricao')}")
            texto_notas = "\n".join(linhas)

            fig.text(
                0.018, 0.982,
                texto_notas,
                fontsize=4.0,
                fontfamily="monospace",
                fontweight="bold",
                color="#DC2626",
                ha="left",
                va="top",
                bbox=dict(
                    boxstyle="square,pad=0.3",
                    facecolor="#FEF2F2",
                    edgecolor="#DC2626",
                    linewidth=0.7,
                    alpha=0.94
                ),
                zorder=35
            )

        # 4. CARIMBO OFICIAL COMPACTO
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
