"""Genera gli screenshot del manuale (src/j_forecast_board/static/manual/img) e la posizione dei numeri (shots.json).

Uso (con il server attivo su http://127.0.0.1:8000):
    .venv\\Scripts\\python tools\\make_manual_shots.py
"""

import json
import random
from datetime import date, timedelta
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "src" / "j_forecast_board" / "static" / "manual"
IMG = OUT / "img"
IMG.mkdir(parents=True, exist_ok=True)
URL = "http://127.0.0.1:8000/"
SAMPLE = ROOT / "esempio_vendite_negozi.csv"


def make_sample_csv():
    """Dati INVENTATI: 3 negozi, 2 anni giornalieri, colonna promo; servono solo per provare il caricamento."""
    rnd = random.Random(7)
    rows = ["data;negozio;vendite;promo"]
    start = date(2023, 1, 1)
    for shop, base in (("Milano", 1800), ("Torino", 1200), ("Napoli", 950)):
        for i in range(760):
            d = start + timedelta(days=i)
            promo = 1 if rnd.random() < 0.15 else 0
            season = 1 + 0.18 * (d.month in (11, 12)) - 0.12 * (d.month == 8)
            v = base * season * (1 + 0.3 * (d.weekday() == 5) - 0.45 * (d.weekday() == 6) + 0.3 * promo) * rnd.uniform(0.93, 1.07)
            val = "" if i >= 730 else f"{v:.2f}".replace(".", ",")  # ultimi 30 giorni: solo la promo pianificata
            rows.append(f"{d:%d/%m/%Y};{shop};{val};{promo}")
    SAMPLE.write_text("\n".join(rows), encoding="utf-8")


def idle(page, t=240000):
    page.wait_for_function("() => !document.querySelector('.busy')", timeout=t)
    page.wait_for_timeout(1200)


def box(page, sel, nth=0):
    loc = page.locator(sel)
    if loc.count() <= nth:
        print("   ! marker non trovato:", sel, nth)
        return None
    return loc.nth(nth).bounding_box()


def shot(page, name, clip_sels, markers, max_h=None):
    boxes = [box(page, s) for s in clip_sels]
    boxes = [b for b in boxes if b]
    x0 = min(b["x"] for b in boxes) - 10
    y0 = min(b["y"] for b in boxes) - 10
    x1 = max(b["x"] + b["width"] for b in boxes) + 10
    y1 = max(b["y"] + b["height"] for b in boxes) + 10
    if max_h:
        y1 = min(y1, y0 + max_h)
    x0, y0 = max(0, x0), max(0, y0)
    clip = dict(x=x0, y=y0, width=x1 - x0, height=y1 - y0)
    page.screenshot(path=IMG / f"{name}.png", clip=clip, full_page=True)
    out = []
    for n, sel, *rest in markers:
        b = box(page, sel, rest[0] if rest else 0)
        if not b:
            continue
        mx = min(max(b["x"] - 22, x0 + 2), x1 - 30)  # appena fuori dall'angolo in alto a sinistra
        my = min(max(b["y"] - 18, y0 + 2), y1 - 30)
        out.append(dict(n=n, x=round((mx - x0) / clip["width"] * 100, 2), y=round((my - y0) / clip["height"] * 100, 2)))
    SHOTS[name] = dict(w=round(clip["width"]), h=round(clip["height"]), markers=out)
    print("ok", name, len(out), "numeri")


def tab(page, name):
    page.click(f"nav [data-tab={name}]")
    page.wait_for_timeout(400)
    idle(page)


SHOTS = {}
make_sample_csv()
with sync_playwright() as p:
    b = p.chromium.launch(channel="msedge", headless=True)
    cred = json.loads((ROOT / "accesso_demo.json").read_text(encoding="utf-8"))
    page = b.new_page(viewport={"width": 1440, "height": 2600},
                      http_credentials={"username": cred["utente"], "password": cred["password"]})
    page.goto(URL)
    page.wait_for_selector("#ovOut .kpis", timeout=240000)
    idle(page)

    # barra in alto (pillola di avanzamento mostrata a scopo illustrativo)
    page.evaluate("""() => { const p = document.querySelector('#jobPill'); p.hidden = false;
        p.textContent = '⏳ Timestral-209M · closed = missing on 1,115 series 45% · ~12 min left'; }""")
    shot(page, "barra", ["header"], [(1, "#nav"), (2, "#dsSel"), (3, "#serSel"), (4, "#serNext"), (5, "#varSel"),
                                    (6, "#horizon"), (7, "#context"), (8, "#jobPill")])
    page.evaluate("() => { document.querySelector('#jobPill').hidden = true; }")

    # OVERVIEW (Rossmann)
    shot(page, "overview_kpi", ["#ovOut > .card:nth-child(1)"],
         [(1, "#ovOut .summary"), (2, "#ovOut .notes"), (3, ".kpi", 0), (4, ".kpi", 1), (5, ".kpi", 2), (6, ".kpi", 3), (7, ".kpi", 4), (8, ".kpi", 5)])
    shot(page, "overview_classifica", ["#ovOut > .card:nth-child(2)"],
         [(1, "#ovOut tr.best"), (2, "#ovOut > .card:nth-child(2) tbody tr", 1), (3, "#ovOut > .card:nth-child(2) thead"), (4, "#ovOut td.bestcell"), (5, "#ovOut .runbar")])
    shot(page, "overview_grafici", ["#ovOut .grid3"],
         [(i + 1, "#ovOut .grid3 > .card h3", i) for i in range(6)])

    # SERIES (negozio 1)
    tab(page, "series")
    page.wait_for_selector("#sePlot .main-svg")
    idle(page)
    shot(page, "serie", ["#tab-series .tool", "#seChips", "#seCard"],
         [(1, "#tab-series label:has(#seBaseline)"), (2, "#tab-series [data-view=all]"), (3, "#tab-series [data-view=recent]"), (4, "#seCsv"),
          (5, "#seChips"), (6, "#sePlot .legend"), (7, "#sePlot .annotation", 0), (8, "#sePlot .annotation", 1), (9, "#sePlot .rangeslider-container")])
    shot(page, "serie_covariate", ["#covCard", "#seTable"], [(1, "#covPlot"), (2, "#seTable tr.best")])

    # TOTAL
    tab(page, "total")
    page.wait_for_selector("#toPlot .main-svg")
    idle(page)
    shot(page, "totale", ["#toChips", "#toCard", "#toTable"], [(1, "#toPlot .legend"), (2, "#toPlot .annotation", 0), (3, "#toTable tbody tr")])

    # EXPLORE
    tab(page, "explore")
    page.click("#rpRun")
    idle(page)
    page.eval_on_selector("#rpSlider", "el => { el.value = 28; el.dispatchEvent(new Event('input')); }")
    page.check("#rpReveal")
    page.wait_for_timeout(800)
    shot(page, "esplora", ["#tab-explore .tool", "#rpChips", "#rpCard", "#rpErr"],
         [(1, "#rpFrames"), (2, "#rpSpan"), (3, "#rpRun"), (4, "label:has(#rpReveal)"), (5, "label:has(#rpFollow)"), (6, "#rpSpeed"),
          (7, "#rpPlay"), (8, "#rpSlider"), (9, "#rpErr")])

    # LIVE
    tab(page, "live")
    page.wait_for_selector("#lvPlot .main-svg")
    page.click("#lvBack")
    idle(page)
    shot(page, "live", ["#tab-live .tool", "#lvChips", "#lvCard"],
         [(1, "#lvDate"), (2, "#lvRun"), (3, "#lvEnd"), (4, "#lvBack"), (5, "#lvRand"), (6, "#lvChips"), (7, "#lvPlot .annotation")])

    # WHAT-IF (negozio 1, promo tutti i giorni)
    tab(page, "whatif")
    page.click("#wiPresets button >> nth=0")
    idle(page)
    shot(page, "whatif", ["#wiCard", "#wiChips", "#wiPlotCard"],
         [(1, "#wiPresets"), (2, ".wi-row .mode", 3), (3, ".wi-row .val", 3), (4, ".wi-row .rng", 3), (5, "#wiRun"), (6, "#wiReset"),
          (7, "#wiChips"), (8, "#wiPlot .legend")])

    # SPLIT TEST (Germania, 2 anni -> 3 anni)
    page.select_option("#dsSel", "germany")
    page.wait_for_timeout(800)
    tab(page, "split")
    page.click("[data-sp='2,3']")
    idle(page)
    shot(page, "split", ["#tab-split .tool", "#spChips", "#spCard"],
         [(1, "#spStart"), (2, "#spSplit"), (3, "#spEnd"), (4, "#spRun"), (5, "[data-sp='2,3']"), (6, "label:has(#spBase)"),
          (7, "#spChips"), (8, "#spPlot .annotation", 1)])
    shot(page, "split_analisi", ["#tab-split .grid3", "#spLb"], [(1, "#spPer"), (2, "#spHow"), (3, "#spLb tr.best")])
    shot(page, "split_tabella", ["#spTable"], [(1, "#spTable th", 4), (2, "#spTable th", 6)], max_h=330)

    # ANOMALIES (Bike sharing)
    page.select_option("#dsSel", "bike")
    page.wait_for_timeout(800)
    tab(page, "anomalies")
    page.click("#adRun")
    idle(page)
    shot(page, "anomalie", ["#tab-anomalies .tool", "#adChips", "#adCard", "#adTable"],
         [(1, "#adStep"), (2, "#adWin"), (3, "#adLevel"), (4, "#adRun"), (5, "#adChips"), (6, "#adPlot .scatterlayer .trace:last-child .point", 0),
          (7, "#adTable table")], max_h=1050)

    # YOUR DATA (file di esempio)
    tab(page, "upload")
    page.set_input_files("#upFile", str(SAMPLE))
    idle(page)
    page.select_option("#upRoles .r[data-c=promo] .role", "known")
    shot(page, "dati", ["#upCard"],
         [(1, "#drop"), (2, "#upForm table"), (3, "#upName"), (4, "#upDate"), (5, "#upId"), (6, "#upTarget"), (7, "#upRoles"),
          (8, "#upFreq"), (9, "#upSeason"), (10, "#upAgg"), (11, "#upCal"), (12, "#upCountry"), (13, "#upGo")])
    b.close()

(OUT / "shots.json").write_text(json.dumps(SHOTS, indent=1), encoding="utf-8")
print("Salvato", OUT / "shots.json")
