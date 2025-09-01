## Bot Settings

### Domain

```
petsmem.site
```

### Mini App


```
Current URL: https://petsmem.site/
Mode: Fullsize
Splash Icon: Custom
Background Color: 🌗 #4e5fd6
Header Color: 🌗 #4e5fd6
```

Registration in TApps

```
Details
Link: https://t.me/pets_memorial_bot
Analytics ID: pets_memorial_ru
Subtitle: Where Pet Memories Live Forever
Description: Pets Memorial lets you create a lasting digital tribute to your beloved pet. Turn photos and memories into unique NFTs that preserve their story on the blockchain. Share your tribute with others who understand and keep your pet’s memory alive.
```

### Menu Button

```
Current menu button Open App with URL for Pets Memorial Bot @pets_memorial_bot:
https://petsmem.site/
```

### Info

```
Name: Pets Memorial Bot
About: Where Pet Memories Live Forever
About (RU): Здесь воспоминания о питомцах живут вечно
```

### Description

```
Create a lasting digital tribute to your beloved pet powered by blockchain — where each memory is unique, preserved, and truly yours.

With the Mini App, you can:

    ✨  Mint new memorial NFTs

    🔍  View full content of memorial NFTs

    ⚙️  Edit and manage your NFTs
```

```
Создайте вечную цифровую память о своём любимом питомце на базе блокчейна — где каждая история уникальна, сохранена и принадлежит только вам.

В Mini App вы можете:

    ✨ Минтить новые мемориальные NFT

    🔍 Просматривать полное содержимое мемориальных NFT

    ⚙️ Редактировать и управлять своими NFT
```

### Commads

```
inquiry - Create inquiry
nftlist - List your memorial NFTs
nftview - View memorial NFT, args: [address]
```

## Development Server

```sh
watchmedo auto-restart --directory=./ --recursive --pattern="*.py" -- python -m test.bot_poll
```