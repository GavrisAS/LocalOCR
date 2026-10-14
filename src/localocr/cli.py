"""CLI exit codes: 0 success, 1 review/partial/failure, 2 config, 3 server, 130 cancel."""

import sys
from pathlib import Path
from typing import Annotated

import typer

from localocr import __version__, build_commit
from localocr.config import setup_logging
from localocr.ollama import OCRServerError, OllamaClient, Settings
from localocr.service import convert as run_convert

app = typer.Typer(no_args_is_help=True)


@app.callback(invoke_without_command=True)
def callback(
    version: Annotated[bool, typer.Option("--version", is_eager=True)] = False,
    commit: Annotated[bool, typer.Option("--build-commit", is_eager=True)] = False,
):
    if commit:
        typer.echo(build_commit())
        raise typer.Exit()
    if version:
        typer.echo(__version__)
        raise typer.Exit()


@app.command()
def doctor(ollama_url: str = "http://127.0.0.1:11434", model: str = "glm-ocr:latest"):
    try:
        typer.echo(OllamaClient(Settings(url=ollama_url, model=model)).doctor())
    except (ValueError, OSError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(2) from error
    except OCRServerError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(3) from error


@app.command()
def convert(
    source: Path,
    ollama_url: str = "http://127.0.0.1:11434",
    model: str = "glm-ocr:latest",
    output_dir: Path | None = None,
    recursive: bool = False,
    overwrite: bool = False,
    timeout: float = 300,
    diagnostics: bool = False,
):
    setup_logging()
    try:
        results = run_convert(
            source,
            Settings(ollama_url, model, timeout),
            output_dir,
            recursive,
            overwrite,
            diagnostics,
            progress=lambda done, total, message: typer.echo(f"[{done}/{total}] {message}"),
        )
        typer.echo(f"Обнаружено файлов: {len(results)}")
        for status, label in [
            ("SUCCESS", "Успешно обработано"),
            ("REVIEW", "Требуют проверки"),
            ("FAILED", "Ошибок"),
            ("SKIPPED", "Пропущено"),
        ]:
            typer.echo(f"{label}: {sum(r.status == status for r in results)}")
        typer.echo(
            f"Каталог результатов: {output_dir or ((source if source.is_dir() else source.parent) / 'results')}"
        )
        if any(result.status in {"FAILED", "REVIEW"} for result in results):
            raise typer.Exit(1)
    except (ValueError, OSError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(2) from error
    except OCRServerError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(3) from error
    except KeyboardInterrupt as error:
        raise typer.Exit(130) from error


def main():
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")
    app()
