from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def run(command: list[str]) -> None:
    print("\n> " + " ".join(command), flush=True)
    subprocess.check_call(command)


def main() -> int:
    root = Path(__file__).resolve().parent
    os.chdir(root)

    spec = root / "ModrinthBatchDownloader.spec"
    app = root / "app.py"
    requirements = root / "requirements.txt"
    assets = root / "assets"
    icon_png = assets / "icon.png"
    icon_ico = assets / "icon.ico"

    if not app.is_file() or not spec.is_file():
        print("ERRO: execute este script na pasta principal do projeto, junto de app.py e ModrinthBatchDownloader.spec.")
        return 1

    if not requirements.is_file():
        print("ERRO: requirements.txt não foi encontrado.")
        return 1

    # Instala/atualiza as dependências declaradas pelo projeto.
    run([sys.executable, "-m", "pip", "install", "-r", str(requirements)])
    run([sys.executable, "-m", "pip", "install", "--upgrade", "pyinstaller"])

    # O arquivo .spec usa assets/icon.ico. Se ele não existir, cria-o a partir do PNG.
    if not icon_ico.exists():
        if not icon_png.is_file():
            print("ERRO: assets/icon.ico e assets/icon.png não foram encontrados; não é possível definir o ícone do executável.")
            return 1
        try:
            from PIL import Image
            assets.mkdir(parents=True, exist_ok=True)
            with Image.open(icon_png) as image:
                image.convert("RGBA").save(
                    icon_ico,
                    format="ICO",
                    sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
                )
            print(f"Ícone criado: {icon_ico}")
        except Exception as exc:
            print(f"ERRO ao criar assets/icon.ico: {exc}")
            return 1

    # Limpa os artefatos antigos e gera um executável standalone usando o spec do projeto.
    run([sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm", str(spec)])

    exe = root / "dist" / "ModrinthBatchDownloader.exe"
    if exe.is_file():
        print(f"\nBuild concluído! Executável gerado em:\n{exe}")
        return 0

    print("\nO PyInstaller terminou, mas o executável esperado não foi encontrado em dist/.")
    return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        print(f"\nERRO: um comando terminou com código {exc.returncode}.")
        raise SystemExit(exc.returncode)
