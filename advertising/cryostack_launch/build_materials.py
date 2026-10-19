"""Build the CryoStack launch advert and editable overview deck."""
from __future__ import annotations

import base64
import html
import shutil
import subprocess
import textwrap
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
ASSETS = OUT / "assets"
RENDERS = OUT / "slides_rendered"
LOGO_SRC = ROOT / "icesee_jupyter_book" / "cryostack.png"
CONNECTOR_SRC = ROOT / "icesee_hpc_connector" / "assets" / "cryostack-connector-512.png"
RESULT_SRC = ROOT / "icesee_jupyter_book" / "icesee_jupyter_notebooks" / "users" / "48daa81ee695409f9a63ae133bf22d42-7ec81b4cd674" / ".cryostack" / "runs" / "ba6537bb-c5fe-451b-98cf-47b453c84e3d" / "cache" / "outputs" / "figures" / "stressbalance_velocity.png"

NAVY = "082B59"
BLUE = "087EEB"
CYAN = "24B8E8"
PALE = "EEF7FC"
INK = "172033"
MUTED = "5E7187"
WHITE = "FFFFFF"
GREEN = "177A55"


def data_uri(path: Path) -> str:
    mime = "image/png"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


def prepare_assets() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    RENDERS.mkdir(parents=True, exist_ok=True)
    shutil.copy2(LOGO_SRC, ASSETS / "cryostack-logo-canonical.png")
    shutil.copy2(CONNECTOR_SRC, ASSETS / "cryostack-connector.png")
    shutil.copy2(RESULT_SRC, ASSETS / "issm-stressbalance-velocity.png")
    im = Image.open(LOGO_SRC).convert("RGB")
    im.crop((105, 30, 1435, 985)).save(ASSETS / "cryostack-logo-cropped.png", quality=95)


def svg_lines(lines: list[str], x: int, y: int, css: str, line_height: int) -> str:
    spans = "".join(
        f'<tspan x="{x}" dy="{0 if i == 0 else line_height}">{escape(line)}</tspan>'
        for i, line in enumerate(lines)
    )
    return f'<text x="{x}" y="{y}" class="{css}">{spans}</text>'


def advert_svg() -> str:
    logo = data_uri(ASSETS / "cryostack-logo-cropped.png")
    cards = [
        ("01", "Configure", "Choose ISSM or Icepack examples and set model and run parameters in the browser."),
        ("02", "Connect", "Use the CryoStack Connector with your own institutional HPC identity."),
        ("03", "Launch + monitor", "Configure Slurm resources, submit jobs, inspect status, and tail run logs."),
        ("04", "Inspect + retrieve", "Preview supported results and download managed results and figures."),
        ("05", "Assimilate", "Configure ICESEE ensemble data-assimilation workflows through its dedicated application."),
        ("06", "Learn", "Follow application Getting Started guides, user manuals, and technical resources."),
    ]
    card_xml = []
    for i, (num, title, body) in enumerate(cards):
        col, row = i % 2, i // 2
        x, y = 90 + col * 520, 780 + row * 235
        card_xml.append(f'''<g transform="translate({x},{y})">
          <rect width="480" height="195" rx="20" fill="#fff" stroke="#D6E5F0"/>
          <circle cx="48" cy="48" r="25" fill="#{BLUE}"/><text x="48" y="56" text-anchor="middle" class="num">{num}</text>
          <text x="88" y="54" class="cardtitle">{title}</text>
          {svg_lines(textwrap.wrap(body, width=48), 30, 112, 'body', 25)}
        </g>''')
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1240" height="1754" viewBox="0 0 1240 1754">
    <style>
      text{{font-family:'DejaVu Sans',Arial,sans-serif;fill:#{INK}}}.eyebrow{{font-size:18px;font-weight:700;letter-spacing:2px;fill:#{BLUE}}}
      .title{{font-size:56px;font-weight:700;fill:#{NAVY}}}.tag{{font-size:32px;font-weight:600;fill:#{INK}}}.strap{{font-size:19px;font-weight:700;letter-spacing:1px;fill:#{BLUE}}}
      .intro{{font-size:20px;fill:#{MUTED}}}.num{{font-size:14px;font-weight:700;fill:#fff}}.cardtitle{{font-size:22px;font-weight:700;fill:#{NAVY}}}
      .body{{font-size:16px;fill:#{MUTED}}}.who{{font-size:19px;fill:#{INK}}}.cta{{font-size:32px;font-weight:700;fill:#fff}}.url{{font-size:20px;fill:#fff}}
    </style>
    <rect width="1240" height="1754" fill="#F8FBFD"/><rect width="1240" height="20" fill="#{BLUE}"/>
    <image href="{logo}" x="70" y="60" width="300" height="260" preserveAspectRatio="xMidYMid meet"/>
    <text x="405" y="120" class="eyebrow">CRYOSPHERE COMPUTING PLATFORM</text>
    <text x="405" y="190" class="title">CryoStack</text><text x="405" y="245" class="tag">Ice-sheet modeling</text><text x="405" y="285" class="tag">without the setup barrier.</text>
    <rect x="70" y="345" width="1100" height="78" rx="18" fill="#{NAVY}"/><text x="620" y="395" text-anchor="middle" class="strap">CONFIGURE  •  LAUNCH  •  MONITOR  •  VISUALIZE  •  DOWNLOAD</text>
    {svg_lines(['CryoStack provides browser-based access to supported computational ice-sheet simulations and ensemble', 'data-assimilation workflows on remote and Slurm-managed HPC systems.', 'Researchers work through guided applications while computations continue to use their own institutional HPC', 'identity and configured scientific software environments.'], 90, 500, 'intro', 34)}
    {''.join(card_xml)}
    <text x="90" y="1515" class="eyebrow">WHO IS IT FOR?</text>
    <text x="90" y="1556" class="who">Ice-sheet researchers  •  Students and educators  •  Observational scientists</text>
    <text x="90" y="1590" class="who">New computational modelers  •  Teams building reproducible supported workflows</text>
    <rect x="0" y="1630" width="1240" height="124" fill="#{NAVY}"/><text x="80" y="1685" class="cta">Try CryoStack</text><text x="80" y="1724" class="url">cryostack.eas.gatech.edu</text>
    <text x="1160" y="1684" text-anchor="end" class="url">Documentation</text><text x="1160" y="1722" text-anchor="end" class="url">cryostack.eas.gatech.edu/documentation/</text>
    </svg>'''


def render_svg(svg: str, svg_path: Path, png_path: Path, pdf_path: Path | None = None, width: int | None = None) -> None:
    svg_path.write_text(svg, encoding="utf-8")
    cmd = ["rsvg-convert", str(svg_path), "-o", str(png_path)]
    if width:
        cmd[1:1] = ["-w", str(width)]
    subprocess.run(cmd, check=True)
    if pdf_path:
        subprocess.run(["rsvg-convert", "-f", "pdf", str(svg_path), "-o", str(pdf_path)], check=True)


def slide_svg(title: str, subtitle: str = "", body: list[str] | None = None, *, image: Path | None = None, flow: list[str] | None = None, cards: list[tuple[str, list[str]]] | None = None, cta: bool = False) -> str:
    image_xml = ""
    if image:
        image_xml = f'<image href="{data_uri(image)}" x="1050" y="145" width="740" height="760" preserveAspectRatio="xMidYMid meet"/>'
    flow_xml = ""
    if flow:
        x0, y = 125, 485
        bw = 1420 / len(flow) - 25
        for i, label in enumerate(flow):
            x = x0 + i * (bw + 25)
            flow_xml += f'<rect x="{x}" y="{y}" width="{bw}" height="105" rx="18" fill="#{PALE}" stroke="#{CYAN}"/><text x="{x+bw/2}" y="{y+62}" text-anchor="middle" class="flow">{escape(label)}</text>'
            if i < len(flow)-1:
                flow_xml += f'<text x="{x+bw+12}" y="{y+65}" text-anchor="middle" class="arrow">→</text>'
    cards_xml = ""
    if cards:
        for i, (head, text) in enumerate(cards):
            if len(cards) > 3:
                x, y, width, height = 105 + (i % 2) * 855, 300 + (i // 2) * 300, 800, 250
            else:
                x, y, width, height = 105 + i * 520, 350, 465, 340
            cards_xml += f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="24" fill="#fff" stroke="#D8E7F1"/><rect x="{x}" y="{y}" width="{width}" height="12" rx="6" fill="#{[BLUE,CYAN,GREEN,NAVY][i%4]}"/><text x="{x+34}" y="{y+70}" class="cardhead">{escape(head)}</text>{svg_lines(text, x+34, y+118, "cardbody", 32)}'
    cta_xml = (f'<rect x="105" y="610" width="1710" height="245" rx="28" fill="#{NAVY}"/>'
               '<text x="160" y="680" class="ctabig">cryostack.eas.gatech.edu</text>'
               '<text x="160" y="727" class="ctasmall">Documentation  ·  cryostack.eas.gatech.edu/documentation/</text>'
               '<text x="160" y="765" class="ctasmall">Getting Started  ·  /applications/icesheets/getting_started.html</text>'
               '<text x="160" y="803" class="ctasmall">User Manual  ·  /applications/icesheets/user_manual.html     Developer Guide  ·  /docs/developer_guide.html</text>') if cta else ""
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080"><style>
    text{{font-family:'DejaVu Sans',Arial,sans-serif}}.kicker{{font-size:18px;font-weight:700;letter-spacing:2px;fill:#{BLUE}}}.title{{font-size:52px;font-weight:700;fill:#{NAVY}}}.subtitle{{font-size:26px;fill:#{MUTED}}}.body{{font-size:25px;fill:#{INK}}}.flow{{font-size:19px;font-weight:700;fill:#{NAVY}}}.arrow{{font-size:30px;fill:#{BLUE}}}.cardhead{{font-size:31px;font-weight:700;fill:#{NAVY}}}.cardbody{{font-size:21px;fill:#{MUTED}}}.ctabig{{font-size:38px;font-weight:700;fill:#fff}}.ctasmall{{font-size:22px;fill:#fff}}</style>
    <rect width="1920" height="1080" fill="#F8FBFD"/><rect width="1920" height="16" fill="#{BLUE}"/><text x="105" y="78" class="kicker">CRYOSTACK</text><text x="105" y="155" class="title">{escape(title)}</text><text x="105" y="208" class="subtitle">{escape(subtitle)}</text>
    {svg_lines(body or [], 105, 300, 'body', 42)}{image_xml}{flow_xml}{cards_xml}{cta_xml}<text x="1815" y="1035" text-anchor="end" class="kicker">ICCL + PGSL · GEORGIA TECH</text></svg>'''


def slides() -> list[str]:
    logo = ASSETS / "cryostack-logo-cropped.png"
    connector = ASSETS / "cryostack-connector.png"
    result = ASSETS / "issm-stressbalance-velocity.png"
    return [
        slide_svg("CryoStack", "From computational code to an accessible scientific gateway", ["Browser-based access to supported ice-sheet modeling,", "data-assimilation, and cryosphere-data workflows."], image=logo),
        slide_svg("Ice-sheet models are powerful — but difficult to get running", "The setup remains real; CryoStack provides a supported path through it.", ["Dependencies, compilation, HPC configuration, schedulers, and", "model-specific workflows can slow down students, observational scientists,", "and researchers entering computational ice-sheet modeling."], flow=["Scientific model", "Dependencies", "Compilation", "HPC setup", "Slurm", "Workflow", "Simulation"]),
        slide_svg("From computational code to a scientific gateway", "Users retain their own institutional HPC identity and credentials.", ["Configure through a browser application. Pair the CryoStack Connector.", "Launch supported computations through Slurm. Monitor the run.", "Inspect, visualize, and download managed results."], flow=["Research code", "CryoStack app", "Connector", "HPC / Slurm", "Computation", "Results"]),
        slide_svg("1. Set up your account and HPC resource", "Personal resource settings remain scoped to your CryoStack account.", cards=[("Sign in", ["Open CryoStack and sign in with", "your account before starting a", "persistent modeling workspace."]), ("Choose the resource", ["Select the configured HPC resource", "and access mode. PACE/Phoenix", "supports Connector or direct access."]), ("Enter your details", ["Provide your HPC username, remote", "working directory, Slurm allocation,", "and notification email as required."])]),
        slide_svg("2. Pair the CryoStack Connector", "The Connector uses your workstation and your institutional HPC access.", ["Stay connected to any institutionally required VPN.", "Open Connector Setup from CryoLauncher, install the published connector,", "launch it, enter the one-time pairing code, and confirm Connected status."], flow=["Connector Setup", "Download", "Launch", "Pairing code", "Connected"]),
        slide_svg("3. Configure the SquareIceShelf example", "A first supported ISSM workflow in CryoLauncher", cards=[("Run settings", ["Choose Basic mode and Remote", "execution. Select ISSM as the", "modeling application."]), ("Example", ["Select SquareIceShelf from the", "discovered ISSM examples and", "confirm the detected run target."]), ("HPC resources", ["Review backend, partition, wall time,", "nodes, tasks, memory, and Slurm", "allocation before submission."])]),
        slide_svg("4. Launch and follow the run", "CryoLauncher keeps submission, monitoring, and outputs in one workspace.", ["Review the Run Plan, then select Run.", "CryoStack stages the example and submits it through the paired Connector.", "Use the returned Slurm job ID to follow status and tail the Run Log."], flow=["Run Plan", "Run", "Connector", "Slurm job", "Run Log", "Results"]),
        slide_svg("Explore CryoStack", "Distinct applications connected through one platform", cards=[("CryoLauncher", ["Configure and launch supported ISSM", "and Icepack modeling workflows on", "remote and Slurm-managed systems."]), ("ICESEE", ["Configure ensemble data-assimilation", "workflows for supported numerical", "models and filtering methods."]), ("LIVIST", ["Explore Antarctic ice-sheet temperature", "products inferred from radar and", "constrained by borehole observations."]), ("Frozen Legacies", ["Explore historical Antarctic airborne", "radar surveys, flight tracks, and", "processed campaign observations."])]),
        slide_svg("Configure → Launch → Monitor → Visualize → Download", "One managed workflow from experiment setup to retrieved results", ["Browser controls expose application selection, model configuration,", "Slurm resources, status, and logs. The actual ISSM velocity result", "shown here was generated by a managed CryoStack run."], image=result),
        slide_svg("Try CryoStack", "Designed to make supported modeling workflows easier to access, reproduce, and share.", ["Ice, Climate and Coasts Lab (ICCL) and", "Polar Geophysics and Sea Level Lab (PGSL)", "Georgia Institute of Technology"], image=logo, cta=True),
    ]


def pptx_text_shape(shape_id: int, text: str, x: int, y: int, w: int, h: int, size: int, color: str, bold: bool = False) -> str:
    runs = ''.join(f'<a:r><a:rPr lang="en-US" sz="{size*100}" b="{1 if bold else 0}"><a:solidFill><a:srgbClr val="{color}"/></a:solidFill></a:rPr><a:t>{escape(line)}</a:t></a:r>' + ('<a:br/>' if i < len(text.splitlines())-1 else '') for i,line in enumerate(text.splitlines()))
    return f'<p:sp><p:nvSpPr><p:cNvPr id="{shape_id}" name="Text {shape_id}"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr><p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{w}" cy="{h}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/></p:spPr><p:txBody><a:bodyPr wrap="square"/><a:lstStyle/><a:p>{runs}<a:endParaRPr lang="en-US"/></a:p></p:txBody></p:sp>'


def build_pptx(slide_pngs: list[Path]) -> None:
    pptx = OUT / "CryoStack_Overview.pptx"
    count = len(slide_pngs)
    content = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Default Extension="png" ContentType="image/png"/><Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/><Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/><Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/><Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>''' + ''.join(f'<Override PartName="/ppt/slides/slide{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>' for i in range(1,count+1)) + '</Types>'
    root_rels = '''<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/></Relationships>'''
    pres = '''<?xml version="1.0" encoding="UTF-8"?><p:presentation xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"><p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst><p:sldIdLst>''' + ''.join(f'<p:sldId id="{255+i}" r:id="rId{i+1}"/>' for i in range(1,count+1)) + '''</p:sldIdLst><p:sldSz cx="12192000" cy="6858000" type="screen16x9"/><p:notesSz cx="6858000" cy="9144000"/></p:presentation>'''
    pres_rels = '''<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="slideMasters/slideMaster1.xml"/>''' + ''.join(f'<Relationship Id="rId{i+1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide{i}.xml"/>' for i in range(1,count+1)) + '</Relationships>'
    master = '''<?xml version="1.0" encoding="UTF-8"?><p:sldMaster xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"><p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/></p:spTree></p:cSld><p:sldLayoutIdLst><p:sldLayoutId id="1" r:id="rId1"/></p:sldLayoutIdLst><p:txStyles><p:titleStyle/><p:bodyStyle/><p:otherStyle/></p:txStyles></p:sldMaster>'''
    master_rels = '''<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="../theme/theme1.xml"/></Relationships>'''
    layout = '''<?xml version="1.0" encoding="UTF-8"?><p:sldLayout xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" type="blank"><p:cSld name="Blank"><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/></p:spTree></p:cSld></p:sldLayout>'''
    layout_rels = '''<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="../slideMasters/slideMaster1.xml"/></Relationships>'''
    theme = '''<?xml version="1.0" encoding="UTF-8"?><a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="CryoStack"><a:themeElements><a:clrScheme name="CryoStack"><a:dk1><a:srgbClr val="082B59"/></a:dk1><a:lt1><a:srgbClr val="FFFFFF"/></a:lt1><a:dk2><a:srgbClr val="172033"/></a:dk2><a:lt2><a:srgbClr val="F8FBFD"/></a:lt2><a:accent1><a:srgbClr val="087EEB"/></a:accent1><a:accent2><a:srgbClr val="24B8E8"/></a:accent2><a:accent3><a:srgbClr val="177A55"/></a:accent3><a:accent4><a:srgbClr val="5E7187"/></a:accent4><a:accent5><a:srgbClr val="D6E5F0"/></a:accent5><a:accent6><a:srgbClr val="EEF7FC"/></a:accent6><a:hlink><a:srgbClr val="087EEB"/></a:hlink><a:folHlink><a:srgbClr val="082B59"/></a:folHlink></a:clrScheme><a:fontScheme name="DejaVu Sans"><a:majorFont><a:latin typeface="DejaVu Sans"/></a:majorFont><a:minorFont><a:latin typeface="DejaVu Sans"/></a:minorFont></a:fontScheme><a:fmtScheme name="CryoStack"><a:fillStyleLst/><a:lnStyleLst/><a:effectStyleLst/><a:bgFillStyleLst/></a:fmtScheme></a:themeElements></a:theme>'''
    editable = [
        ("CryoStack", "Ice-sheet modeling without the setup barrier"),
        ("The Problem", "Dependencies → Compilation → HPC configuration → Slurm → Model workflow → Simulation"),
        ("From browser to HPC", "Browser → CryoStack → CryoStack Connector → HPC / Slurm → Ice-sheet model → Results"),
        ("Set up your account", "Sign in → Select resource → Enter personal HPC settings"),
        ("Pair the Connector", "Connector Setup → Download → Launch → Pair → Connected"),
        ("Configure SquareIceShelf", "Basic → Remote → ISSM → SquareIceShelf → HPC resources"),
        ("Launch and follow", "Run Plan → Run → Connector → Slurm job → Run Log → Results"),
        ("Explore CryoStack", "CryoLauncher  |  ICESEE  |  LIVIST  |  Frozen Legacies"),
        ("One managed workflow", "Configure → Launch → Monitor → Visualize → Download"),
        ("Try CryoStack", "cryostack.eas.gatech.edu\ncryostack.eas.gatech.edu/documentation/"),
    ]
    with zipfile.ZipFile(pptx, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content); z.writestr("_rels/.rels", root_rels)
        z.writestr("ppt/presentation.xml", pres); z.writestr("ppt/_rels/presentation.xml.rels", pres_rels)
        z.writestr("ppt/slideMasters/slideMaster1.xml", master); z.writestr("ppt/slideMasters/_rels/slideMaster1.xml.rels", master_rels)
        z.writestr("ppt/slideLayouts/slideLayout1.xml", layout); z.writestr("ppt/slideLayouts/_rels/slideLayout1.xml.rels", layout_rels); z.writestr("ppt/theme/theme1.xml", theme)
        for i, (png, texts) in enumerate(zip(slide_pngs, editable), 1):
            pic = f'<p:pic><p:nvPicPr><p:cNvPr id="2" name="Rendered design"/><p:cNvPicPr/><p:nvPr/></p:nvPicPr><p:blipFill><a:blip r:embed="rId2"/><a:stretch><a:fillRect/></a:stretch></p:blipFill><p:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="12192000" cy="6858000"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr></p:pic>'
            # Editable title and summary are placed off-canvas in the Selection Pane;
            # the complete designed slide remains pixel-stable across PowerPoint versions.
            edit = pptx_text_shape(3, texts[0], 12200000, 0, 4000000, 800000, 30, NAVY, True) + pptx_text_shape(4, texts[1], 12200000, 900000, 6000000, 1800000, 18, INK)
            slide = f'<?xml version="1.0" encoding="UTF-8"?><p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"><p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/>{pic}{edit}</p:spTree></p:cSld></p:sld>'
            rels = '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/slide%d.png"/></Relationships>' % i
            z.writestr(f"ppt/slides/slide{i}.xml", slide); z.writestr(f"ppt/slides/_rels/slide{i}.xml.rels", rels); z.write(png, f"ppt/media/slide{i}.png")


def main() -> None:
    prepare_assets()
    render_svg(advert_svg(), OUT / "CryoStack_Advert.svg", OUT / "CryoStack_Advert.png", OUT / "CryoStack_Advert.pdf", width=2480)
    rendered = []
    for i, svg in enumerate(slides(), 1):
        svg_path = RENDERS / f"slide-{i}.svg"
        png_path = RENDERS / f"slide-{i}.png"
        render_svg(svg, svg_path, png_path, width=1920)
        rendered.append(png_path)
    build_pptx(rendered)
    print("CryoStack advertising materials built")


if __name__ == "__main__":
    main()
