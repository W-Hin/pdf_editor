import subprocess
import sys
from pathlib import Path


def create_shortcut(target_exe: str, shortcut_name: str = "PDF Editor") -> Path:
    desktop = Path.home() / "Desktop"
    shortcut_path = desktop / f"{shortcut_name}.lnk"
    target = Path(target_exe).resolve()
    working_dir = target.parent

    ps_script = (
        "$WshShell = New-Object -ComObject WScript.Shell\n"
        f'$Shortcut = $WshShell.CreateShortcut("{shortcut_path}")\n'
        f'$Shortcut.TargetPath = "{target}"\n'
        f'$Shortcut.WorkingDirectory = "{working_dir}"\n'
        "$Shortcut.Save()\n"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", ps_script], check=True)
    return shortcut_path


if __name__ == "__main__":
    # Points at the web app (the primary way to use PDF Editor) by default.
    # Pass an explicit path as argv[1] to point at something else, e.g. the
    # desktop app: dist/PDFEditor/PDFEditor.exe
    default_target = str(Path("dist/PDFEditorWeb/PDFEditorWeb.exe").resolve())
    target = sys.argv[1] if len(sys.argv) > 1 else default_target
    path = create_shortcut(target)
    print(f"Shortcut created at {path}")
