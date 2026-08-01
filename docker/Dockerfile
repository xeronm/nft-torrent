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
    ./llvm.sh 21 clang && \
    rm ./llvm.sh && \
    apt-get clean

RUN git clone https://github.com/ton-blockchain/ton.git --branch ${TON_RELEASE} --recurse-submodules /ton

RUN cd /ton && \
    mkdir build && \
    cd build && \
    cmake -GNinja -DCMAKE_BUILD_TYPE=Release \
          -DCMAKE_C_COMPILER=clang-21 \
          -DCMAKE_CXX_COMPILER=clang++-21 \
          -DPORTABLE=1 \
          -DTON_ARCH=x86-64 \
          .. && \
    ninja tonlib tonlibjson tonlib-cli

FROM ubuntu:22.04

ARG USER_ID=9001 \
    GROUP_ID=9001 \
    NFTORRENT_VERSION \
    PIP_INDEX_URL

COPY --from=builder /ton/build/tonlib/libtonlibjson.so.0.5 /usr/local/lib/
COPY --from=builder /ton/build/tonlib/tonlib-cli /usr/local/lib/tonlib-cli

RUN groupadd -r nftorrent --gid=${GROUP_ID} && \
    useradd -r -g nftorrent --uid=${USER_ID} --home-dir=/opt/nftorrent --shell=/bin/bash nftorrent && \
    apt-get update && \
    apt-get install -y wget curl unzip python3 python3-pip libatomic1 libjemalloc2 libsodium23 locales && \
    apt-get clean && \
    locale-gen en_US.UTF-8 && \
    update-locale LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 && \
    python3 -m pip install pip -U --no-cache-dir && \
    chmod 755 /usr/local/lib/libtonlibjson.so.0.5 && \
    ln -s /usr/local/lib/libtonlibjson.so.0.5 /usr/local/lib/libtonlibjson.so

WORKDIR /opt/nftorrent

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

RUN --mount=from=dist,target=/mnt/dist \
    python3 -m pip install ton_nft_torrent==${NFTORRENT_VERSION} "gunicorn>=25.0" uvicorn --no-cache-dir \
        --find-links /mnt/dist

ENV LC_ALL=en_US.UTF-8 \
    LANG=en_US.UTF-8 \
    LOGGER_LEVEL=WARNING \
    TONLIB_LITESERVER_CONFIG=https://ton.org/global-config.json \
    TONLIB_KEYSTORE=/tmp/.ton_keystore/

USER nftorrent

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]

CMD [ "gunicorn", "-k", "uvicorn.workers.UvicornWorker", "-w", "1", "--bind", "0.0.0.0:8002", "--no-control-socket", "--access-logfile", "-", "NFTorrent.main:app" ]

