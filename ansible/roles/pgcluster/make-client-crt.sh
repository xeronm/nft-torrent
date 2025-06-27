#!/bin/bash
set -euo pipefail

# Пути к CA и выходным файлам
CA_KEY=./inventory/certs/pgcluster/ca.key
CA_CERT=./inventory/certs/pgcluster/ca.crt

CLIENT_KEY=./inventory/certs/pgcluster/client.key
CLIENT_CSR=./inventory/certs/pgcluster/client.csr
CLIENT_CERT=./inventory/certs/pgcluster/client.crt

EXTFILE=/tmp/client-ext.cnf

# Создаем файл расширений для сертификата клиента
cat > "$EXTFILE" <<EOF
basicConstraints=CA:FALSE
keyUsage = digitalSignature, keyEncipherment
extendedKeyUsage = clientAuth
subjectAltName = @alt_names

[alt_names]
DNS.1 = etcd-client
EOF

echo "Generating client private key..."
openssl genrsa -out "$CLIENT_KEY" 4096

echo "Generating client CSR..."
openssl req -new -key "$CLIENT_KEY" -out "$CLIENT_CSR" -subj "/CN=etcd-client"

echo "Signing client certificate with CA..."
openssl x509 -req -in "$CLIENT_CSR" -CA "$CA_CERT" -CAkey "$CA_KEY" \
  -CAcreateserial -out "$CLIENT_CERT" -days 3650 -sha256 -extfile "$EXTFILE"

echo "Client certificate created successfully:"
openssl x509 -in "$CLIENT_CERT" -noout -text | grep -A5 "X509v3 Extended Key Usage"

# Убираем временный файл
rm -f "$EXTFILE"

echo "Done."