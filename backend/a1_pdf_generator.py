import os
import math
import textwrap
from datetime import datetime
from typing import Dict, Any, List

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle

import ezdxf
from ezdxf import bbox
from ezdxf.addons.drawing import RenderContext, Frontend
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
from ezdxf.addons.drawing.properties import LayoutProperties

# Força plotagem monocromática (Preto e Branco) da geometria CAD
try:
    from ezdxf.addons.drawing.config import Configuration, ColorPolicy, BackgroundPolicy
    policy_pb = getattr(ColorPolicy, "BLACK", getattr(ColorPolicy, "MONOCHROME", ColorPolicy.COLOR_ON_WHITE))
    DRAWING_CONFIG = Configuration(
        color_policy=policy_pb,
        background_policy=BackgroundPolicy.WHITE,
        lineweight_scaling=1.8,
        min_lineweight=0.35
    )
except Exception:
    DRAWING_CONFIG = None

class A1VerificationPDFGenerator:
    def __init__(self, output_dir: str = "temp_reports"):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)
        # Dimensões exatas ISO A1 Paisagem (841 x 594 mm em polegadas)
        self.width_in = 841.0 / 25.4   # ~33.11 pol
        self.height_in = 594.0 / 25.4  # ~23.38 pol
        
        # 3.0 mm de altura real de plotagem na folha A1 = 8.5 pt (3.0 / 25.4 * 72)
        self.text_h_3mm = 8.5

    def _select_primary_layout(self, doc: ezdxf.document.Drawing):
        """Seleciona o espaço onde está a prancha técnica principal."""
        for lay in doc.layouts:
            if lay.name.lower() != "model":
                ents = [e for e in lay if e.dxftype() != "VIEWPORT"]
                if len(ents) > 10:
                    return lay
        return doc.modelspace()

    def _draw_error_marker(self, ax, cx: float, cy: float, radius: float, color: str = "#DC2626"):
        """Desenha círculo técnico de inspeção limpo com mira (substitui os girassóis)."""
        # 1. Círculo principal translúcido de destaque
        fill_circle = Circle(
            (cx, cy),
            radius,
            facecolor=color,
            alpha=0.08,
            edgecolor=color,
            linewidth=1.4,
            zorder=25
        )
        ax.add_patch(fill_circle)

        # 2. Mira central de precisão (+)
        cross_size = radius * 0.45
        ax.plot([cx - cross_size, cx + cross_size], [cy, cy], color=color, linewidth=1.2, zorder=26)
        ax.plot([cx, cx], [cy - cross_size, cy + cross_size], color=color, linewidth=1.2, zorder=26)

    def _draw_verified_badge(self, ax, x: float, y: float):
        """Marcador verde técnico '✓' para itens inspecionados e aprovados."""
        ax.plot(x, y, marker="o", markersize=7.0, color="#059669", zorder=20)
        ax.text(
            x, y, "✓",
            fontsize=6.5,
            fontweight="bold",
            color="#FFFFFF",
            ha="center",
            va="center",
            zorder=21
        )

    def _add_qa_stamp(self, fig, status: str, score: float, total_issues: int, verified_count: int, filename: str):
        """Carimbo oficial de verificação QA/QC no canto inferior direito da prancha."""
        is_reprovado = "REPROVADO" in status
        stamp_color = "#DC2626" if is_reprovado else ("#D97706" if "RESSALVA" in status else "#059669")
        today = datetime.now().strftime("%d/%m/%Y %H:%M")

        stamp_text = (
            f"LEAFTEK CAD QA/QC • LAUDO TÉCNICO DE VERIFICAÇÃO DE PROJETO\n"
            f"ARQUIVO : {filename[:40]}\n"
            f"EMISSÃO : {today} | FORMATO: ISO A1 (841 x 594 mm)\n"
            f"STATUS  : {status} | ÍNDICE DE CONFORMIDADE: {score}%\n"
            f"ITENS   : ✓ {verified_count} CONFORMES | ✗ {total_issues} NOTAS A REVISAR\n"
            f"CRITÉRIO: ABNT NBR 8800 / AWS D1.1 / PESO TEÓRICO: 7.850 kg/m³"
        )

        fig.text(
            0.965, 0.045,
            stamp_text,
            fontsize=self.text_h_3mm,
            fontfamily="monospace",
            fontweight="bold",
            color=stamp_color,
            ha="right",
            va="bottom",
            bbox=dict(
                boxstyle="square,pad=0.55",
                facecolor="#FFFFFF",
                edgecolor=stamp_color,
                linewidth=1.8,
                alpha=0.98
            ),
            zorder=40
        )

    def generate(self, doc: ezdxf.document.Drawing, audit_result: Dict[str, Any], output_filename: str) -> str:
        pdf_path = os.path.join(self.output_dir, output_filename)

        fig = plt.figure(figsize=(self.width_in, self.height_in), dpi=300)
        ax = fig.add_axes([0.040, 0.040, 0.920, 0.920])
        ax.axis("off")

        target_layout = self._select_primary_layout(doc)
        ctx = RenderContext(doc)
        layout_props = LayoutProperties.from_layout(target_layout)
        try:
            layout_props.background_color = "#FFFFFF"
            layout_props.default_color = "#000000"
        except Exception:
            pass

        # 1. ENQUADRAMENTO EXATO DA PRANCHA / PEÇA
        drawing_box = bbox.extents(target_layout)
        if drawing_box.has_data:
            cad_min_x, cad_min_y = drawing_box.extmin[0], drawing_box.extmin[1]
            cad_max_x, cad_max_y = drawing_box.extmax[0], drawing_box.extmax[1]
        else:
            cad_min_x, cad_min_y, cad_max_x, cad_max_y = 0.0, 0.0, 841.0, 594.0

        span_x = max(abs(cad_max_x - cad_min_x), 10.0)
        span_y = max(abs(cad_max_y - cad_min_y), 10.0)

        pad_x = span_x * 0.06
        pad_y = span_y * 0.06
        view_min_x = cad_min_x - pad_x
        view_max_x = cad_max_x + pad_x
        view_min_y = cad_min_y - pad_y
        view_max_y = cad_max_y + pad_y

        ax.set_xlim(view_min_x, view_max_x)
        ax.set_ylim(view_min_y, view_max_y)
        ax.set_aspect("equal", adjustable="datalim")

        # 2. RENDERIZAÇÃO EM PRETO E BRANCO TÉCNICO (CTB MONOCROMÁTICO)
        backend = MatplotlibBackend(ax)
        frontend = Frontend(ctx, backend, config=DRAWING_CONFIG) if DRAWING_CONFIG else Frontend(ctx, backend)
        frontend.draw_layout(target_layout, layout_properties=layout_props, finalize=False)

        # 3. MARCAÇÕES VERDES (ELEMENTOS APROVADOS)
        inconformidades = audit_result.get("inconformidades", [])
        error_coords = set()
        for err in inconformidades:
            p = err.get("posicao", {})
            error_coords.add((round(float(p.get("x", 0)), 1), round(float(p.get("y", 0)), 1)))

        verified_items_count = 0
        for dim in target_layout.query("DIMENSION"):
            pt = getattr(dim.dxf, "text_midpoint", None) or getattr(dim.dxf, "defpoint", None)
            if pt:
                coord = (round(pt[0], 1), round(pt[1], 1))
                if coord not in error_coords and (pt[0] != 0 or pt[1] != 0):
                    self._draw_verified_badge(ax, pt[0], pt[1])
                    verified_items_count += 1

        for txt in target_layout.query("TEXT MTEXT"):
            pt = getattr(txt.dxf, "insert", None)
            if pt:
                coord = (round(pt[0], 1), round(pt[1], 1))
                if coord not in error_coords and (pt[0] != 0 or pt[1] != 0):
                    self._draw_verified_badge(ax, pt[0], pt[1])
                    verified_items_count += 1

        # 4. CÍRCULOS TÉCNICOS VERMELHOS E SETAS DE CHAMADA
        marker_radius = max(8.0, span_x * 0.014)
        offset_dist_x = max(24.0, span_x * 0.038)
        offset_dist_y = max(24.0, span_y * 0.038)
        mid_x = (view_min_x + view_max_x) / 2.0
        mid_y = (view_min_y + view_max_y) / 2.0

        safe_min_x = view_min_x + pad_x * 0.5
        safe_max_x = view_max_x - pad_x * 0.5
        safe_min_y = view_min_y + pad_y * 0.5
        safe_max_y = view_max_y - pad_y * 0.5

        callouts_count = 0
        for err in inconformidades:
            pos = err.get("posicao", {})
            px = float(pos.get("x", 0.0))
            py = float(pos.get("y", 0.0))

            if px != 0.0 or py != 0.0:
                is_crit = err.get("gravidade") == "CRITICA"
                color = "#DC2626" if is_crit else "#D97706"

                # Aplica o círculo técnico com mira no furo/peça
                self._draw_error_marker(ax, px, py, radius=marker_radius, color=color)

                # Chamadas com seta para as notas
                if callouts_count < 10:
                    callouts_count += 1
                    dx = -offset_dist_x if px > mid_x else offset_dist_x
                    dy = -offset_dist_y if py > mid_y else offset_dist_y

                    tx = max(safe_min_x, min(px + dx, safe_max_x))
                    ty = max(safe_min_y, min(py + dy, safe_max_y))

                    desc_quebrada = "\n".join(textwrap.wrap(err.get("descricao", ""), width=32))
                    box_text = f"[{err.get('id')}] {err.get('tipo')}\n{desc_quebrada}"

                    ax.annotate(
                        box_text,
                        xy=(px, py),
                        xytext=(tx, ty),
                        ha="right" if dx < 0 else "left",
                        va="top" if dy < 0 else "bottom",
                        arrowprops=dict(
                            arrowstyle="->",
                            color=color,
                            lw=1.0,
                            shrinkA=3,
                            shrinkB=3
                        ),
                        fontsize=self.text_h_3mm,  # Altura real de 3 mm
                        fontfamily="sans-serif",
                        fontweight="bold",
                        color="#7F1D1D" if is_crit else "#78350F",
                        bbox=dict(
                            boxstyle="round,pad=0.35",
                            fc="#FEF2F2" if is_crit else "#FFFBEB",
                            ec=color,
                            lw=1.0,
                            alpha=0.96
                        ),
                        zorder=30
                    )

        # 5. QUADRO TÉCNICO DE RESSALVAS (CANTO SUPERIOR ESQUERDO)
        quadro_linhas = ["QUADRO DE RESSALVAS TÉCNICAS (MODIFICAÇÕES):"]
        for i, err in enumerate(inconformidades[:7]):
            desc_curta = err.get("descricao", "")
            if len(desc_curta) > 75:
                desc_curta = desc_curta[:72] + "..."
            quadro_linhas.append(f"{i+1}. [{err.get('id')}] {desc_curta}")

        if len(inconformidades) > 7:
            quadro_linhas.append(f"• ... e mais {len(inconformidades) - 7} apontamentos descritos no laudo.")

        texto_quadro = "\n".join(quadro_linhas)
        fig.text(
            0.045, 0.955,
            texto_quadro,
            fontsize=self.text_h_3mm,
            fontfamily="sans-serif",
            fontweight="bold",
            color="#DC2626",
            ha="left",
            va="top",
            bbox=dict(
                boxstyle="square,pad=0.5",
                facecolor="#FEF2F2",
                edgecolor="#DC2626",
                linewidth=1.4,
                alpha=0.96
            ),
            zorder=40
        )

        # 6. CARIMBO OFICIAL DE AUDITORIA
        self._add_qa_stamp(
            fig,
            status=audit_result.get("status_geral", "REPROVADO"),
            score=audit_result.get("score_conformidade", 0.0),
            total_issues=len(inconformidades),
            verified_count=verified_items_count,
            filename=audit_result.get("arquivo", "desenho.dwg")
        )

        fig.savefig(pdf_path, format="pdf", dpi=300, facecolor="#FFFFFF")
        plt.close(fig)
        return pdf_path
