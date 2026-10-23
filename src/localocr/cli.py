"""CLI exit codes: 0 success, 1 review/partial/failure, 2 config, 3 server, 130 cancel."""

import sys
from pathlib import Path
from typing import Annotated

import typer

from localocr import __version__, build_commit
from localocr.config import load_config, setup_logging
from localocr.embedded import EmbeddedSettings
from localocr.ollama import OCRServerError
from localocr.providers import create_provider
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


def selected_settings(
    provider,
    ollama_url,
    url,
    model,
    api_token,
    openwebui_api,
    precision,
    engine,
    model_path,
    mmproj_path,
    use_config,
    timeout=300,
    device=None,
    ssl_verify=None,
    trust_env=None,
):
    from localocr.config import AppConfig

    config = load_config() if use_config else AppConfig()
    config.provider = provider or ("ollama" if ollama_url else config.provider)
    if device is not None and (
        device not in {"auto", "gpu", "cpu"} or config.provider != "embedded"
    ):
        raise ValueError("--device auto|gpu|cpu применяется только к Embedded")
    if config.provider == "ollama":
        config.ollama_url = url or ollama_url or config.ollama_url
        config.ollama_model = model or config.ollama_model
    elif config.provider == "openwebui":
        config.openwebui_url = url or config.openwebui_url
        config.openwebui_model = model or config.openwebui_model
        config.api_token = config.api_token if api_token is None else api_token
        config.openwebui_api = openwebui_api or config.openwebui_api
        if ssl_verify is not None:
            config.ssl_verify = ssl_verify
        if trust_env is not None:
            config.trust_env = trust_env
    elif config.provider == "embedded":
        return EmbeddedSettings(
            precision=precision or config.precision,
            device_mode=device or config.embedded_device,
            engine=engine,
            model_path=model_path,
            mmproj_path=mmproj_path,
            timeout=timeout,
            max_calls=config.ocr_max_calls,
            max_image_seconds=config.embedded_max_image_seconds,
        )
    return config.settings(timeout)


@app.command()
def doctor(
    ollama_url: str | None = None,
    model: str | None = None,
    provider: str | None = None,
    url: str | None = None,
    api_token: str | None = None,
    openwebui_api: str | None = None,
    precision: str | None = None,
    engine: Path | None = None,
    model_path: Path | None = None,
    mmproj_path: Path | None = None,
    use_config: bool = False,
    device: str | None = None,
    debug_http: bool = False,
    ssl_verify: Annotated[bool | None, typer.Option("--ssl-verify/--no-ssl-verify")] = None,
    trust_env: Annotated[bool | None, typer.Option("--trust-env/--no-trust-env")] = None,
):
    client = None
    try:
        setup_logging()
        settings = selected_settings(
            provider,
            ollama_url,
            url,
            model,
            api_token,
            openwebui_api,
            precision,
            engine,
            model_path,
            mmproj_path,
            use_config,
            device=device,
            ssl_verify=ssl_verify,
            trust_env=trust_env,
        )
        client = create_provider(settings, on_network_event=typer.echo if debug_http else None)
        typer.echo(client.doctor())
    except (ValueError, OSError) as error:
        from localocr.runtime import write_error

        typer.echo(write_error(error) if isinstance(error, OSError) else str(error), err=True)
        raise typer.Exit(2) from error
    except OCRServerError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(3) from error
    except KeyboardInterrupt as error:
        raise typer.Exit(130) from error
    finally:
        if client is not None:
            client.close()


@app.command()
def convert(
    source: Path,
    ollama_url: str | None = None,
    model: str | None = None,
    provider: str | None = None,
    url: str | None = None,
    api_token: str | None = None,
    openwebui_api: str | None = None,
    precision: str | None = None,
    engine: Path | None = None,
    model_path: Path | None = None,
    mmproj_path: Path | None = None,
    use_config: bool = False,
    device: str | None = None,
    debug_http: bool = False,
    ssl_verify: Annotated[bool | None, typer.Option("--ssl-verify/--no-ssl-verify")] = None,
    trust_env: Annotated[bool | None, typer.Option("--trust-env/--no-trust-env")] = None,
    output_dir: Path | None = None,
    recursive: bool = False,
    overwrite: bool = False,
    timeout: float = 300,
    diagnostics: bool = False,
):
    try:
        setup_logging()
        results = run_convert(
            source,
            selected_settings(
                provider,
                ollama_url,
                url,
                model,
                api_token,
                openwebui_api,
                precision,
                engine,
                model_path,
                mmproj_path,
                use_config,
                timeout,
                device=device,
                ssl_verify=ssl_verify,
                trust_env=trust_env,
            ),
            output_dir,
            recursive,
            overwrite,
            diagnostics,
            on_network_event=typer.echo if debug_http else None,
            progress=lambda done, total, message: typer.echo(f"[{done}/{total}] {message}"),
        )
        typer.echo(f"Обнаружено файлов: {len(results)}")
        for status, label in [
            ("SUCCESS", "Успешно обработано"),
            ("REVIEW", "Требуют проверки"),
            ("PARTIAL", "Частично восстановлено"),
            ("FAILED", "Ошибок"),
            ("SKIPPED", "Пропущено"),
        ]:
            typer.echo(f"{label}: {sum(r.status == status for r in results)}")
        typer.echo(
            f"Каталог результатов: {output_dir or ((source if source.is_dir() else source.parent) / 'results')}"
        )
        if any(result.status in {"FAILED", "REVIEW", "PARTIAL"} for result in results):
            raise typer.Exit(1)
    except (ValueError, OSError) as error:
        from localocr.runtime import write_error

        typer.echo(write_error(error) if isinstance(error, OSError) else str(error), err=True)
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
