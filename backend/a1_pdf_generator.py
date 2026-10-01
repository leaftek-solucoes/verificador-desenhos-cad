import os
import math
import textwrap
from datetime import datetime
from typing import Dict, Any, List, Tuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle

import ezdxf
from ezdxf import bbox
from ezdxf.addons.drawing import RenderContext, Frontend
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
from ezdxf.addons.drawing.properties import LayoutProperties

# Força plotagem monocromática (Preto e Branco) da geometria da prancha
try:
    from ezdxf.addons.drawing.config import Configuration, ColorPolicy, BackgroundPolicy
    policy_mono = getattr(ColorPolicy, "BLACK", getattr(ColorPolicy, "COLOR_ON_WHITE", None))
    DRAWING_CONFIG = Configuration(
        color_policy=policy_mono,
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
        for lay in doc.layouts:
            if lay.name.lower() != "model":
                ents = [e for e in lay if e.dxftype() != "VIEWPORT"]
                if len(ents) > 10:
                    return lay
        return doc.modelspace()

    def _draw_error_marker(self, ax, cx: float, cy: float, radius: float, color: str = "#DC2626"):
        """Desenha círculo técnico de inspeção limpo com mira de precisão."""
        target_circle = Circle(
            (cx, cy),
            radius,
            facecolor=color,
            alpha=0.08,
            edgecolor=color,
            linewidth=1.4,
            zorder=25
        )
        ax.add_patch(target_circle)

        c_size = radius * 0.45
        ax.plot([cx - c_size, cx + c_size], [cy, cy], color=color, linewidth=1.2, zorder=26)
        ax.plot([cx, cx], [cy - c_size, cy + c_size], color=color, linewidth=1.2, zorder=26)

    def _draw_verified_badge(self, ax, x: float, y: float):
        """Marcador verde técnico '✓'."""
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

    def _cluster_nearby_issues(self, inconformidades: List[Dict[str, Any]], cluster_dist: float) -> List[Dict[str, Any]]:
        """Agrupa inconformidades muito próximas para não gerar sobreposições imediatas."""
        clusters = []
        for err in inconformidades:
            pos = err.get("posicao", {})
            px = float(pos.get("x", 0.0))
            py = float(pos.get("y", 0.0))

            if px == 0.0 and py == 0.0:
                clusters.append({"is_cluster": False, "px": 0.0, "py": 0.0, "items": [err]})
                continue

            merged = False
            for c in clusters:
                if c["px"] == 0.0 and c["py"] == 0.0:
                    continue
                dist = math.hypot(px - c["px"], py - c["py"])
                if dist <= cluster_dist:
                    c["items"].append(err)
                    merged = True
                    break

            if not merged:
                clusters.append({"is_cluster": True, "px": px, "py": py, "items": [err]})
        return clusters

    def _calculate_anti_collision_pos(
        self,
        px: float,
        py: float,
        preferred_tx: float,
        preferred_ty: float,
        box_w: float,
        box_h: float,
        placed_boxes: List[Tuple[float, float, float, float]],
        safe_bounds: Tuple[float, float, float, float]
    ) -> Tuple[float, float]:
        """Calcula uma posição livre de sobreposição deslocando em degraus verticais/horizontais."""
        safe_min_x, safe_max_x, safe_min_y, safe_max_y = safe_bounds
        tx, ty = preferred_tx, preferred_ty

        step_y = box_h * 1.15
        max_attempts = 14
        direction = 1 if py <= (safe_min_y + safe_max_y) / 2.0 else -1

        for _ in range(max_attempts):
            # Define o retângulo AABB da caixa atual
            b_xmin = tx - box_w if tx < px else tx
            b_xmax = b_xmin + box_w
            b_ymin = ty - box_h if ty < py else ty
            b_ymax = b_ymin + box_h

            # Verifica colisão com todas as caixas já posicionadas
            has_collision = False
            for (oxmin, oymin, oxmax, oymax) in placed_boxes:
                if not (b_xmax < oxmin or b_xmin > oxmax or b_ymax < oymin or b_ymin > oymax):
                    has_collision = True
                    break

            if not has_collision:
                placed_boxes.append((b_xmin, b_ymin, b_xmax, b_ymax))
                return tx, ty

            # Em caso de colisão, move verticalmente
            ty += direction * step_y
            if ty > safe_max_y - box_h:
                direction = -1
                ty = preferred_ty - step_y
            elif ty < safe_min_y + box_h:
                direction = 1
                ty = preferred_ty + step_y

        # Se esgotar tentativas, aceita a melhor posição com pequeno afastamento
        placed_boxes.append((tx, ty, tx + box_w, ty + box_h))
        return tx, ty

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

        # 1. ENQUADRAMENTO EXATO
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

        # 2. RENDERIZAÇÃO EM PRETO E BRANCO TÉCNICO
        backend = MatplotlibBackend(ax)
        frontend = Frontend(ctx, backend, config=DRAWING_CONFIG) if DRAWING_CONFIG else Frontend(ctx, backend)
        frontend.draw_layout(target_layout, layout_properties=layout_props, finalize=False)

        # 3. MARCAÇÕES EM VERDE (APROVADOS)
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

        # 4. AGRUPAMENTO E POSICIONAMENTO ANTI-COLISÃO
        cluster_threshold = max(25.0, span_x * 0.035)
        clusters = self._cluster_nearby_issues(inconformidades, cluster_dist=cluster_threshold)

        marker_radius = max(8.0, span_x * 0.014)
        offset_dist_x = max(28.0, span_x * 0.045)
        offset_dist_y = max(28.0, span_y * 0.045)
        box_w = max(55.0, span_x * 0.12)
        box_h = max(22.0, span_y * 0.05)

        mid_x = (view_min_x + view_max_x) / 2.0
        mid_y = (view_min_y + view_max_y) / 2.0
        safe_bounds = (
            view_min_x + pad_x * 0.5,
            view_max_x - pad_x * 0.5,
            view_min_y + pad_y * 0.5,
            view_max_y - pad_y * 0.5
        )

        placed_boxes: List[Tuple[float, float, float, float]] = []
        callouts_count = 0

        for c in clusters:
            px, py = c["px"], c["py"]
            if px == 0.0 and py == 0.0:
                continue

            items = c["items"]
            is_crit = any(it.get("gravidade") == "CRITICA" for it in items)
            color = "#DC2626" if is_crit else "#D97706"

            # Desenha a mira técnica no ponto
            self._draw_error_marker(ax, px, py, radius=marker_radius, color=color)

            if callouts_count < 12:
                callouts_count += 1
                dx = -offset_dist_x if px > mid_x else offset_dist_x
                dy = -offset_dist_y if py > mid_y else offset_dist_y
                preferred_tx = px + dx
                preferred_ty = py + dy

                # Calcula posição sem colisão com caixas vizinhas
                tx, ty = self._calculate_anti_collision_pos(
                    px, py, preferred_tx, preferred_ty,
                    box_w, box_h, placed_boxes, safe_bounds
                )

                # Monta o texto unificado caso haja múltiplos erros no mesmo local
                if len(items) == 1:
                    it = items[0]
                    desc_quebrada = "\n".join(textwrap.wrap(it.get("descricao", ""), width=32))
                    box_text = f"[{it.get('id')}] {it.get('tipo')}\n{desc_quebrada}"
                else:
                    ids_str = ", ".join([it.get('id') for it in items[:3]])
                    if len(items) > 3:
                        ids_str += f" +{len(items)-3}"
                    box_text = f"[{ids_str}] {items[0].get('tipo')} ({len(items)}x)\nVerificar propriedades dos elementos adjacentes."

                ax.annotate(
                    box_text,
                    xy=(px, py),
                    xytext=(tx, ty),
                    ha="right" if tx < px else "left",
                    va="top" if ty < py else "bottom",
                    arrowprops=dict(
                        arrowstyle="->",
                        color=color,
                        lw=1.0,
                        shrinkA=3,
                        shrinkB=3
                    ),
                    fontsize=self.text_h_3mm,
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
