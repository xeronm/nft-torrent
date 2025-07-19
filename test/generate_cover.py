from NFTorrent.imageutils import generate_cover

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
    "Hendehog",
    "Mouse",
]

for name in SPECIES_LOGO:
    img = generate_cover(
        baseimage=f"./assets/images/species/{name}.webp",
        format="webp",
        font="assets/fonts/Inter_24pt-Bold.ttf",
        title="Marcus",
        subtitle="Nibelung",
        subtitle_font="assets/fonts/Inter_24pt-Regular.ttf",
        title_size=72,
        subtitle_size=40,
        rect_padding=(128, 0),
        rect_fill=(31, 33, 66),
        color="white",
    )

    with open(f"./.tox/cover-{name}.webp", "bw+") as f:
        f.write(img)
