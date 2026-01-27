#!/usr/bin/env python3
"""
Mistral OCR 3 - PDF to Markdown CLI Tool

Converts PDF files to Markdown using the Mistral OCR 3 API.
"""

import argparse
import base64
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from mistralai import Mistral


def load_api_key() -> str | None:
    """
    Load MISTRAL_API_KEY with fallback chain:
    1. Current directory .env
    2. Home directory .env
    3. Environment variable (already set)
    """
    # Try current directory .env
    cwd_env = Path.cwd() / '.env'
    if cwd_env.exists():
        load_dotenv(cwd_env)
        if os.environ.get('MISTRAL_API_KEY'):
            return os.environ.get('MISTRAL_API_KEY')

    # Try home directory .env
    home_env = Path.home() / '.env'
    if home_env.exists():
        load_dotenv(home_env)
        if os.environ.get('MISTRAL_API_KEY'):
            return os.environ.get('MISTRAL_API_KEY')

    # Fall back to environment variable
    return os.environ.get('MISTRAL_API_KEY')


# Exit codes
EXIT_SUCCESS = 0
EXIT_FILE_NOT_FOUND = 1
EXIT_INVALID_FORMAT = 2
EXIT_NO_API_KEY = 3
EXIT_AUTH_ERROR = 4
EXIT_RATE_LIMIT = 5
EXIT_API_ERROR = 6
EXIT_INVALID_PAGE_RANGE = 7


def parse_page_range(page_spec: str) -> list[int]:
    """
    Parse a page range specification into a list of page numbers.

    Examples:
        "0-4" -> [0, 1, 2, 3, 4]
        "0,2,5" -> [0, 2, 5]
        "0-2,5,8-10" -> [0, 1, 2, 5, 8, 9, 10]
    """
    pages = set()
    parts = page_spec.split(',')

    for part in parts:
        part = part.strip()
        if not part:
            continue

        if '-' in part:
            # Range like "0-4"
            range_parts = part.split('-')
            if len(range_parts) != 2:
                raise ValueError(f"Invalid range format: {part}")
            try:
                start = int(range_parts[0])
                end = int(range_parts[1])
            except ValueError:
                raise ValueError(f"Invalid page numbers in range: {part}")

            if start < 0 or end < 0:
                raise ValueError(f"Page numbers must be non-negative: {part}")
            if start > end:
                raise ValueError(f"Start page must be <= end page: {part}")

            pages.update(range(start, end + 1))
        else:
            # Single page like "5"
            try:
                page = int(part)
            except ValueError:
                raise ValueError(f"Invalid page number: {part}")

            if page < 0:
                raise ValueError(f"Page numbers must be non-negative: {part}")

            pages.add(page)

    return sorted(pages)


def extract_and_save_images_from_base64(markdown: str, images_dir: Path) -> tuple[str, int]:
    """
    Extract base64 images from markdown, save to files, and update references.

    Returns the updated markdown with file path references instead of base64.
    """
    # Pattern to match base64 image data URIs in markdown
    # Matches: ![alt](data:image/png;base64,...)
    pattern = r'!\[([^\]]*)\]\(data:image/([^;]+);base64,([^)]+)\)'

    image_count = 0

    def replace_image(match):
        nonlocal image_count
        image_count += 1

        alt_text = match.group(1)
        image_format = match.group(2)
        base64_data = match.group(3)

        # Determine file extension
        ext_map = {
            'png': 'png',
            'jpeg': 'jpg',
            'jpg': 'jpg',
            'gif': 'gif',
            'webp': 'webp',
        }
        ext = ext_map.get(image_format.lower(), 'png')

        # Create filename
        filename = f"image_{image_count:03d}.{ext}"
        filepath = images_dir / filename

        # Decode and save image
        try:
            image_data = base64.b64decode(base64_data)
            filepath.write_bytes(image_data)
        except Exception as e:
            print(f"Warning: Failed to save image {filename}: {e}", file=sys.stderr)
            return match.group(0)  # Keep original on failure

        # Return updated markdown reference
        relative_path = f"{images_dir.name}/{filename}"
        return f"![{alt_text}]({relative_path})"

    updated_markdown = re.sub(pattern, replace_image, markdown)

    return updated_markdown, image_count


def save_page_images(page, images_dir: Path, image_counter: int) -> tuple[dict[str, str], int]:
    """
    Save images from page response and return a mapping of original ID to new path.

    The API returns images in a separate 'images' field with base64 data.
    The data may be a raw base64 string or a data URI (data:image/...;base64,...).
    """
    image_map = {}

    if not hasattr(page, 'images') or not page.images:
        return image_map, image_counter

    for img in page.images:
        if not hasattr(img, 'image_base64') or not img.image_base64:
            continue

        image_counter += 1

        # Get image ID for mapping
        img_id = getattr(img, 'id', f'img-{image_counter}')

        base64_data = img.image_base64

        # Strip data URI prefix if present (e.g., "data:image/jpeg;base64,...")
        ext = 'jpg'  # default
        if base64_data.startswith('data:'):
            # Parse data URI: data:image/jpeg;base64,<data>
            if ';base64,' in base64_data:
                header, base64_data = base64_data.split(';base64,', 1)
                # Extract format from header (e.g., "data:image/jpeg" -> "jpeg")
                if '/' in header:
                    fmt = header.split('/')[-1].lower()
                    if fmt in ('jpeg', 'jpg'):
                        ext = 'jpg'
                    elif fmt == 'png':
                        ext = 'png'
                    elif fmt == 'gif':
                        ext = 'gif'
                    elif fmt == 'webp':
                        ext = 'webp'
        else:
            # Raw base64 - detect from magic bytes
            if base64_data.startswith('/9j/'):
                ext = 'jpg'
            elif base64_data.startswith('iVBOR'):
                ext = 'png'

        filename = f"image_{image_counter:03d}.{ext}"
        filepath = images_dir / filename

        try:
            image_data = base64.b64decode(base64_data)
            filepath.write_bytes(image_data)
            # Map original reference to new path
            image_map[img_id] = f"{images_dir.name}/{filename}"
            # Also map common variations
            image_map[f"{img_id}.jpeg"] = f"{images_dir.name}/{filename}"
            image_map[f"{img_id}.jpg"] = f"{images_dir.name}/{filename}"
            image_map[f"{img_id}.png"] = f"{images_dir.name}/{filename}"
        except Exception as e:
            print(f"Warning: Failed to save image {filename}: {e}", file=sys.stderr)

    return image_map, image_counter


def update_image_references(markdown: str, image_map: dict[str, str]) -> str:
    """
    Update image references in markdown to point to saved files.
    """
    for original, new_path in image_map.items():
        # Replace references like ![alt](img-0.jpeg) with ![alt](images_dir/image_001.jpg)
        markdown = markdown.replace(f"]({original})", f"]({new_path})")
    return markdown


def main():
    parser = argparse.ArgumentParser(
        prog='mistral-ocr',
        description='Convert PDF files to Markdown using the Mistral OCR 3 API.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
API Key Configuration (checked in order):
  1. .env file in current directory
  2. .env file in home directory (~/.env)
  3. MISTRAL_API_KEY environment variable

  Create a .env file with: MISTRAL_API_KEY=your-key-here

Output:
  Creates <input>.md in the same directory as the input PDF.
  If images are extracted, creates <input>_images/ directory containing
  numbered image files (image_001.png, image_002.png, etc.)

Examples:
  # Convert entire PDF
  mistral-ocr document.pdf

  # Convert only pages 0-4
  mistral-ocr document.pdf --pages 0-4

  # Convert without extracting images
  mistral-ocr document.pdf --no-images

Exit Codes:
  0    Success
  1    File not found or not readable
  2    Invalid file format (not a PDF)
  3    Missing MISTRAL_API_KEY
  4    API authentication error (invalid key)
  5    API rate limit or quota exceeded
  6    API processing error
  7    Invalid page range specified
'''
    )

    parser.add_argument(
        'input_pdf',
        metavar='input.pdf',
        help='Path to the PDF file to convert'
    )

    parser.add_argument(
        '--pages',
        metavar='PAGES',
        help='''Page range to process (0-indexed). Examples:
                --pages 0-4 (pages 0 through 4)
                --pages 0,2,5 (specific pages)
                --pages 0-2,5,8-10 (mixed)
                Default: all pages'''
    )

    parser.add_argument(
        '--no-images',
        action='store_true',
        help='Skip image extraction. By default, images are extracted to separate files.'
    )

    args = parser.parse_args()

    # Validate input file
    input_path = Path(args.input_pdf)

    if not input_path.exists():
        print(f"Error: File not found: {input_path}", file=sys.stderr)
        sys.exit(EXIT_FILE_NOT_FOUND)

    if not input_path.is_file():
        print(f"Error: Not a file: {input_path}", file=sys.stderr)
        sys.exit(EXIT_FILE_NOT_FOUND)

    if input_path.suffix.lower() != '.pdf':
        print(f"Error: File must be a PDF: {input_path}", file=sys.stderr)
        sys.exit(EXIT_INVALID_FORMAT)

    # Check API key
    api_key = load_api_key()
    if not api_key:
        print("Error: MISTRAL_API_KEY not found. Set it in:", file=sys.stderr)
        print("  - .env file in current directory", file=sys.stderr)
        print("  - .env file in home directory (~/.env)", file=sys.stderr)
        print("  - MISTRAL_API_KEY environment variable", file=sys.stderr)
        sys.exit(EXIT_NO_API_KEY)

    # Parse page range if specified
    pages = None
    if args.pages:
        try:
            pages = parse_page_range(args.pages)
        except ValueError as e:
            print(f"Error: Invalid page range: {args.pages}. Use format like 0-4 or 0,2,5", file=sys.stderr)
            sys.exit(EXIT_INVALID_PAGE_RANGE)

    # Read and encode PDF as base64
    try:
        pdf_data = input_path.read_bytes()
        pdf_base64 = base64.standard_b64encode(pdf_data).decode('utf-8')
    except IOError as e:
        print(f"Error: Cannot read file: {input_path}: {e}", file=sys.stderr)
        sys.exit(EXIT_FILE_NOT_FOUND)

    # Initialize Mistral client
    client = Mistral(api_key=api_key)

    # Build OCR request parameters
    include_images = not args.no_images

    # Call OCR API
    try:
        ocr_response = client.ocr.process(
            model="mistral-ocr-latest",
            document={
                "type": "document_url",
                "document_url": f"data:application/pdf;base64,{pdf_base64}",
            },
            include_image_base64=include_images,
        )
    except Exception as e:
        error_str = str(e).lower()

        if 'unauthorized' in error_str or 'authentication' in error_str or '401' in error_str:
            print("Error: Invalid API key. Check your MISTRAL_API_KEY.", file=sys.stderr)
            sys.exit(EXIT_AUTH_ERROR)
        elif 'rate limit' in error_str or '429' in error_str:
            print("Error: API rate limit exceeded. Try again later.", file=sys.stderr)
            sys.exit(EXIT_RATE_LIMIT)
        else:
            print(f"Error: API processing failed: {e}", file=sys.stderr)
            sys.exit(EXIT_API_ERROR)

    # Extract markdown and images from response
    markdown_parts = []
    all_image_maps = {}
    image_counter = 0
    output_stem = input_path.stem
    images_dir = input_path.parent / f"{output_stem}_images"

    if hasattr(ocr_response, 'pages') and ocr_response.pages:
        for i, page in enumerate(ocr_response.pages):
            # Filter by page range if specified
            if pages is not None and i not in pages:
                continue

            if hasattr(page, 'markdown') and page.markdown:
                markdown_parts.append(page.markdown)

            # Extract images from this page if enabled
            if include_images:
                if not images_dir.exists():
                    images_dir.mkdir(exist_ok=True)
                image_map, image_counter = save_page_images(page, images_dir, image_counter)
                all_image_maps.update(image_map)

    markdown_content = '\n\n'.join(markdown_parts)

    # Update image references in markdown
    if all_image_maps:
        markdown_content = update_image_references(markdown_content, all_image_maps)

    # Also handle any inline base64 images (fallback)
    if include_images and 'data:image' in markdown_content:
        if not images_dir.exists():
            images_dir.mkdir(exist_ok=True)
        markdown_content, extra_count = extract_and_save_images_from_base64(markdown_content, images_dir)
        image_counter += extra_count

    # Remove empty images directory if no images were saved
    if images_dir.exists():
        try:
            if not any(images_dir.iterdir()):
                images_dir.rmdir()
        except OSError:
            pass

    image_count = image_counter

    # Write markdown output
    output_path = input_path.with_suffix('.md')
    try:
        output_path.write_text(markdown_content, encoding='utf-8')
    except IOError as e:
        print(f"Error: Cannot write output file: {output_path}: {e}", file=sys.stderr)
        sys.exit(EXIT_API_ERROR)

    # Success message
    print(f"Created: {output_path}")
    if image_count > 0:
        print(f"Extracted {image_count} image(s) to: {images_dir}")

    sys.exit(EXIT_SUCCESS)


if __name__ == '__main__':
    main()
