"""Application entry point: ``coating-studio [project.coat]``."""

from __future__ import annotations

import os
import sys


def main(argv=None):
    argv = list(sys.argv if argv is None else argv)
    # High-DPI is on by default in Qt 6; keep rounding crisp on fractional scales.
    os.environ.setdefault("QT_SCALE_FACTOR_ROUNDING_POLICY", "PassThrough")
    import matplotlib

    matplotlib.use("QtAgg")
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtWidgets import QApplication

    from coating_studio import APP_NAME, __version__
    from coating_studio.mplfonts import configure_matplotlib_fonts
    from coating_studio.gui.icons import app_icon
    from coating_studio.gui.settings import AppSettings
    from coating_studio.i18n import detect_system_language, set_language

    QCoreApplication.setOrganizationName("CoatingStudio")
    QCoreApplication.setOrganizationDomain("coating-studio.local")
    QCoreApplication.setApplicationName(APP_NAME)
    QCoreApplication.setApplicationVersion(__version__)
    app = QApplication.instance() or QApplication(argv)
    app.setWindowIcon(app_icon())
    if sys.platform.startswith("linux"):
        app.setDesktopFileName("coating-studio")

    settings = AppSettings()
    lang = settings.language
    lang = detect_system_language() if lang == "system" else lang
    set_language(lang)
    if lang == "ko":
        from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator

        QLocale.setDefault(QLocale(QLocale.Korean, QLocale.SouthKorea))
        qt_tr = QTranslator(app)
        if qt_tr.load("qtbase_ko", QLibraryInfo.path(QLibraryInfo.TranslationsPath)):
            app.installTranslator(qt_tr)
    else:
        from PySide6.QtCore import QLocale

        QLocale.setDefault(QLocale(QLocale.English, QLocale.UnitedStates))
    configure_matplotlib_fonts()

    from coating_studio.gui.main_window import MainWindow

    win = MainWindow(settings)
    files = [a for a in argv[1:] if not a.startswith("-")]
    if files and os.path.exists(files[0]):
        win.load_path(files[0], confirm=False)
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
