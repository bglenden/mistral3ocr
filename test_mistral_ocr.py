"""Unit tests for mistral_ocr.py"""

import base64
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

import pytest

import mistral_ocr
from mistral_ocr import (
    CHUNK_SIZE_LIMIT,
    EXIT_API_ERROR,
    EXIT_AUTH_ERROR,
    EXIT_FILE_NOT_FOUND,
    EXIT_INVALID_FORMAT,
    EXIT_INVALID_PAGE_RANGE,
    EXIT_NO_API_KEY,
    EXIT_RATE_LIMIT,
    EXIT_SUCCESS,
    extract_and_save_images_from_base64,
    load_api_key,
    ocr_single_chunk,
    parse_page_range,
    save_page_images,
    split_pdf_into_chunks,
    update_image_references,
)


class TestParsePageRange:
    """Tests for parse_page_range function."""

    def test_single_page(self):
        assert parse_page_range("5") == [5]

    def test_single_page_zero(self):
        assert parse_page_range("0") == [0]

    def test_range(self):
        assert parse_page_range("0-4") == [0, 1, 2, 3, 4]

    def test_range_same_start_end(self):
        assert parse_page_range("3-3") == [3]

    def test_comma_separated(self):
        assert parse_page_range("0,2,5") == [0, 2, 5]

    def test_mixed_range_and_pages(self):
        assert parse_page_range("0-2,5,8-10") == [0, 1, 2, 5, 8, 9, 10]

    def test_removes_duplicates(self):
        assert parse_page_range("1,1,2,2-3") == [1, 2, 3]

    def test_whitespace_handling(self):
        assert parse_page_range("1 , 2 , 3") == [1, 2, 3]

    def test_invalid_non_numeric(self):
        with pytest.raises(ValueError):
            parse_page_range("abc")

    def test_invalid_negative(self):
        with pytest.raises(ValueError):
            parse_page_range("-1")

    def test_invalid_reversed_range(self):
        with pytest.raises(ValueError):
            parse_page_range("5-2")

    def test_invalid_range_format(self):
        with pytest.raises(ValueError):
            parse_page_range("1-2-3")

    def test_empty_parts_ignored(self):
        assert parse_page_range("1,,2") == [1, 2]


class TestLoadApiKey:
    """Tests for load_api_key function."""

    def test_from_environment(self):
        with mock.patch.dict(os.environ, {"MISTRAL_API_KEY": "test-key"}):
            with mock.patch.object(Path, "exists", return_value=False):
                assert load_api_key() == "test-key"

    def test_from_cwd_env_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / ".env"
            env_file.write_text("MISTRAL_API_KEY=cwd-key\n")

            with mock.patch.object(Path, "cwd", return_value=Path(tmpdir)):
                with mock.patch.dict(os.environ, {}, clear=True):
                    # Clear any existing key
                    os.environ.pop("MISTRAL_API_KEY", None)
                    result = load_api_key()
                    assert result == "cwd-key"

    def test_missing_key_returns_none(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            os.environ.pop("MISTRAL_API_KEY", None)
            with mock.patch.object(Path, "exists", return_value=False):
                assert load_api_key() is None


class TestExtractAndSaveImagesFromBase64:
    """Tests for extract_and_save_images_from_base64 function."""

    # Tiny valid 1x1 PNG
    TINY_PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="

    def test_extracts_single_image(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            images_dir = Path(tmpdir) / "images"
            images_dir.mkdir()

            markdown = f"![Test](data:image/png;base64,{self.TINY_PNG_B64})"
            result, count = extract_and_save_images_from_base64(markdown, images_dir)

            assert count == 1
            assert "images/image_001.png" in result
            assert (images_dir / "image_001.png").exists()

    def test_extracts_multiple_images(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            images_dir = Path(tmpdir) / "images"
            images_dir.mkdir()

            markdown = f"""
![First](data:image/png;base64,{self.TINY_PNG_B64})
![Second](data:image/png;base64,{self.TINY_PNG_B64})
"""
            result, count = extract_and_save_images_from_base64(markdown, images_dir)

            assert count == 2
            assert (images_dir / "image_001.png").exists()
            assert (images_dir / "image_002.png").exists()

    def test_handles_jpeg_format(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            images_dir = Path(tmpdir) / "images"
            images_dir.mkdir()

            # Use PNG data but with jpeg type - will still save
            markdown = f"![Test](data:image/jpeg;base64,{self.TINY_PNG_B64})"
            result, count = extract_and_save_images_from_base64(markdown, images_dir)

            assert count == 1
            assert "image_001.jpg" in result

    def test_no_images_returns_unchanged(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            images_dir = Path(tmpdir) / "images"
            images_dir.mkdir()

            markdown = "# Just text\nNo images here."
            result, count = extract_and_save_images_from_base64(markdown, images_dir)

            assert count == 0
            assert result == markdown


class TestSavePageImages:
    """Tests for save_page_images function."""

    # Tiny JPEG magic bytes as base64
    TINY_JPEG_B64 = "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAALCAABAAEBAREA/8QAFAABAAAAAAAAAAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AVN//2Q=="
    # Same as data URI
    TINY_JPEG_DATA_URI = "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAALCAABAAEBAREA/8QAFAABAAAAAAAAAAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AVN//2Q=="

    def test_saves_images_from_page(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            images_dir = Path(tmpdir) / "images"
            images_dir.mkdir()

            # Mock page object with raw base64
            mock_image = mock.MagicMock()
            mock_image.id = "img-0"
            mock_image.image_base64 = self.TINY_JPEG_B64

            mock_page = mock.MagicMock()
            mock_page.images = [mock_image]

            image_map, counter = save_page_images(mock_page, images_dir, 0)

            assert counter == 1
            assert "img-0" in image_map
            assert (images_dir / "image_001.jpg").exists()

    def test_saves_images_from_data_uri(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            images_dir = Path(tmpdir) / "images"
            images_dir.mkdir()

            # Mock page object with data URI (as returned by Mistral API)
            mock_image = mock.MagicMock()
            mock_image.id = "img-0"
            mock_image.image_base64 = self.TINY_JPEG_DATA_URI

            mock_page = mock.MagicMock()
            mock_page.images = [mock_image]

            image_map, counter = save_page_images(mock_page, images_dir, 0)

            assert counter == 1
            assert "img-0" in image_map
            filepath = images_dir / "image_001.jpg"
            assert filepath.exists()
            # Verify it's a valid JPEG (starts with FFD8)
            data = filepath.read_bytes()
            assert data[:2] == b'\xff\xd8', "Should be valid JPEG"

    def test_no_images_attribute(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            images_dir = Path(tmpdir) / "images"
            images_dir.mkdir()

            mock_page = mock.MagicMock(spec=[])  # No images attribute

            image_map, counter = save_page_images(mock_page, images_dir, 0)

            assert counter == 0
            assert image_map == {}

    def test_empty_images_list(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            images_dir = Path(tmpdir) / "images"
            images_dir.mkdir()

            mock_page = mock.MagicMock()
            mock_page.images = []

            image_map, counter = save_page_images(mock_page, images_dir, 0)

            assert counter == 0
            assert image_map == {}


class TestUpdateImageReferences:
    """Tests for update_image_references function."""

    def test_updates_references(self):
        markdown = "![alt](img-0.jpeg)\n![alt2](img-1.jpeg)"
        image_map = {
            "img-0.jpeg": "output_images/image_001.jpg",
            "img-1.jpeg": "output_images/image_002.jpg",
        }

        result = update_image_references(markdown, image_map)

        assert "output_images/image_001.jpg" in result
        assert "output_images/image_002.jpg" in result
        assert "img-0.jpeg" not in result

    def test_empty_map_unchanged(self):
        markdown = "![alt](img-0.jpeg)"
        result = update_image_references(markdown, {})
        assert result == markdown


class TestMainCLI:
    """Integration tests for main CLI function."""

    def test_file_not_found(self):
        with mock.patch("sys.argv", ["mistral-ocr", "nonexistent.pdf"]):
            with pytest.raises(SystemExit) as exc_info:
                mistral_ocr.main()
            assert exc_info.value.code == EXIT_FILE_NOT_FOUND

    def test_invalid_format(self):
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"not a pdf")
            temp_path = f.name

        try:
            with mock.patch("sys.argv", ["mistral-ocr", temp_path]):
                with pytest.raises(SystemExit) as exc_info:
                    mistral_ocr.main()
                assert exc_info.value.code == EXIT_INVALID_FORMAT
        finally:
            os.unlink(temp_path)

    def test_missing_api_key(self):
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"%PDF-1.4 fake pdf content")
            temp_path = f.name

        try:
            with mock.patch("sys.argv", ["mistral-ocr", temp_path]):
                with mock.patch.dict(os.environ, {}, clear=True):
                    os.environ.pop("MISTRAL_API_KEY", None)
                    # Mock load_api_key to return None (no .env files, no env var)
                    with mock.patch("mistral_ocr.load_api_key", return_value=None):
                        with pytest.raises(SystemExit) as exc_info:
                            mistral_ocr.main()
                        assert exc_info.value.code == EXIT_NO_API_KEY
        finally:
            os.unlink(temp_path)

    def test_invalid_page_range(self):
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"%PDF-1.4 fake pdf content")
            temp_path = f.name

        try:
            with mock.patch("sys.argv", ["mistral-ocr", temp_path, "--pages", "invalid"]):
                with mock.patch.dict(os.environ, {"MISTRAL_API_KEY": "test-key"}):
                    with pytest.raises(SystemExit) as exc_info:
                        mistral_ocr.main()
                    assert exc_info.value.code == EXIT_INVALID_PAGE_RANGE
        finally:
            os.unlink(temp_path)

    def test_api_auth_error(self):
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"%PDF-1.4 fake pdf content")
            temp_path = f.name

        try:
            with mock.patch("sys.argv", ["mistral-ocr", temp_path]):
                with mock.patch.dict(os.environ, {"MISTRAL_API_KEY": "bad-key"}):
                    with mock.patch("mistral_ocr.Mistral") as mock_client:
                        mock_client.return_value.ocr.process.side_effect = Exception(
                            "401 Unauthorized"
                        )
                        with pytest.raises(SystemExit) as exc_info:
                            mistral_ocr.main()
                        assert exc_info.value.code == EXIT_AUTH_ERROR
        finally:
            os.unlink(temp_path)

    def test_api_rate_limit_error(self):
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"%PDF-1.4 fake pdf content")
            temp_path = f.name

        try:
            with mock.patch("sys.argv", ["mistral-ocr", temp_path]):
                with mock.patch.dict(os.environ, {"MISTRAL_API_KEY": "test-key"}):
                    with mock.patch("mistral_ocr.Mistral") as mock_client:
                        mock_client.return_value.ocr.process.side_effect = Exception(
                            "429 rate limit exceeded"
                        )
                        with pytest.raises(SystemExit) as exc_info:
                            mistral_ocr.main()
                        assert exc_info.value.code == EXIT_RATE_LIMIT
        finally:
            os.unlink(temp_path)

    def test_successful_conversion(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = Path(tmpdir) / "test.pdf"
            pdf_path.write_bytes(b"%PDF-1.4 fake pdf content")

            # Mock OCR response
            mock_page = mock.MagicMock()
            mock_page.markdown = "# Test\nSome content"
            mock_page.images = []

            mock_response = mock.MagicMock()
            mock_response.pages = [mock_page]

            with mock.patch("sys.argv", ["mistral-ocr", str(pdf_path)]):
                with mock.patch.dict(os.environ, {"MISTRAL_API_KEY": "test-key"}):
                    with mock.patch("mistral_ocr.Mistral") as mock_client:
                        mock_client.return_value.ocr.process.return_value = mock_response
                        with pytest.raises(SystemExit) as exc_info:
                            mistral_ocr.main()
                        assert exc_info.value.code == EXIT_SUCCESS

            # Check output was created
            output_path = Path(tmpdir) / "test.md"
            assert output_path.exists()
            assert "# Test" in output_path.read_text()

    def test_no_images_flag(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = Path(tmpdir) / "test.pdf"
            pdf_path.write_bytes(b"%PDF-1.4 fake pdf content")

            mock_page = mock.MagicMock()
            mock_page.markdown = "# Test"
            mock_page.images = []

            mock_response = mock.MagicMock()
            mock_response.pages = [mock_page]

            with mock.patch("sys.argv", ["mistral-ocr", str(pdf_path), "--no-images"]):
                with mock.patch.dict(os.environ, {"MISTRAL_API_KEY": "test-key"}):
                    with mock.patch("mistral_ocr.Mistral") as mock_client:
                        mock_client.return_value.ocr.process.return_value = mock_response
                        with pytest.raises(SystemExit) as exc_info:
                            mistral_ocr.main()
                        assert exc_info.value.code == EXIT_SUCCESS

            # Check no images directory was created
            images_dir = Path(tmpdir) / "test_images"
            assert not images_dir.exists()


class TestExitCodes:
    """Verify exit code constants."""

    def test_exit_codes_are_unique(self):
        codes = [
            EXIT_SUCCESS,
            EXIT_FILE_NOT_FOUND,
            EXIT_INVALID_FORMAT,
            EXIT_NO_API_KEY,
            EXIT_AUTH_ERROR,
            EXIT_RATE_LIMIT,
            EXIT_API_ERROR,
            EXIT_INVALID_PAGE_RANGE,
        ]
        assert len(codes) == len(set(codes)), "Exit codes must be unique"

    def test_exit_success_is_zero(self):
        assert EXIT_SUCCESS == 0


def create_test_pdf(num_pages: int, tmp_path: Path) -> Path:
    """Create a simple multi-page PDF for testing."""
    from pypdf import PdfWriter

    writer = PdfWriter()
    for _ in range(num_pages):
        writer.add_blank_page(width=612, height=792)
    pdf_path = tmp_path / "test.pdf"
    with open(pdf_path, "wb") as f:
        writer.write(f)
    return pdf_path


class TestSplitPdfIntoChunks:
    """Tests for split_pdf_into_chunks function."""

    def test_small_file_no_chunking(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = create_test_pdf(5, Path(tmpdir))
            chunks = split_pdf_into_chunks(pdf_path, None)

            assert len(chunks) == 1
            b64_str, page_indices = chunks[0]
            assert page_indices is None  # small file, no pypdf processing
            # Verify it's valid base64
            raw = base64.b64decode(b64_str)
            assert raw[:5] == b'%PDF-'

    def test_large_file_splits_into_multiple_chunks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = create_test_pdf(20, Path(tmpdir))
            # Use a tiny chunk limit to force splitting
            chunks = split_pdf_into_chunks(pdf_path, None, chunk_size_limit=1024)

            assert len(chunks) > 1
            # All original pages should be covered exactly once
            all_pages = []
            for _, page_indices in chunks:
                assert page_indices is not None
                all_pages.extend(page_indices)
            assert sorted(all_pages) == list(range(20))

    def test_page_filtering_with_chunks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = create_test_pdf(10, Path(tmpdir))
            wanted = [0, 2, 4, 6, 8]
            chunks = split_pdf_into_chunks(pdf_path, wanted, chunk_size_limit=1024)

            all_pages = []
            for _, page_indices in chunks:
                assert page_indices is not None
                all_pages.extend(page_indices)
            assert sorted(all_pages) == wanted

    def test_single_page_exceeds_limit_exits(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = create_test_pdf(5, Path(tmpdir))
            file_size = pdf_path.stat().st_size
            # Set limit so low that even a single page exceeds it
            with pytest.raises(SystemExit) as exc_info:
                split_pdf_into_chunks(pdf_path, None, chunk_size_limit=1)
            assert exc_info.value.code == EXIT_API_ERROR

    def test_single_page_exceeds_limit_skip_oversized(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = create_test_pdf(5, Path(tmpdir))
            file_size = pdf_path.stat().st_size
            # With skip_oversized, oversized pages are dropped
            chunks = split_pdf_into_chunks(pdf_path, None,
                                           chunk_size_limit=1,
                                           skip_oversized=True)
            assert chunks == []

    def test_empty_page_list_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a PDF large enough to enter the chunking path
            pdf_path = create_test_pdf(5, Path(tmpdir))
            file_size = pdf_path.stat().st_size
            # Force chunking path by setting limit below file size
            chunks = split_pdf_into_chunks(pdf_path, [], chunk_size_limit=file_size - 1)

            assert chunks == []

    def test_page_indices_out_of_range_ignored(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = create_test_pdf(3, Path(tmpdir))
            file_size = pdf_path.stat().st_size
            chunks = split_pdf_into_chunks(pdf_path, [0, 1, 5, 10], chunk_size_limit=file_size - 1)

            all_pages = []
            for _, page_indices in chunks:
                assert page_indices is not None
                all_pages.extend(page_indices)
            assert sorted(all_pages) == [0, 1]

    def test_each_chunk_is_valid_pdf(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = create_test_pdf(10, Path(tmpdir))
            chunks = split_pdf_into_chunks(pdf_path, None, chunk_size_limit=1024)

            for b64_str, _ in chunks:
                raw = base64.b64decode(b64_str)
                assert raw[:5] == b'%PDF-'


class TestOcrSingleChunk:
    """Tests for ocr_single_chunk function."""

    def test_calls_api_with_correct_params(self):
        mock_client = mock.MagicMock()
        mock_client.ocr.process.return_value = mock.MagicMock()

        pdf_b64 = base64.standard_b64encode(b"%PDF-1.4 test").decode('utf-8')
        ocr_single_chunk(mock_client, pdf_b64, include_images=True)

        mock_client.ocr.process.assert_called_once_with(
            model="mistral-ocr-latest",
            document={
                "type": "document_url",
                "document_url": f"data:application/pdf;base64,{pdf_b64}",
            },
            include_image_base64=True,
        )

    def test_passes_no_images_flag(self):
        mock_client = mock.MagicMock()
        pdf_b64 = base64.standard_b64encode(b"%PDF-1.4 test").decode('utf-8')
        ocr_single_chunk(mock_client, pdf_b64, include_images=False)

        call_kwargs = mock_client.ocr.process.call_args
        assert call_kwargs.kwargs['include_image_base64'] is False
