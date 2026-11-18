#!/usr/bin/env python3
"""Convert a CEWE photo book (.mcf) to PDF.

Renders each spread (cover + double pages) as one PDF page, using the photos in
the *_mcf-Dateien folder. CEWE's own design backgrounds/cliparts are not
available outside the CEWE software, so backgrounds are rendered white.

Usage: mcf2pdf.py book.mcf [out.pdf] [--dpi 300] [--single]
"""
import argparse
import html
import io
import os
import re
import sys
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

from PIL import Image, ImageOps
from reportlab.lib.colors import Color
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph

Image.MAX_IMAGE_PIXELS = None
U = 72 / 254.0  # MCF units are 0.1 mm -> points

def _font_candidates():
    """(dir, [regular, bold, italic, bolditalic]) sets to try, in order."""
    here = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    lib = ["LiberationSans-Regular.ttf", "LiberationSans-Bold.ttf",
           "LiberationSans-Italic.ttf", "LiberationSans-BoldItalic.ttf"]
    windir = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    return [
        (os.path.join(here, "fonts"), lib),  # bundled with the app / next to the script
        (windir, ["arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"]),
        ("/usr/share/fonts/liberation-sans-fonts", lib),
        ("/usr/share/fonts/truetype/liberation", lib),
        ("/Library/Fonts", ["Arial.ttf", "Arial Bold.ttf", "Arial Italic.ttf", "Arial Bold Italic.ttf"]),
    ]


def register_fonts():
    for d, files in _font_candidates():
        paths = [os.path.join(d, f) for f in files]
        if not all(os.path.exists(p) for p in paths):
            continue
        try:
            for name, p in zip(("Sans", "Sans-B", "Sans-I", "Sans-BI"), paths):
                pdfmetrics.registerFont(TTFont(name, p))
            pdfmetrics.registerFontFamily("Sans", normal="Sans", bold="Sans-B", italic="Sans-I", boldItalic="Sans-BI")
            return "Sans"
        except Exception:
            continue
    return "Helvetica"  # built-in PDF font; no umlaut problems with Latin-1 text


FONT = register_fonts()


def argb(s):
    """'#aarrggbb' or decimal ARGB int -> reportlab Color or None if transparent."""
    if s is None:
        return None
    v = int(s[1:], 16) if s.startswith("#") else int(s)
    a = (v >> 24) & 255
    if a == 0:
        return None
    return Color(((v >> 16) & 255) / 255, ((v >> 8) & 255) / 255, (v & 255) / 255, a / 255)


def parse_style(s):
    d = {}
    for part in (s or "").split(";"):
        if ":" in part:
            k, v = part.split(":", 1)
            d[k.strip()] = v.strip()
    return d


def px(v, default=0.0):
    m = re.match(r"(-?[\d.]+)", v or "")
    return float(m.group(1)) if m else default


class QtRich(HTMLParser):
    """Turn Qt rich text into a list of paragraphs (markup, align, size, margins)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.paras = []
        self.stack = []  # style dicts
        self.body = {"size": 12.0, "bold": False, "italic": False, "color": "#000000", "underline": False}
        self.cur = None

    def style(self):
        st = dict(self.body)
        for s in self.stack:
            st.update(s)
        return st

    def _apply(self, css):
        out = {}
        if "font-size" in css:
            out["size"] = px(css["font-size"], 12)
        if "font-weight" in css:
            out["bold"] = int(px(css["font-weight"], 400)) >= 600
        if "font-style" in css:
            out["italic"] = css["font-style"] == "italic"
        if "color" in css:
            out["color"] = css["color"]
        if "text-decoration" in css:
            out["underline"] = "underline" in css["text-decoration"]
        return out

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        css = parse_style(a.get("style"))
        if tag == "body":
            self.body.update(self._apply(css))
        elif tag == "p":
            self.cur = {"runs": [], "align": a.get("align", ""), "mt": px(css.get("margin-top")),
                        "mb": px(css.get("margin-bottom")), "size": self.style()["size"]}
            self.stack.append(self._apply(css))
        elif tag == "span":
            self.stack.append(self._apply(css))
        elif tag == "br" and self.cur is not None:
            self.cur["runs"].append(("\n", self.style()))

    def handle_endtag(self, tag):
        if tag == "span" and self.stack:
            self.stack.pop()
        elif tag == "p" and self.cur is not None:
            self.stack.pop() if self.stack else None
            self.paras.append(self.cur)
            self.cur = None

    def handle_data(self, data):
        if self.cur is not None:
            self.cur["runs"].append((data, self.style()))


def para_markup(p):
    out, maxsize = [], 0
    for text, st in p["runs"]:
        maxsize = max(maxsize, st["size"])
        if text == "\n":
            out.append("<br/>")
            continue
        t = html.escape(text, quote=False).replace("  ", " &nbsp;")
        if st["bold"]:
            t = f"<b>{t}</b>"
        if st["italic"]:
            t = f"<i>{t}</i>"
        if st["underline"]:
            t = f"<u>{t}</u>"
        out.append(f'<font size="{st["size"]}" color="{st["color"]}">{t}</font>')
    return "".join(out), (maxsize or p["size"])


ALIGN = {"center": TA_CENTER, "right": TA_RIGHT, "justify": TA_JUSTIFY, "left": TA_LEFT}


def draw_text(c, area, x, y, w, h):
    text = area.find("text")
    if text is None or not (text.text or "").strip():
        return
    tf = text.find("textFormat")
    fmt = tf.attrib if tf is not None else {}
    bg = argb(fmt.get("backgroundColor")) or argb(area.get("backgroundcolor"))
    if bg is not None:
        c.setFillColor(bg)
        c.rect(x, y, w, h, stroke=0, fill=1)
    q = QtRich()
    q.feed(text.text)
    # Horizontal alignment comes only from the paragraphs' own align attribute;
    # a paragraph without one is left-aligned (Qt rich text). textFormat's
    # Alignment is CEWE's "format for new text" and is not applied to existing text.
    default_align = "left"
    al = fmt.get("Alignment", "")
    flow = []
    for i, p in enumerate(q.paras):
        markup, size = para_markup(p)
        st = ParagraphStyle("p", fontName=FONT, fontSize=size, leading=size * 1.15,
                            alignment=ALIGN.get(p["align"] or default_align, TA_LEFT),
                            spaceBefore=p["mt"] * 0.75 if i else 0, spaceAfter=p["mb"] * 0.75)
        if not markup.strip() or markup in ("<br/>",):
            markup = "&nbsp;"
        flow.append(Paragraph(markup, st))
    pad = 0
    heights = [f.wrap(w - 2 * pad, 1e6)[1] for f in flow]
    total = sum(heights) + sum(f.style.spaceBefore + f.style.spaceAfter for f in flow)
    if "ALIGNVCENTER" in al:
        cur = y + h - (h - total) / 2
    elif "ALIGNBOTTOM" in al:
        cur = y + total
    else:
        cur = y + h
    for f, fh in zip(flow, heights):
        cur -= f.style.spaceBefore + fh
        f.drawOn(c, x + pad, cur)
        cur -= f.style.spaceAfter


_img_cache = {}


def load_image(path):
    if path not in _img_cache:
        im = Image.open(path)
        im = ImageOps.exif_transpose(im)
        _img_cache.clear()  # keep memory low; images are rarely reused consecutively
        _img_cache[path] = im
    return _img_cache[path]


def draw_image(c, area, imgdir, x, y, w, h, dpi, warn):
    img = area.find("image")
    if img is None:
        return
    fn = img.get("filename", "").strip()
    if fn.startswith("safecontainer:"):
        fn = fn[len("safecontainer:"):].lstrip("/\\")
    if not fn:
        return  # empty photo placeholder (no photo dropped into this box)
    path = os.path.join(imgdir, fn)
    if not os.path.isfile(path) and os.path.isabs(fn) and os.path.isfile(fn):
        path = fn  # some projects reference photos by absolute path
    if not os.path.isfile(path):
        warn(f"missing image {fn}")
        return
    cut = img.find("cutout")
    cl, ct, sc = (float(cut.get("left", 0)), float(cut.get("top", 0)), float(cut.get("scale", 1))) if cut is not None else (0, 0, 1)
    if sc <= 0:
        warn(f"invalid scale for image {fn}")
        return
    try:
        im = load_image(path)
    except Exception as e:  # unreadable or unsupported format (e.g. HEIC)
        warn(f"cannot read image {fn}: {e}")
        return
    W, H = im.size
    aw, ah = w / U, h / U  # area size in mcf units
    # visible part of the image in source pixels
    x0, y0 = max(0, -cl / sc), max(0, -ct / sc)
    x1, y1 = min(W, (aw - cl) / sc), min(H, (ah - ct) / sc)
    if x1 <= x0 or y1 <= y0:
        return
    crop = im.crop((int(x0), int(y0), int(round(x1)), int(round(y1))))
    # placement of the crop inside the area (mcf units)
    px0, py0 = cl + int(x0) * sc, ct + int(y0) * sc
    pw, ph = crop.size[0] * sc, crop.size[1] * sc
    target = (pw / 254 * dpi, ph / 254 * dpi)  # pixels at requested dpi
    if crop.size[0] > target[0] * 1.05:
        crop = crop.resize((max(1, int(target[0])), max(1, int(target[1]))), Image.LANCZOS)
    if crop.mode not in ("RGB", "L"):
        crop = crop.convert("RGB")
    buf = io.BytesIO()
    crop.save(buf, "JPEG", quality=90)
    buf.seek(0)
    c.saveState()
    try:
        p = c.beginPath()
        p.rect(x, y, w, h)
        c.clipPath(p, stroke=0, fill=0)
        c.drawImage(ImageReader(buf), x + px0 * U, y + h - (py0 + ph) * U, pw * U, ph * U)
    finally:
        c.restoreState()


def render_page(c, page, imgdir, dpi, warn, x_off=0, page_h=None):
    for area in sorted(page.findall("area"), key=lambda a: float(a.find("position").get("zposition", 0))):
        pos = area.find("position")
        left, top = float(pos.get("left")), float(pos.get("top"))
        w, h = float(pos.get("width")), float(pos.get("height"))
        rot = float(pos.get("rotation", 0))
        c.saveState()
        # rotate around the area's centre (CEWE rotates clockwise)
        cx, cy = (x_off + left + w / 2) * U, page_h - (top + h / 2) * U
        c.translate(cx, cy)
        if rot:
            c.rotate(-rot)
        x, y, ww, hh = -w / 2 * U, -h / 2 * U, w * U, h * U
        t = area.get("areatype")
        try:
            if t == "imagearea":
                draw_image(c, area, imgdir, x, y, ww, hh, dpi, warn)
            elif t in ("textarea", "spinetextarea"):
                draw_text(c, area, x, y, ww, hh)
        except Exception as e:  # one broken box shouldn't stop the whole book
            warn(f"skipped {t} on page {page.get('pagenr')}: {e}")
        c.restoreState()


# CEWE's background designs ship with the CEWE software, not with the project.
# Approximate the ones we know by a plain colour: (designElementId, hue) -> colour.
KNOWN_BACKGROUNDS = {
    ("406", "60"): "#d8d8cc",  # light green-grey paper, sampled from the CEWE editor
}


def background_color(page):
    """Approximate fill colour for a page's CEWE background design, or None."""
    if page is None:
        return None
    for bg in page.findall("background"):
        key = (bg.get("designElementId"), bg.get("hue"))
        if bg.get("type") == "1" and key in KNOWN_BACKGROUNDS:
            return KNOWN_BACKGROUNDS[key]
    return None


def draw_backgrounds(c, halves, W, H, x_off):
    """halves: [(page element or None, x0, width)] in mcf units."""
    for el, x0, w in halves:
        col = background_color(el)
        if col:
            c.setFillColor(argb("#ff" + col[1:]))
            c.rect((x_off + x0) * U, 0, w * U, H * U, stroke=0, fill=1)


def draw_page_numbers(c, pn, numbers, W, H, x_off):
    """numbers: [(number, 'left'|'right')] for the halves of a spread."""
    if pn is None:
        return
    size = float(pn.get("fontsize", 14))
    bold = pn.get("fontbold") == "1"
    italic = pn.get("fontitalics") == "1"
    font = FONT + ("-BI" if bold and italic else "-B" if bold else "-I" if italic else "") if FONT == "Sans" else \
        ("Helvetica-Bold" if bold else "Helvetica")
    margin, vmargin = float(pn.get("margin", 50)), float(pn.get("verticalMargin", 100))
    color = argb(pn.get("textcolor", "#ff000000")) or argb("#ff000000")
    fmt = pn.get("textstring", "%")
    c.setFillColor(color)
    c.setFont(font, size)
    y = vmargin * U - size * 0.35  # vertically centre the digits on the margin line
    for num, side in numbers:
        s = fmt.replace("%", str(num))
        if side == "left":  # outer edge of a left page is the spread's left edge
            c.drawString((x_off + margin) * U, y, s)
        else:
            c.drawRightString((x_off + W - margin) * U, y, s)


class Cancelled(Exception):
    pass


def default_image_dir(mcf):
    """The image folder CEWE saved next to the .mcf (named in the file's imagedir)."""
    root = ET.parse(mcf).getroot()
    return os.path.join(os.path.dirname(os.path.abspath(mcf)), root.get("imagedir", ""))


def convert(mcf, out=None, dpi=300, single=False, progress=None, warn=None, cancel=None,
            backgrounds=True, page_numbers=True, image_dir=None):
    """Convert `mcf` to PDF and return the output path.

    progress(done, total, label) is called after each rendered spread;
    warn(msg) for non-fatal problems; cancel() -> True aborts with Cancelled.
    backgrounds: fill known CEWE background designs with an approximate colour.
    page_numbers: draw page numbers as configured in the book.
    image_dir: folder with the book's photos; default is the CEWE folder next to the .mcf.
    """
    out = out or os.path.splitext(mcf)[0] + ".pdf"
    warn = warn or (lambda m: print("warning:", m, file=sys.stderr))
    root = ET.parse(mcf).getroot()
    if root.tag != "fotobook":
        raise ValueError("Not a CEWE photo book (.mcf) file")
    imgdir = image_dir or os.path.join(os.path.dirname(os.path.abspath(mcf)), root.get("imagedir", ""))
    if image_dir and not os.path.isdir(image_dir):
        raise FileNotFoundError(f"Images folder not found: {image_dir}")
    if not os.path.isdir(imgdir):
        warn(f"image folder not found: {imgdir} (choose the folder with the photos as images folder)")
    # spine is part of the cover; odd normal pages hold no content (spreads live on even pages)
    all_pages = root.findall("page")
    pages = [p for p in all_pages
             if p.get("type") != "spine" and (p.findall("area") or p.get("type") == "emptypage")]
    by_nr = {int(p.get("pagenr")): p for p in all_pages if p.get("type") == "normalpage"}
    ac = root.find("articleConfig")
    n_normal = int(ac.get("normalpages")) if ac is not None else max(by_nr, default=0)
    pn = root.find("pagenumbering") if page_numbers else None
    empties = [p for p in all_pages if p.get("type") == "emptypage"]

    def spread_info(page, W):
        """-> ([(bg element, x0, width)], [(page number, side)]) for a spread."""
        typ = page.get("type")
        if typ == "normalpage":  # even page n holds the spread n | n+1
            n = int(page.get("pagenr"))
            nums = [(k, side) for k, side in ((n, "left"), (n + 1, "right")) if 1 <= k <= n_normal]
            return [(page, 0, W / 2), (by_nr.get(n + 1, page), W / 2, W / 2)], nums
        if typ == "emptypage" and empties and page is empties[0]:  # inside front cover | page 1
            return [(page, 0, W / 2), (by_nr.get(1, page), W / 2, W / 2)], [(1, "right")] if n_normal else []
        return [(page, 0, W)], []

    tmp = out + ".part"
    c = canvas.Canvas(tmp)
    c.setTitle(os.path.splitext(os.path.basename(mcf))[0])

    def render(page, W, H, x_off):
        halves, nums = spread_info(page, W)
        if backgrounds:
            draw_backgrounds(c, halves, W, H, x_off)
        render_page(c, page, imgdir, dpi, warn, x_off=x_off, page_h=H * U)
        draw_page_numbers(c, pn, nums, W, H, x_off)

    try:
        for i, page in enumerate(pages):
            if cancel and cancel():
                raise Cancelled()
            typ = page.get("type")
            bs = page.find("bundlesize")
            W, H = float(bs.get("width")), float(bs.get("height"))
            if single and typ in ("normalpage", "emptypage"):
                for half in (0, 1):
                    c.setPageSize((W / 2 * U, H * U))
                    c.saveState()
                    p = c.beginPath(); p.rect(0, 0, W / 2 * U, H * U); c.clipPath(p, stroke=0, fill=0)
                    render(page, W, H, -half * W / 2)
                    c.restoreState()
                    c.showPage()
            else:
                c.setPageSize((W * U, H * U))
                render(page, W, H, 0)
                c.showPage()
            if progress:
                label = "Cover" if typ == "fullcover" else ("Inside cover" if typ == "emptypage" else f"Pages {page.get('pagenr')}-{int(page.get('pagenr')) + 1}")
                progress(i + 1, len(pages), label)
        c.save()
        os.replace(tmp, out)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mcf")
    ap.add_argument("out", nargs="?")
    ap.add_argument("--dpi", type=int, default=300, help="max image resolution in the PDF (default 300)")
    ap.add_argument("--single", action="store_true", help="split double-page spreads into single pages")
    ap.add_argument("--white", action="store_true", help="white background instead of approximated CEWE designs")
    ap.add_argument("--no-page-numbers", action="store_true", help="don't draw page numbers")
    ap.add_argument("--images", metavar="DIR",
                    help="folder with the book's photos (default: the <name>_mcf-Dateien folder next to the .mcf)")
    a = ap.parse_args()
    try:
        out = _cli_convert(a)
    except (OSError, ValueError, ET.ParseError) as e:
        sys.exit(f"error: {e}")
    print(f"wrote {out}")


def _cli_convert(a):
    return convert(a.mcf, a.out, a.dpi, a.single,
                   progress=lambda d, t, l: print(f"[{d}/{t}] {l}", file=sys.stderr),
                   backgrounds=not a.white, page_numbers=not a.no_page_numbers, image_dir=a.images)


if __name__ == "__main__":
    main()
