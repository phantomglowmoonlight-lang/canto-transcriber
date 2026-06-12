"""
CLI 命令列介面：使用 typer + rich
"""
import json
import sys
from pathlib import Path
from typing import Optional
import typer
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.prompt import Prompt, Confirm

from app.config import settings
from app.audio_processor import (
    check_ffmpeg,
    validate_audio_file,
    convert_to_wav,
    get_audio_duration,
)
from app.transcriber import transcribe_audio
from app.diarizer import diarize, assign_speakers_to_stt_segments
from app.text_processor import (
    apply_speaker_names,
    build_speaker_counts,
    merge_adjacent_same_speaker,
    segments_to_text,
)
from app.speaker_registry import SpeakerRegistry
from app.exporter import export_txt, export_docx
from app.report_generator import generate_report
from app.translator import translate_segments_builtin

app = typer.Typer(help="廣東話會議錄音轉文字系統 CLI", no_args_is_help=True)
console = Console()


def _check_prerequisites():
    """檢查必要的前置條件"""
    if not check_ffmpeg():
        console.print("[red]❌ 找不到 ffmpeg！[/red]")
        console.print("請安裝 ffmpeg 並加入系統 PATH：https://ffmpeg.org/download.html")
        raise typer.Exit(1)


@app.command()
def transcribe(
    audio_file: str = typer.Argument(..., help="音檔路徑"),
    output: str = typer.Option("./output", help="輸出目錄"),
    diarization_mode: str = typer.Option("vad", help="說話人分離模式: vad/pyannote"),
):
    """將音檔轉寫為文字"""
    _check_prerequisites()

    input_path = Path(audio_file)
    if not input_path.exists():
        console.print(f"[red]檔案不存在：{audio_file}[/red]")
        raise typer.Exit(1)

    is_valid, error = validate_audio_file(input_path)
    if not is_valid:
        console.print(f"[red]{error}[/red]")
        raise typer.Exit(1)

    output_dir = Path(output)
    output_dir.mkdir(parents=True, exist_ok=True)

    console.print(f"[bold]載入音檔：{input_path.name}[/bold]")
    duration = get_audio_duration(input_path)
    console.print(f"  時長：{duration / 60:.1f} 分鐘")

    # 格式轉換
    console.print("[cyan]轉換格式中...[/cyan]")
    wav_path = convert_to_wav(input_path, output_dir)

    # 語音識別
    console.print("[cyan]語音識別中（這可能需要數分鐘）...[/cyan]")
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}")) as progress:
        task = progress.add_task("轉寫中...", total=None)
        result = transcribe_audio(wav_path, language="yue")
        progress.update(task, completed=True)

    segments = result["segments"]
    console.print(f"  偵測語言：{result['language']}（機率：{result['language_probability']:.0%}）")
    console.print(f"  總段落數：{len(segments)}")

    if not segments:
        console.print("[yellow]未偵測到語音內容[/yellow]")
        return

    # 說話人分離
    console.print("[cyan]說話人分離中...[/cyan]")
    diar_segments = diarize(wav_path, mode=diarization_mode)
    segments = assign_speakers_to_stt_segments(segments, diar_segments)
    segments = merge_adjacent_same_speaker(segments)

    # 顯示說話人資訊
    speaker_counts = build_speaker_counts(segments)
    table = Table(title="說話人統計")
    table.add_column("代號", style="cyan")
    table.add_column("發言次數", justify="right")
    for sid, count in sorted(speaker_counts.items(), key=lambda x: int(x[0].replace("人物 #", ""))):
        table.add_row(sid, str(count))
    console.print(table)

    # 儲存原始結果
    result_data = {
        "audio_filename": input_path.name,
        "language": result["language"],
        "language_probability": result["language_probability"],
        "duration_sec": duration,
        "segments": segments,
        "speaker_map": {sid: {"count": count, "name": None} for sid, count in speaker_counts.items()},
    }
    json_path = output_dir / f"{input_path.stem}.json"
    json_path.write_text(json.dumps(result_data, ensure_ascii=False, indent=2), encoding="utf-8")
    console.print(f"[green]✓ 結果已儲存：{json_path}[/green]")

    # 顯示轉寫預覽
    console.print("\n[bold]轉寫預覽：[/bold]")
    for seg in segments[:10]:
        speaker = seg.get("speaker", "人物 #1")
        console.print(f"  [{speaker}] {seg['text'][:80]}...")


@app.command()
def edit(
    result_file: str = typer.Argument(..., help="轉寫結果 JSON 檔案"),
):
    """互動式編輯說話人名稱"""
    result_path = Path(result_file)
    if not result_path.exists():
        console.print(f"[red]檔案不存在：{result_file}[/red]")
        raise typer.Exit(1)

    data = json.loads(result_path.read_text(encoding="utf-8"))
    segments = data["segments"]
    speaker_map = data.get("speaker_map", {})
    registry = SpeakerRegistry()

    for sid, info in speaker_map.items():
        if info.get("name"):
            registry.set_name(sid, info["name"])

    # 顯示說話人
    console.print("[bold]目前說話人：[/bold]")
    for sid, info in sorted(speaker_map.items(), key=lambda x: int(x[0].replace("人物 #", ""))):
        name = info.get("name") or "未命名"
        count = info.get("count", 0)
        console.print(f"  {sid}（發言 {count} 次）：{name}")

    console.print("\n輸入 [編號] [姓名] 來命名（例如：1 陳大明），輸入 done 完成")
    console.print("輸入 reset [編號] 重置為預設代號")

    while True:
        cmd = Prompt.ask(">").strip()
        if cmd.lower() == "done":
            break
        if cmd.lower().startswith("reset "):
            parts = cmd.split(maxsplit=1)
            if len(parts) == 2:
                speaker_id = parts[1]
                speaker_id_full = f"人物 #{speaker_id}" if not speaker_id.startswith("人物") else speaker_id
                registry.reset_name(speaker_id_full)
                console.print(f"  已重置「{speaker_id_full}」")
            continue

        parts = cmd.split(maxsplit=1)
        if len(parts) == 2:
            num, name = parts
            speaker_id = f"人物 #{num}" if not num.startswith("人物") else num
            if registry.set_name(speaker_id, name):
                console.print(f"  [green]已將「{speaker_id}」→「{name}」[/green]")
            else:
                console.print(f"  [red]說話人「{speaker_id}」不存在[/red]")

    # 應用命名
    segments = apply_speaker_names(segments, registry)
    data["segments"] = segments

    # 更新 speaker_map
    for sid, info in speaker_map.items():
        info["name"] = registry._map.get(sid)

    # 儲存
    output_path = result_path.parent / f"{result_path.stem}_已命名.json"
    output_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    console.print(f"[green]✓ 已命名結果儲存至：{output_path}[/green]")

    # 同時匯出 TXT
    if Confirm.ask("是否匯出為 TXT？"):
        txt_path = result_path.parent / f"{result_path.stem}_已命名.txt"
        export_txt(segments, txt_path, data.get("audio_filename", ""), registry=registry)
        console.print(f"[green]✓ TXT 已匯出：{txt_path}[/green]")


@app.command()
def export(
    result_file: str = typer.Argument(..., help="轉寫結果 JSON 檔案"),
    fmt: str = typer.Option("txt", "--format", "-f", help="匯出格式：txt/docx"),
    language: str = typer.Option("yue", "--lang", "-l", help="語言版本：yue/written"),
    output: str = typer.Option("", "--output", "-o", help="輸出路徑"),
):
    """匯出轉寫結果"""
    result_path = Path(result_file)
    if not result_path.exists():
        console.print(f"[red]檔案不存在：{result_file}[/red]")
        raise typer.Exit(1)

    data = json.loads(result_path.read_text(encoding="utf-8"))
    segments = data["segments"]
    speaker_map = data.get("speaker_map", {})
    registry = SpeakerRegistry()
    for sid, info in speaker_map.items():
        if info.get("name"):
            registry.set_name(sid, info["name"])

    audio_filename = data.get("audio_filename", result_path.stem)
    written = language == "written"

    if not output:
        ext = ".txt" if fmt == "txt" else ".docx"
        output = str(result_path.parent / f"{result_path.stem}_export{ext}")

    output_path = Path(output)

    if fmt == "txt":
        export_txt(segments, output_path, audio_filename, written=written, registry=registry)
    elif fmt == "docx":
        export_docx(segments, output_path, audio_filename, written=written, registry=registry)
    else:
        console.print(f"[red]不支援的格式：{fmt}[/red]")
        raise typer.Exit(1)

    console.print(f"[green]✓ 匯出完成：{output_path}[/green]")


@app.command()
def report(
    result_file: str = typer.Argument(..., help="轉寫結果 JSON 檔案"),
    output: str = typer.Option("./report.md", "--output", "-o", help="輸出路徑"),
    language: str = typer.Option("yue", "--lang", "-l", help="分析基礎語言：yue/written"),
    model: str = typer.Option("", "--model", "-m", help="LLM 模型名稱"),
):
    """生成 AI 會議報告"""
    result_path = Path(result_file)
    if not result_path.exists():
        console.print(f"[red]檔案不存在：{result_file}[/red]")
        raise typer.Exit(1)

    data = json.loads(result_path.read_text(encoding="utf-8"))
    segments = data["segments"]
    written = language == "written"

    console.print("[cyan]正在生成會議報告...[/cyan]")
    result = generate_report(segments, written=written, model=model or None)

    if result["success"]:
        output_path = Path(output)
        output_path.write_text(result["report"], encoding="utf-8")
        console.print(f"[green]✓ 報告已儲存：{output_path}[/green]")
        console.print(f"  使用模型：{result['model']}")
        if result.get("tokens_used"):
            console.print(f"  Token 用量：{result['tokens_used']}")
    else:
        console.print(f"[red]❌ 生成失敗：{result.get('error')}[/red]")


@app.command()
def translate(
    result_file: str = typer.Argument(..., help="轉寫結果 JSON 檔案"),
    output: str = typer.Option("", "--output", "-o", help="輸出路徑"),
):
    """將粵語口語翻譯為書面語"""
    result_path = Path(result_file)
    if not result_path.exists():
        console.print(f"[red]檔案不存在：{result_file}[/red]")
        raise typer.Exit(1)

    data = json.loads(result_path.read_text(encoding="utf-8"))
    segments = data["segments"]

    console.print("[cyan]正在翻譯為書面語...[/cyan]")
    result = translate_segments_builtin(segments, scope="all")

    if result["success"]:
        data["segments"] = result["updated_segments"]
        if not output:
            output = str(result_path.parent / f"{result_path.stem}_書面語.json")
        output_path = Path(output)
        output_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        console.print(f"[green]✓ 翻譯完成：{output_path}[/green]")
        console.print(f"  使用模型：{result['model']}")
    else:
        console.print(f"[red]❌ 翻譯失敗：{result.get('error')}[/red]")


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", "--host"),
    port: int = typer.Option(8000, "--port"),
):
    """啟動 API 伺服器"""
    from app.api_server import start_server
    start_server(host, port)


def main():
    app()


if __name__ == "__main__":
    main()
