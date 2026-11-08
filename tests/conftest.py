"""Test-session set-up shared by all test modules."""
import os
import sys

# Qt's offscreen platform (QT_QPA_PLATFORM=offscreen, used by the test runs and CI) does not read the Windows font
# registry: it looks for fonts in PySide6/lib/fonts, which Qt no longer ships, so it finds none and text is drawn
# with no glyphs (an exported PDF had no text on Windows only).  Point it at the system fonts before Qt starts.
if sys.platform == "win32" and os.environ.get("QT_QPA_PLATFORM") == "offscreen" and "QT_QPA_FONTDIR" not in os.environ:
    os.environ["QT_QPA_FONTDIR"] = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
