import unittest
import io

from NFTorrent.imageutils import generate_cover, convert_image
from PIL import Image

SPECIES_LOGO = [
    "Other",
    "Dog",
    "Cat",
    "Hamster",
    "Rabbit",
    "Parrot",
    "Fish",
    "Turtle",
    "Reptile",
    "Horse",
    "Hedgehog",
    "Mouse",
    "Ferret",
]

class TestImageUtils(unittest.TestCase):

    def test_cover(self):
        for name in SPECIES_LOGO:
            img = generate_cover(
                baseimage=f"./assets/images/species/{name}.webp",
                format="webp",
                font="assets/fonts/Inter_24pt-Bold.ttf",
                title="Marcus",
                subtitle="Nibelung",
                subtitle_font="assets/fonts/Inter_24pt-Regular.ttf",
                title_size=36,
                subtitle_size=20,
                rect_padding=(96, 0),
                rect_fill=(31, 33, 66),
                color="white",
            )

            self.assertIsNotNone(img)


    def test_convert(self):
        with open("./assets/images/marcus-2.jpg", "rb") as f:
            data = f.read()
        img = Image.open(io.BytesIO(data))
        self.assertEqual(img.size, (470, 420))

        p200 = convert_image(data, 200, "webp")
        img = Image.open(io.BytesIO(p200))
        self.assertEqual(img.size, (200, 200))

        p2000 = convert_image(data, 2000, "webp")
        img = Image.open(io.BytesIO(p2000))
        self.assertEqual(img.size, (470, 420))

