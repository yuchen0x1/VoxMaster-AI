import sys
import multiprocessing

if __name__ == "__main__":
    multiprocessing.freeze_support()
    if len(sys.argv) > 1 and sys.argv[1] == '--cli':
        from vox.cli import main as cli

        sys.exit(cli(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "--verify-package":
        from vox.package_check import main as check

        sys.exit(check(sys.argv[2:]))
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont
from vox.interface import MainWindow
from vox.visual import STYLES, app_icon


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("VoxMaster AI")
    app.setOrganizationName("VoxMaster")
    from vox.platforms import ui_font

    if sys.platform != 'darwin':
        app.setStyle("Fusion")
    app.setFont(QFont(ui_font(), 10))
    app.setWindowIcon(app_icon())
    app.setStyleSheet(STYLES)
    window = MainWindow()
    window.show()
    if len(sys.argv) > 1 and Path(sys.argv[1]).is_file():
        from PySide6.QtCore import QTimer

        QTimer.singleShot(0, lambda: window.open_path(sys.argv[1]))
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
