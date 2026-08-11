#!/usr/bin/env bash
# setup-oracle.sh — Ubuntu Always Free (Ampere ARM) — Aleff + OpenCLIP
# Uso (na VM):
#   cd /opt/aleff-system2
#   sudo bash deploy/oracle/setup-oracle.sh
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/aleff-system2}"
APP_USER="${APP_USER:-ubuntu}"
DOMAIN="${DOMAIN:-aleffthiago.com.br}"

echo "==> Atualizando sistema"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y python3 python3-venv python3-pip nginx certbot python3-certbot-nginx git curl ca-certificates

echo "==> Pasta do app: $APP_DIR"
mkdir -p "$APP_DIR"
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

if [[ ! -f "$APP_DIR/backend/server.py" ]]; then
  echo "ERRO: copie o projeto para $APP_DIR antes (git clone ou scp)."
  echo "Exemplo: git clone SEU_REPO $APP_DIR"
  exit 1
fi

echo "==> venv + deps (com OpenCLIP)"
sudo -u "$APP_USER" bash -lc "
  cd '$APP_DIR'
  python3 -m venv .venv
  . .venv/bin/activate
  pip install --upgrade pip
  pip install -r requirements.txt
  pip install -r requirements-clip.txt
"

if [[ ! -f "$APP_DIR/.env" ]]; then
  echo "==> Crie o arquivo .env (copie do .env.example e preencha)"
  echo "    nano $APP_DIR/.env"
  cp -n "$APP_DIR/.env.example" "$APP_DIR/.env" || true
  chown "$APP_USER:$APP_USER" "$APP_DIR/.env"
fi

# Ajustes de produção no .env (se ainda não tiverem)
grep -q '^HOST=' "$APP_DIR/.env" || echo 'HOST=127.0.0.1' >> "$APP_DIR/.env"
sed -i 's/^HOST=.*/HOST=127.0.0.1/' "$APP_DIR/.env" || true
sed -i 's/^SESSION_COOKIE_SECURE=.*/SESSION_COOKIE_SECURE=true/' "$APP_DIR/.env" || true
sed -i 's/^CLIP_ENABLED=.*/CLIP_ENABLED=true/' "$APP_DIR/.env" || true
sed -i 's/^SEARCH_USE_CLIP=.*/SEARCH_USE_CLIP=0/' "$APP_DIR/.env" || true
grep -q '^SEARCH_USE_CLIP=' "$APP_DIR/.env" || echo 'SEARCH_USE_CLIP=0' >> "$APP_DIR/.env"
grep -q '^SEARCH_CACHE_TTL=' "$APP_DIR/.env" || echo 'SEARCH_CACHE_TTL=90' >> "$APP_DIR/.env"
grep -q '^HOME_POOL_CACHE_TTL=' "$APP_DIR/.env" || echo 'HOME_POOL_CACHE_TTL=120' >> "$APP_DIR/.env"
sed -i 's/^CODE_VIEWER_ENABLED=.*/CODE_VIEWER_ENABLED=false/' "$APP_DIR/.env" || true
sed -i 's|^CORS_ORIGINS=.*|CORS_ORIGINS=https://'"$DOMAIN"',https://www.'"$DOMAIN"'|' "$APP_DIR/.env" || true
grep -q '^FLASK_ENV=' "$APP_DIR/.env" || echo 'FLASK_ENV=production' >> "$APP_DIR/.env"
grep -q '^TRUST_PROXY=' "$APP_DIR/.env" && sed -i 's/^TRUST_PROXY=.*/TRUST_PROXY=true/' "$APP_DIR/.env" || echo 'TRUST_PROXY=true' >> "$APP_DIR/.env"
grep -q '^ALLOWED_HOSTS=' "$APP_DIR/.env" && sed -i 's|^ALLOWED_HOSTS=.*|ALLOWED_HOSTS='"$DOMAIN"',www.'"$DOMAIN"'|' "$APP_DIR/.env" || echo "ALLOWED_HOSTS=$DOMAIN,www.$DOMAIN" >> "$APP_DIR/.env"

mkdir -p "$APP_DIR/data" "$APP_DIR/data/thumbs" "$APP_DIR/data/media_cache" "$APP_DIR/frontend/fotos/slots"
chown -R "$APP_USER:$APP_USER" "$APP_DIR/data" "$APP_DIR/frontend/fotos/slots"

echo "==> systemd"
cat > /etc/systemd/system/aleff.service <<EOF
[Unit]
Description=Aleff Thiago Media System
After=network.target

[Service]
Type=simple
User=$APP_USER
WorkingDirectory=$APP_DIR
Environment=PATH=$APP_DIR/.venv/bin
EnvironmentFile=$APP_DIR/.env
ExecStart=$APP_DIR/.venv/bin/waitress-serve --host=127.0.0.1 --port=3001 --threads=8 --channel-timeout=120 backend.server:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable aleff
systemctl restart aleff

echo "==> Nginx (static + cache de thumbs + proxy API)"
mkdir -p /var/cache/nginx/aleff-thumbs
chown -R www-data:www-data /var/cache/nginx/aleff-thumbs 2>/dev/null || chown -R nginx:nginx /var/cache/nginx/aleff-thumbs 2>/dev/null || true

# Zona de cache (idempotente)
if ! grep -q 'proxy_cache_path /var/cache/nginx/aleff-thumbs' /etc/nginx/nginx.conf; then
  sed -i '/http {/a\    proxy_cache_path /var/cache/nginx/aleff-thumbs levels=1:2 keys_zone=aleff_thumbs:20m max_size=1g inactive=7d use_temp_path=off;' /etc/nginx/nginx.conf || true
fi
# Rate limits (idempotente) — defesa em profundidade além do Flask
if ! grep -q 'limit_req_zone \$binary_remote_addr zone=aleff_api' /etc/nginx/nginx.conf; then
  sed -i '/http {/a\    limit_req_zone \$binary_remote_addr zone=aleff_api:10m rate=30r/s;\n    limit_req_zone \$binary_remote_addr zone=aleff_login:10m rate=5r/m;\n    limit_req_zone \$binary_remote_addr zone=aleff_dl:10m rate=10r/m;' /etc/nginx/nginx.conf || true
fi

cat > /etc/nginx/sites-available/aleff <<EOF
server {
    listen 80;
    server_name $DOMAIN www.$DOMAIN;

    client_max_body_size 500M;
    gzip on;
    gzip_types text/css application/javascript application/json image/svg+xml;
    gzip_min_length 1024;

    # Headers de segurança no edge
    add_header X-Content-Type-Options nosniff always;
    add_header X-Frame-Options DENY always;
    add_header Referrer-Policy strict-origin-when-cross-origin always;

    root $APP_DIR/frontend;
    # Static pesado direto do disco (não passa pelo Waitress)
    location ^~ /css/ {
        expires 7d;
        add_header Cache-Control "public, max-age=604800, stale-while-revalidate=604800";
        try_files \$uri @app;
    }
    location ^~ /js/ {
        expires 1d;
        add_header Cache-Control "public, max-age=86400, stale-while-revalidate=604800";
        try_files \$uri @app;
    }
    location ^~ /fotos/ {
        expires 30d;
        add_header Cache-Control "public, max-age=2592000, immutable";
        try_files \$uri @app;
    }
    location ^~ /videos/ {
        expires 7d;
        add_header Cache-Control "public, max-age=604800, immutable";
        add_header Accept-Ranges bytes;
        try_files \$uri @app;
    }
    location ^~ /fonts/ {
        expires 30d;
        add_header Cache-Control "public, max-age=2592000, immutable";
        try_files \$uri @app;
    }

    # Originais / cache bruto — nunca servir via HTTP estático
    location ^~ /data/ {
        deny all;
        return 404;
    }
    location ^~ /media_cache/ {
        deny all;
        return 404;
    }
    location ^~ /uploads/ {
        deny all;
        return 404;
    }

    # Thumbs WebP pré-geradas (quando existirem) — sem Flask
    location ~ ^/data-thumbs/(small|medium)/([0-9]+)\.webp$ {
        alias $APP_DIR/data/thumbs/\$1/\$2.webp;
        default_type image/webp;
        expires 30d;
        add_header Cache-Control "public, max-age=2592000, immutable";
        try_files \$uri @thumb_api;
    }

    # Thumbs: cache nginx na frente do Flask (small/medium/legado)
    location ~ ^/api/media/[0-9]+/thumb {
        proxy_pass http://127.0.0.1:3001;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_cache aleff_thumbs;
        proxy_cache_valid 200 7d;
        proxy_cache_use_stale error timeout updating http_500 http_502 http_503;
        proxy_cache_lock on;
        add_header X-Cache-Status \$upstream_cache_status;
        expires 7d;
    }

    location @thumb_api {
        rewrite ^/data-thumbs/(small|medium)/([0-9]+)\.webp$ /api/media/\$2/thumb-\$1 last;
    }

    # Login: anti brute-force no edge
    location = /api/auth/login {
        limit_req zone=aleff_login burst=8 nodelay;
        limit_req_status 429;
        proxy_pass http://127.0.0.1:3001;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    # Download HD: rate baixo (scrape)
    location ~ ^/api/media/[0-9]+/download\$ {
        limit_req zone=aleff_dl burst=20 nodelay;
        limit_req_status 429;
        proxy_pass http://127.0.0.1:3001;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 300s;
    }

    location /api/ {
        limit_req zone=aleff_api burst=80 nodelay;
        limit_req_status 429;
        proxy_pass http://127.0.0.1:3001;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 300s;
        proxy_buffering on;
    }

    location @app {
        proxy_pass http://127.0.0.1:3001;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 300s;
    }

    location / {
        proxy_pass http://127.0.0.1:3001;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 300s;
    }
}
EOF

ln -sf /etc/nginx/sites-available/aleff /etc/nginx/sites-enabled/aleff
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx

echo ""
echo "OK. App rodando em :3001 via Nginx :80 (static offload + thumb cache)"
echo "1) Libere no Oracle Security List: TCP 22, 80, 443"
echo "2) DNS A @ e www -> IP publico da VM"
echo "3) HTTPS: sudo certbot --nginx -d $DOMAIN -d www.$DOMAIN"
echo "4) Login + Sync Drive no dashboard"
echo "5) Persistência: pasta $APP_DIR/data (DB + thumbs + media_cache) NÃO apague"
echo "Status: systemctl status aleff"
