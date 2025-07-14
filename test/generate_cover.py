from NFTorrent.imageutils import generate_cover

img = generate_cover(
    baseimage="./assets/images/collection-logo.webp",
    format="webp",
    font="assets/fonts/Inter_24pt-Bold.ttf",
    title="Marcus",
    subtitle="Nibelung",
    subtitle_font="assets/fonts/Inter_24pt-Regular.ttf",
    rect_padding=(64, 8)
    )

with open("./.tox/cover.webp", "bw+") as f:
    f.write(img)