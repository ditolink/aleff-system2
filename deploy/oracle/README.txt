# Dockerfile Oracle Ampere (ARM) — mesmo conteúdo do padrão com CLIP
# Em Ampere use preferencialmente o script setup-oracle.sh (sem Docker).
# Se preferir Docker na VM:
#   docker build -t aleff -f Dockerfile .
#   docker run -d --env-file .env -p 3001:3001 -v aleff-data:/app/data aleff
