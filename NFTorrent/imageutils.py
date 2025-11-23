import io
import math
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont
from PIL._typing import _Ink

from .utils import guess_type


def buffer_guess_type(data: bytes, default_type: str = None) -> tuple[str, str]:
    with Image.open(io.BytesIO(data)) as img:
        ext = img.format.lower()
        mime_type, _ = guess_type(f"buffer.{ext}", default_type=default_type)
        return mime_type or "application/octet-stream", ext


def convert_image(buffer: bytes, size: int, format: str) -> bytes:
    img = Image.open(io.BytesIO(buffer))
    # 1. Resize min dimension to `size`
    x, y = img.size
    if x > size and y > size:
        m, n = x / size, y / size
        x0 = y0 = size
        if m > n:
            x0 = math.ceil(x / n)
        elif n > m:
            y0 = math.ceil(y / m)
        img = img.resize([x0, y0])

    # 2. Crop center
    x, y = img.size
    if x > size or y > size:
        x0 = y0 = 0
        if x > size:
            x0 = (x - size) // 2
        if y > size:
            y0 = (y - size) // 2
        img = img.crop((x0, y0, x0 + size, y0 + size))

    bufferOut = io.BytesIO()
    img.save(bufferOut, format)
    return bufferOut.getvalue()


@lru_cache(maxsize=10)
def load_background(filename: str):
    return Image.open(filename).convert("RGBA")


@lru_cache(maxsize=10)
def load_font(font: str, size: int = 24):
    return ImageFont.truetype(
        font,
        size=size,
    )


def generate_cover(
    baseimage: str = None,
    title: str = None,
    subtitle: str = None,
    format: str = "png",
    font: str = None,
    title_size: int = 96,
    subtitle_font: str = None,
    subtitle_size: int = 48,
    color: _Ink = "black",
    rect_padding: tuple[int, int] = (20, 10),
    rect_margin: tuple[int, int] = (20, None),
    rect_fill: _Ink = "white",
    rect_radius: int = 16,
    offset_top: float = 0.875,
):
    img = load_background(baseimage).copy()
    image_width = img.size[0]
    draw = ImageDraw.Draw(img)
    title_font = load_font(font, size=title_size)
    font_factor = 1

    bbox_title = title_font.getbbox(title)
    if bbox_title[2] > image_width - 2 * rect_margin[0]:
        # Try to reduce font
        font_factor = 0.8
        title_font = load_font(font, size=int(title_size * font_factor))
        bbox_title = title_font.getbbox(title)

    title_height, title_width = bbox_title[3], bbox_title[2]
    py = int((img.height - title_height) * offset_top)
    px = (img.width - title_width) // 2
    bbox = (px, py, px + title_width, py + title_height)

    if subtitle:
        sub_font = load_font(subtitle_font or font, size=int(subtitle_size * font_factor))
        bbox_sub = sub_font.getbbox(subtitle)
        if bbox_sub[2] > image_width - 2 * rect_margin[0]:
            # Try to reduce font
            font_factor = font_factor * 0.8
            sub_font = load_font(subtitle_font or font, size=int(subtitle_size * font_factor))
            bbox_sub = sub_font.getbbox(subtitle)

        sub_height, sub_width = bbox_sub[3], bbox_sub[2]
        px1 = (img.width - sub_width) // 2
        py1 = py + title_height + int(sub_height * 0.2)
        bbox = (min(px, px1), py, max(px + title_width, px1 + sub_width), py1 + sub_height)

    if rect_fill:
        font_shift = bbox_title[1] // 2
        rect = (
            max(bbox[0] - rect_padding[0], rect_margin[0]),
            bbox[1] + font_shift - rect_padding[1],
            min(bbox[2] + rect_padding[0], image_width - rect_margin[0]),
            bbox[3] + font_shift + rect_padding[1],
        )
        draw.rounded_rectangle(rect, radius=rect_radius, fill=rect_fill, outline=None, width=0)

    draw.text((px, py), title, font=title_font, fill=color)
    if subtitle:
        draw.text((px1, py1), subtitle, font=sub_font, fill=color)

    bufferOut = io.BytesIO()
    img.save(bufferOut, format)
    return bufferOut.getvalue()


__all__ = ["convert_image", "generate_cover"]
