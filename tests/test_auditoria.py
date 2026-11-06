"""Regressão: desenhos gerados com erros conhecidos devem ser detectados, e o desenho limpo aprovado.

Rodar a partir da raiz:  python -m pytest tests
"""
import os
import sys

import pytest

BACKEND = os.path.join(os.path.dirname(__file__), "..", "backend")
sys.path.insert(0, os.path.abspath(BACKEND))

import ezdxf

def build(path, with_paper=False, clean=False):
    doc = ezdxf.new("R2018", setup=True)
    for n in ("CONTORNO", "COTAS", "TEXTOS", "FUROS", "CARIMBO"):
        doc.layers.add(n)
    msp = doc.modelspace()
    # moldura/carimbo (polilinha que NÃO é chapa)
    msp.add_lwpolyline([(-50,-50),(791,-50),(791,544),(-50,544)], close=True, dxfattribs={"layer":"CARIMBO"})
    # chapa 300x200
    msp.add_lwpolyline([(0,0),(300,0),(300,200),(0,200)], close=True, dxfattribs={"layer":"CONTORNO"})
    holes = [(50,50),(250,50),(50,150),(250,150)]          # ok
    if not clean:
        holes += [(10,100), (150,100), (165,100)]           # borda; passo curto
    for h in holes:
        msp.add_circle(h, 9, dxfattribs={"layer":"FUROS"})   # Ø18
    msp.add_circle((50,50), 15, dxfattribs={"layer":"FUROS"})  # arruela concêntrica
    # balões de posição (Ø10) perto da lista, fora da chapa
    for i in range(3):
        msp.add_circle((420, 330 - i*12), 5, dxfattribs={"layer":"TEXTOS"})
        msp.add_text(str(i+1), height=3, dxfattribs={"layer":"TEXTOS"}).set_placement((420, 330-i*12), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER)
    # cotas
    d = msp.add_linear_dim(base=(0,-20), p1=(0,0), p2=(300,0), dxfattribs={"layer":"COTAS"}); d.render()
    txt = "300" if clean else "350"
    d = msp.add_linear_dim(base=(-20,0), p1=(0,0), p2=(0,200), text=("<>" if clean else "250"), angle=90, dxfattribs={"layer":"COTAS"}); d.render()
    # lista de material
    T = lambda s,x,y: msp.add_text(s, height=3.5, dxfattribs={"layer":"TEXTOS"}).set_placement((x,y))
    T("LISTA DE MATERIAL", 450, 360)
    for x,h in zip((450,470,500,620,660),("POS","QTD","DESCRIÇÃO","PESO UN.","PESO TOT.")): T(h,x,345)
    rows = [("1","2","CH 6,35x200x300","2,99","5,98"),
            ("2","4","CH 9,5x100x150","1,12","4,47"),
            ("3","1","CH 12,5x150x150","2,21","2,21" if clean else "3,50")]
    for i,r in enumerate(rows):
        for x,v in zip((450,470,500,620,660), r): T(v,x,330-i*12)
    T("PESO TOTAL: " + ("12,66" if clean else "15,00") + " kg", 600, 290)
    notes = ["NOTAS:", "1. DIMENSÕES EM MILÍMETROS.", "2. MATERIAL: ASTM A36.",
             "3. SOLDAGEM CONFORME AWS D1.1, ELETRODO E7018.", "4. REMOVER REBARBAS E CANTOS VIVOS.",
             "5. TOLERÂNCIAS GERAIS CONFORME ISO 2768-m.", "6. PINTURA: FUNDO EPÓXI 120 µm."]
    if not clean:
        notes[3] = "3. SOLDAGEM CONFORME AWS D1.1, ELETRODO E6013. SOLDA FILETE 2MM."
        notes[1] = "1. DIMENCOES EM MILIMETROS."
        notes.pop()
    for i,n in enumerate(notes): T(n, 20, 500 - i*8)
    if not clean:
        msp.add_line((0,250),(100,250))                       # layer 0
        for i in range(40):                                    # overrides de cor em massa
            msp.add_line((0,260+i*2),(100,260+i*2), dxfattribs={"layer":"CONTORNO","color":1})
    if with_paper:
        ps = doc.layout("Layout1")
        ps.add_lwpolyline([(0,0),(841,0),(841,594),(0,594)], close=True, dxfattribs={"layer":"CARIMBO"})
        for i in range(12): ps.add_text(f"CAMPO {i}", height=3, dxfattribs={"layer":"CARIMBO"}).set_placement((600, 20+i*6))
        ps.add_viewport(center=(420,297), size=(800,560), view_center_point=(370,247), view_height=620)
    doc.saveas(path)



@pytest.fixture(scope="module")
def client(tmp_path_factory):
    os.chdir(tmp_path_factory.mktemp("work"))
    from fastapi.testclient import TestClient
    import main
    return TestClient(main.app)


def audit(client, path):
    with open(path, "rb") as f:
        r = client.post("/audit", files={"file": (os.path.basename(path), f)})
    assert r.status_code == 200, r.text
    return r.json()


def test_desenho_limpo_aprovado(client, tmp_path):
    p = tmp_path / "limpo.dxf"
    build(str(p), clean=True)
    d = audit(client, str(p))
    assert d["status_geral"] == "APROVADO", d["inconformidades"]
    assert d["detalhes_bom"]["peso_calculado_kg"] == pytest.approx(12.66)


@pytest.mark.parametrize("with_paper", [False, True])
def test_erros_detectados(client, tmp_path, with_paper):
    p = tmp_path / "erros.dxf"
    build(str(p), with_paper=with_paper)
    d = audit(client, str(p))
    tipos = {e["tipo"] for e in d["inconformidades"]}
    esperados = {
        "Cota Sobrescrita (Override)", "Peso de Item Divergente", "Erro na Soma da Lista de Materiais",
        "Espaçamento Insuficiente entre Furos", "Furo Próximo da Borda da Chapa",
        "Perna de Solda Abaixo do Mínimo", "Proteção Superficial", "Erro Ortográfico Técnico",
        "Especificação Inadequada de Solda", "Objeto na Layer 0", "Propriedade Fora de ByLayer",
    }
    assert esperados <= tipos
    # Arruela concêntrica e balões não podem virar furos
    assert sum(e["tipo"] == "Espaçamento Insuficiente entre Furos" for e in d["inconformidades"]) == 1
    assert client.get(d["pdf_url"]).status_code == 200


def test_download_bloqueia_caminho(client):
    assert client.get("/download/..%2Fmain.py").status_code == 404
