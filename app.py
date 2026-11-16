"""Startpunkt von Tool-Hub. --selftest prüft das gebaute Paket ohne Fenster."""
import sys


def selftest():
    import tkinter

    from toolhub import config, github, gui, registry, secret, tools, winrun  # noqa: F401
    tkinter.Tcl()
    registry.entries()
    secret.load_token("Tool-Hub/selftest-gibt-es-nicht")
    assert tools.pick_setup("tool-hub", [{"name": "Tool-Hub-Setup-1.0.0.exe"}])[1]
    print("Selbsttest ok")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    from toolhub.gui import main
    main()
