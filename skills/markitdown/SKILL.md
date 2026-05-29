---
name: markitdown
description: "Convert any file or URL to Markdown using Microsoft's MarkItDown library. Use whenever the user needs to extract text/content from files like PDF, Word (.docx), Excel (.xlsx/.xls), PowerPoint (.pptx), images (with OCR/EXIF), audio (with transcription), HTML, CSV, JSON, XML, ZIP, EPUB, Jupyter notebooks (.ipynb), Outlook messages (.msg), YouTube URLs, or Wikipedia URLs. Also trigger when the user wants to feed document content to an LLM, build a text pipeline, batch-convert a folder of files, or extract structured content from any document. Trigger on: 'convert to markdown', 'extract text from', 'read this PDF/Word/Excel/PPT', 'parse this file', 'get text from'."
---

# MarkItDown

Microsoft's MarkItDown converts virtually any file format to clean Markdown, optimized for LLM consumption. It preserves headings, lists, tables, and links — structure that LLMs understand natively.

## Installation

```bash
# Full install (all format support)
pip install 'markitdown[all]' --break-system-packages

# Selective install (faster, fewer deps)
pip install 'markitdown[pdf,docx,pptx,xlsx]' --break-system-packages
```

Optional extras: `pdf`, `docx`, `pptx`, `xlsx`, `xls`, `outlook`, `audio-transcription`, `youtube-transcription`, `az-doc-intel`, `az-content-understanding`

## CLI Usage

```bash
# Convert to stdout
markitdown document.pdf

# Convert to file
markitdown document.pdf -o document.md

# Pipe input
cat document.pdf | markitdown

# With plugins enabled
markitdown --use-plugins document.pdf

# Azure Document Intelligence (cloud, higher quality for scanned docs)
markitdown document.pdf -d -e "<docintel_endpoint>"
```

## Python API

### Basic conversion

```python
from markitdown import MarkItDown

md = MarkItDown()                    # plugins off by default
result = md.convert("file.pdf")
print(result.text_content)
```

### Safest method per use case

| Use case | Method | Notes |
|---|---|---|
| Local file by path | `md.convert_local("file.pdf")` | Safest for local files — no URI handling |
| URL/HTTP | `md.convert_url("https://...")` | Fetches and converts |
| Raw byte stream | `md.convert_stream(stream, stream_info=StreamInfo(mimetype="..."))` | Max control |
| requests.Response | `md.convert_response(response)` | Pass your own fetched response |
| Auto-detect | `md.convert("file_or_url")` | Permissive; handles local, URIs, streams |

> **Security note:** Use the narrowest method for your use case. `convert()` is intentionally permissive — in server/untrusted environments, prefer `convert_local()` or `convert_stream()` and validate inputs first.

### With LLM image descriptions (for PPTX and image files)

```python
from markitdown import MarkItDown
from openai import OpenAI

md = MarkItDown(
    llm_client=OpenAI(),
    llm_model="gpt-4o",
    llm_prompt="Describe this image in detail.",  # optional
)
result = md.convert("slides.pptx")
print(result.text_content)
```

### With plugins (e.g., markitdown-ocr)

```python
md = MarkItDown(enable_plugins=True, llm_client=OpenAI(), llm_model="gpt-4o")
result = md.convert("scanned_invoice.pdf")
```

### Azure Content Understanding (video, audio, structured field extraction)

```python
from markitdown import MarkItDown

# Auto-selects analyzer per file type
md = MarkItDown(cu_endpoint="<content_understanding_endpoint>")
result = md.convert("meeting.mp4")   # video → prebuilt-videoSearch
result = md.convert("call.wav")      # audio → prebuilt-audioSearch
result = md.convert("report.pdf")    # document → prebuilt-documentSearch

# Custom analyzer — extracts domain-specific fields as YAML front matter
md = MarkItDown(
    cu_endpoint="<endpoint>",
    cu_analyzer_id="my-invoice-analyzer",
)
result = md.convert("invoice.pdf")
# Output includes YAML front matter: VendorName, InvoiceDate, etc.
```

Restrict which formats use CU (to control costs):
```python
from markitdown.converters import ContentUnderstandingFileType
md = MarkItDown(
    cu_endpoint="<endpoint>",
    cu_file_types=[ContentUnderstandingFileType.PDF],
)
```

## Batch Conversion (folder of files)

```python
from markitdown import MarkItDown
from pathlib import Path

md = MarkItDown()
input_dir = Path("./docs")
output_dir = Path("./markdown")
output_dir.mkdir(exist_ok=True)

for f in input_dir.iterdir():
    if f.is_file():
        try:
            result = md.convert_local(str(f))
            (output_dir / f.with_suffix(".md").name).write_text(result.text_content)
            print(f"✓ {f.name}")
        except Exception as e:
            print(f"✗ {f.name}: {e}")
```

## Supported Formats

| Format | Extra | Notes |
|---|---|---|
| PDF | `[pdf]` | Text extraction; use `[az-doc-intel]` or `-ocr` plugin for scanned |
| Word (.docx) | `[docx]` | Headings, tables, math (OMML→LaTeX), comments |
| Excel (.xlsx) | `[xlsx]` | All sheets as markdown tables |
| Excel (.xls) | `[xls]` | Legacy format |
| PowerPoint (.pptx) | `[pptx]` | Slides, notes; LLM captions for images |
| Images (.jpg/.png/…) | built-in | EXIF metadata; LLM captions with `llm_client` |
| Audio (.wav/.mp3/.m4a) | `[audio-transcription]` | EXIF + speech-to-text |
| HTML | built-in | Full page → clean markdown |
| CSV | built-in | Encoding-aware (charset_normalizer) |
| JSON / XML | built-in | Pretty-printed |
| ZIP | built-in | Recursively converts contents |
| EPUB | built-in | |
| Jupyter (.ipynb) | built-in | Code + outputs |
| Outlook (.msg) | `[outlook]` | |
| RSS/Atom | built-in | |
| YouTube URL | `[youtube-transcription]` | Fetches transcript |
| Wikipedia URL | built-in | Clean article text |
| Bing SERP HTML | built-in | Search result extraction |

## Custom Converter / Plugin

To add a new format, subclass `DocumentConverter`:

```python
from markitdown import MarkItDown
from markitdown._base_converter import DocumentConverter, DocumentConverterResult
from markitdown._stream_info import StreamInfo

class MyConverter(DocumentConverter):
    def accepts(self, file_stream, stream_info: StreamInfo, **kwargs) -> bool:
        return (stream_info.mimetype or "").startswith("application/x-myformat")

    def convert(self, file_stream, stream_info: StreamInfo, **kwargs) -> DocumentConverterResult:
        content = file_stream.read().decode("utf-8")
        return DocumentConverterResult(markdown=f"# Converted\n\n{content}")

md = MarkItDown()
md.register_converter(MyConverter(), priority=0.0)
result = md.convert("myfile.myf")
```

For distributable plugins, use the `markitdown.plugin` entry point in `pyproject.toml`. See `packages/markitdown-sample-plugin` for the full template.

## Result Object

`result.text_content` — the full markdown string  
`result.markdown` — alias for `text_content`  
`result.title` — document title if detected  

## Common Patterns

**Feed a file to an LLM without loading it yourself:**
```python
md = MarkItDown()
result = md.convert_local("report.pdf")
# Pass result.text_content as context to your LLM prompt
```

**Unknown file type from a stream:**
```python
from markitdown._stream_info import StreamInfo
with open("mystery_file", "rb") as f:
    result = md.convert_stream(f)  # magika auto-detects MIME type
```

**Docker:**
```bash
docker build -t markitdown:latest .
docker run --rm -i markitdown:latest < input.pdf > output.md
```
