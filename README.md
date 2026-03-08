# mistral-ocr

A CLI tool that converts PDF files to Markdown using the [Mistral OCR API](https://docs.mistral.ai/capabilities/document/).

Uses **Mistral OCR 3** (`mistral-ocr-latest`), which offers improved handling of:
- Handwritten and cursive text
- Forms, invoices, and structured documents
- Scanned documents with compression artifacts or skew

See [Mistral's OCR 3 announcement](https://mistral.ai/news/mistral-ocr-3) for details.

## Features

- Converts PDF documents to clean Markdown format
- Automatic chunking of large PDFs (>50MB) with parallel API processing
- Extracts and saves embedded images
- Preserves tables in Markdown format
- Supports page range selection
- Simple command-line interface

## Installation

```bash
pip install -r requirements.txt
```

## Configuration

Set your Mistral API key using one of these methods (checked in order):

1. `.env` file in the current directory
2. `.env` file in your home directory (`~/.env`)
3. `MISTRAL_API_KEY` environment variable

Create a `.env` file:

```bash
echo "MISTRAL_API_KEY=your-api-key-here" > .env
```

Get your API key from the [Mistral AI Console](https://console.mistral.ai/).

## Usage

```bash
# Convert entire PDF
python mistral_ocr.py document.pdf

# Convert specific pages (0-indexed)
python mistral_ocr.py document.pdf --pages 0-4
python mistral_ocr.py document.pdf --pages 0,2,5
python mistral_ocr.py document.pdf --pages 0-2,5,8-10

# Convert without extracting images
python mistral_ocr.py document.pdf --no-images
```

### Output

- Creates `<input>.md` in the same directory as the input PDF
- If images are present, creates `<input>_images/` directory with extracted images

### Options

| Option | Description |
|--------|-------------|
| `--pages PAGES` | Page range to process (0-indexed). Supports ranges (`0-4`), lists (`0,2,5`), or mixed (`0-2,5,8-10`) |
| `--no-images` | Skip image extraction |
| `--skip-oversized` | Skip pages that individually exceed the 50MB API limit instead of exiting |
| `--parallel N` | Number of concurrent API requests for large file chunking (default: 2) |
| `--help` | Show help message |

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | File not found |
| 2 | Invalid file format (not a PDF) |
| 3 | Missing API key |
| 4 | Invalid API key |
| 5 | API rate limit exceeded |
| 6 | API processing error |
| 7 | Invalid page range |

## Large file handling

The Mistral OCR API accepts documents up to 50MB. For larger files, the tool automatically splits them into chunks at page boundaries using `pypdf`, processes chunks in parallel (2 concurrent requests), and merges the results in page order. Includes retry with exponential backoff on rate-limit errors.

## Future Enhancements

- [ ] User-provided correction filters (e.g. `--corrections corrections.json`) to fix known OCR errors for specific document types without baking domain-specific logic into the tool

## Development

### Running Tests

```bash
pip install pytest pytest-cov
pytest test_mistral_ocr.py -v --cov=mistral_ocr
```

## License

MIT
