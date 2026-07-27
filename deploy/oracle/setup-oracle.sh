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
sed -i 's/^CODE_VIEWER_ENABLED=.*/CODE_VIEWER_ENABLED=false/' "$APP_DIR/.env" || true
sed -i 's|^CORS_ORIGINS=.*|CORS_ORIGINS=https://'"$DOMAIN"',https://www.'"$DOMAIN"'|' "$APP_DIR/.env" || true
grep -q '^FLASK_ENV=' "$APP_DIR/.env" || echo 'FLASK_ENV=production' >> "$APP_DIR/.env"
grep -q '^TRUST_PROXY=' "$APP_DIR/.env" && sed -i 's/^TRUST_PROXY=.*/TRUST_PROXY=true/' "$APP_DIR/.env" || echo 'TRUST_PROXY=true' >> "$APP_DIR/.env"
grep -q '^ALLOWED_HOSTS=' "$APP_DIR/.env" && sed -i 's|^ALLOWED_HOSTS=.*|ALLOWED_HOSTS='"$DOMAIN"',www.'"$DOMAIN"'|' "$APP_DIR/.env" || echo "ALLOWED_HOSTS=$DOMAIN,www.$DOMAIN" >> "$APP_DIR/.env"

mkdir -p "$APP_DIR/data" "$APP_DIR/frontend/fotos/slots"
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
ExecStart=$APP_DIR/.venv/bin/waitress-serve --host=127.0.0.1 --port=3001 backend.server:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable aleff
systemctl restart aleff

echo "==> Nginx"
cat > /etc/nginx/sites-available/aleff <<EOF
server {
    listen 80;
    server_name $DOMAIN www.$DOMAIN;

    client_max_body_size 500M;

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
echo "OK. App rodando em :3001 via Nginx :80"
echo "1) Libere no Oracle Security List: TCP 22, 80, 443"
echo "2) DNS A @ e www -> IP publico da VM"
echo "3) HTTPS: sudo certbot --nginx -d $DOMAIN -d www.$DOMAIN"
echo "4) Login + Sync Drive no dashboard"
echo "Status: systemctl status aleff"
