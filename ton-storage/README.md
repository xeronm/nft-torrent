#### Create Torrent


```shell
$ docker compose run -i client

create -d "Pets Memorial Assets" --copy /storage-db/images/
Bag created
BagID = 0CB085065D867DDCD015126B37149E34B6FF07B0D41D2764398FE00E74480AED
Index = 1
Added: Fri Mar  7 08:43:37 2025
-----------------------------------
Pets Memorial Assets
-----------------------------------
Downloaded: 4907KB/4907KB (completed)
Dir name: images/
Total size: 4907KB
Upload speed: 0B/s
Root dir: /storage-db/torrent/torrent-files/0CB085065D867DDCD015126B37149E34B6FF07B0D41D2764398FE00E74480AED
12 files:
######  Prior   Ready/Size       Name
     0: (001)   546KB/546KB   +  auth.png
     1: (001)   566KB/566KB   +  cat.png
     2: (001)   528KB/528KB   +  classB.png
     3: (001)   528KB/528KB   +  collection.png
     4: (001)   671KB/671KB   +  dog.png
     5: (001)   3590B/3590B   +  marcus-1-onchain-128x128.jpg
     6: (001)   6519B/6519B   +  marcus-1-onchain-256x256.jpg
     7: (001)   737KB/737KB   +  marcus-1.jpg
     8: (001)   3583B/3583B   +  marcus-2-onchain-128x128.jpg
     9: (001)   6885B/6885B   +  marcus-2-onchain-256x256.jpg
    10: (001)    39KB/39KB    +  marcus-2.jpg
    11: (001)  1269KB/1269KB  +  marcus-3.jpg


list --hashes
1 bags
#####                                                             BagID  Description              Downloaded   Total   Download  Upload
    1  0CB085065D867DDCD015126B37149E34B6FF07B0D41D2764398FE00E74480AED  Pets Memorial Assets  4907KB/4907KB  4907KB  COMPLETED    0B/s


get 0CB085065D867DDCD015126B37149E34B6FF07B0D41D2764398FE00E74480AED
BagID = 0CB085065D867DDCD015126B37149E34B6FF07B0D41D2764398FE00E74480AED
Index = 1
Added: Fri Mar  7 08:43:37 2025
-----------------------------------
Pets Memorial Assets
-----------------------------------
Downloaded: 4907KB/4907KB (completed)
Dir name: images/
Total size: 4907KB
Upload speed: 0B/s
Root dir: /storage-db/torrent/torrent-files/0CB085065D867DDCD015126B37149E34B6FF07B0D41D2764398FE00E74480AED
12 files:
######  Prior   Ready/Size       Name
     0: (001)   546KB/546KB   +  auth.png
     1: (001)   566KB/566KB   +  cat.png
     2: (001)   528KB/528KB   +  classB.png
     3: (001)   528KB/528KB   +  collection.png
     4: (001)   671KB/671KB   +  dog.png
     5: (001)   3590B/3590B   +  marcus-1-onchain-128x128.jpg
     6: (001)   6519B/6519B   +  marcus-1-onchain-256x256.jpg
     7: (001)   737KB/737KB   +  marcus-1.jpg
     8: (001)   3583B/3583B   +  marcus-2-onchain-128x128.jpg
     9: (001)   6885B/6885B   +  marcus-2-onchain-256x256.jpg
    10: (001)    39KB/39KB    +  marcus-2.jpg
    11: (001)  1269KB/1269KB  +  marcus-3.jpg

```