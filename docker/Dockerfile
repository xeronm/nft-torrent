# Build Auxiliary Image
FROM ubuntu:22.04 AS builder
ARG TON_RELEASE

RUN apt-get update && \
    apt-get install -y wget git openssl curl unzip build-essential git cmake ninja-build \
        zlib1g-dev libsecp256k1-dev libmicrohttpd-dev libsodium-dev ccache libjemalloc-dev \
        liblz4-dev autoconf libssl-dev lsb-release software-properties-common gnupg libtool \
        python3-psycopg2 && \
    wget https://apt.llvm.org/llvm.sh && \
    chmod +x llvm.sh && \
    ./llvm.sh 16 all && \
    rm ./llvm.sh && \
    apt-get clean

RUN git clone https://github.com/ton-blockchain/ton.git --branch ${TON_RELEASE} --recurse-submodules /ton && \
    cd /ton && \
    mkdir build && \
    cd build && \
    cmake -GNinja -DCMAKE_BUILD_TYPE=Release .. && \
    ninja storage-daemon storage-daemon-cli
        # rldp-http-proxy
#    cp assembly/native/build-ubuntu-shared.sh . && \
#    chmod +x build-ubuntu-shared.sh && \
#    ./build-ubuntu-shared.sh

FROM ubuntu:22.04

ARG USER_ID=9001 \
    GROUP_ID=9001 \
    NFTORRENT_VERSION \
    PIP_INDEX_URL

RUN groupadd -r nftorrent --gid=${GROUP_ID} && \
    useradd -r -g nftorrent --uid=${USER_ID} --home-dir=/opt/nftorrent --shell=/bin/bash nftorrent && \
    apt-get update && \
    apt-get install -y gcc wget openssl curl unzip libatomic1 libjemalloc2 libsodium23 python3 python3-pip && \
    apt-get clean && \
    python3 -m pip install pip -U --no-cache-dir

WORKDIR /opt/nftorrent

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
COPY --from=builder /ton/build/storage/storage-daemon/storage-daemon-cli /opt/nftorrent
COPY --from=builder /ton/build/storage/storage-daemon/storage-daemon /opt/nftorrent

RUN --mount=from=dist,target=/mnt/dist \
    python3 -m pip install ton_nft_torrent==${NFTORRENT_VERSION} gunicorn --no-cache-dir \
        --find-links /mnt/dist

ENV LOGURU_LEVEL=INFO \
    TON_STORAGE_DB_PATH=/storage-db \
    TON_STORAGE_DB_TORRENT_PATH=/storage-db/torrent/torrent-files \
    TON_STORAGE_CLI_BINARY=/opt/nftorrent/storage-daemon-cli \
    TON_STORAGE_NUM_WORKERS=8 \
    TON_STORAGE_CONFIRMATION_TIMEOUT=60 \
    TON_STORAGE_MIN_REDUNDANCY=1 \
    TON_API_TONLIB_LITESERVER_CONFIG=https://ton.org/global-config.json \
    TON_API_TONLIB_KEYSTORE=/storage-db/.ton_keystore/

VOLUME storage-db

USER nftorrent

# EXPOSE 3333/udp 5555 8002

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]

CMD [ "gunicorn", "-k", "uvicorn.workers.UvicornWorker", "-w", "1", "--bind", "0.0.0.0:8002", "--access-logfile", "-", "NFTorrent.main:app" ]

