"""The design report as a PDF (A4, portrait), laid out by Qt's rich text from the report's print variant.

Why it draws the pages itself instead of calling ``QTextDocument.print_``: without a page size, ``print_`` adds its own
2 cm margin and lays out in the platform's logical pixels (96 offscreen, 72 on macOS), so image widths in the HTML
would fit on one platform and overflow on another.  Here the document is laid out on the PDF device (300 dpi) with
the page's text area as its page size, and every page is drawn with a "n / N" footer.  See DEVELOPMENT_HISTORY 3.24.
"""

from __future__ import annotations

import base64
import os
import sys

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QMarginsF, QRectF, QSizeF, Qt
from PySide6.QtGui import (
    QColor, QFont, QFontDatabase, QImage, QPageLayout, QPageSize, QPainter, QPdfWriter, QTextDocument,
)

from coating_studio.report import build_report

RESOLUTION = 300  # dpi of the PDF device the document is laid out on
MARGINS_MM = QMarginsF(16, 15, 16, 18)  # left, top, right, bottom (the footer sits in the bottom margin)
BODY_PT = 9.5
IMAGE_FILL = 0.98  # images a little narrower than the text area, so rounding never clips their right edge


def report_font_family():
    """First Korean-capable family Qt can use here (same preference as the matplotlib set-up), else the default."""
    from coating_studio.mplfonts import _CANDIDATES

    plat = "win32" if sys.platform.startswith("win") else "darwin" if sys.platform == "darwin" else "linux"
    available = set(QFontDatabase.families())
    return next((f for f in _CANDIDATES[plat] if f in available), QFont().defaultFamily())


def _image_scale(device):
    """Layout units that <img width="1"> takes on ``device`` (Qt scales image sizes by the device's DPI over its own
    base DPI, which depends on the platform): measured, not assumed."""
    img = QImage(4, 4, QImage.Format_RGB32)
    img.fill(QColor("white"))
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    probe = QTextDocument()
    probe.documentLayout().setPaintDevice(device)
    probe.setDocumentMargin(0)
    probe.setHtml(f'<img width="100" height="100" src="data:image/png;base64,{base64.b64encode(bytes(data)).decode()}">')
    return probe.documentLayout().documentSize().width() / 100


def layout_report(writer, project, **kw):
    """(document, text width, text height) of the report laid out for ``writer``'s pages, in its device pixels."""
    body = writer.pageLayout().paintRectPixels(RESOLUTION)
    width, height = float(body.width()), float(body.height())
    family = report_font_family()
    html = build_report(project, print_layout={"image_width": IMAGE_FILL * width / _image_scale(writer),
                                               "font": family}, **kw)
    doc = QTextDocument()
    doc.documentLayout().setPaintDevice(writer)  # lay out in the PDF's own pixels
    doc.setDocumentMargin(0)
    font = QFont(family)
    font.setPointSizeF(BODY_PT)
    doc.setDefaultFont(font)
    doc.setHtml(html)
    doc.setPageSize(QSizeF(width, height))
    return doc, width, height


def write_report_pdf(path, project, **kw):
    """Write the report to ``path`` as PDF; returns the page count.  ``kw`` as for ``report.build_report``.

    Raises OSError when the file cannot be written (QPdfWriter itself reports nothing, and an old file left in place
    would look like success)."""
    with open(path, "wb"):  # permission / lock problems surface here, with the system's message
        pass
    writer = QPdfWriter(str(path))
    writer.setResolution(RESOLUTION)
    writer.setPageSize(QPageSize(QPageSize.A4))
    writer.setPageMargins(MARGINS_MM, QPageLayout.Millimeter)
    writer.setTitle(project.name)
    writer.setCreator("Coating Studio")
    doc, width, height = layout_report(writer, project, **kw)
    family = report_font_family()
    pages = doc.pageCount()

    painter = QPainter()
    if not painter.begin(writer):
        raise OSError(f"cannot write {path}")
    try:
        footer = QFont(family)
        footer.setPointSizeF(7.5)
        for i in range(pages):
            if i:
                writer.newPage()
            painter.save()
            painter.translate(0, -i * height)
            doc.drawContents(painter, QRectF(0, i * height, width, height))
            painter.restore()
            painter.setFont(footer)
            painter.setPen(QColor("#5f6b7a"))
            gap = RESOLUTION * 0.12  # inch below the text area
            painter.drawText(QRectF(0, height + gap, width, RESOLUTION * 0.3), Qt.AlignLeft | Qt.AlignTop, project.name)
            painter.drawText(QRectF(0, height + gap, width, RESOLUTION * 0.3), Qt.AlignRight | Qt.AlignTop,
                             f"{i + 1} / {pages}")
    finally:
        painter.end()
    if not os.path.getsize(path):
        raise OSError(f"nothing was written to {path}")
    return pages
