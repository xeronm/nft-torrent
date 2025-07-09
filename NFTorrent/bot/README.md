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

### Menu Button

```
Current menu button Open App with URL for Pets Memorial Bot @pets_memorial_bot:
https://petsmem.site/
```

### Description

```
Create a living digital tribute powered by blockchain — where each memory is unique, preserved, and truly yours.

With the Mini App, you can:

    ✨  Mint new memorial NFTs

    🔍  View full content of memorial NFTs

    ⚙️  Edit and manage your NFTs
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