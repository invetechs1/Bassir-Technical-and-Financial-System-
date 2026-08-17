#!/usr/bin/env bash
# ينشر صورة Docker لنظام عزوم على السيرفر — يزيل الحاوية/الصورة القديمة لهذا المشروع فقط، ثم يحمّل الجديدة ويشغّلها.
# يُنفَّذ على السيرفر البعيد داخل مجلد المشروع (بجانب azoom-proposals.tar).
set -e
cd "$(dirname "$0")"

IMAGE="azoom-proposals"
CONTAINER="azoom-proposals"
PORT="${1:-8003}"
TAR_FILE="azoom-proposals.tar"

echo "== إيقاف وإزالة الحاوية القديمة (إن وجدت) =="
docker rm -f "$CONTAINER" 2>/dev/null || true

echo "== إزالة الصورة القديمة لهذا المشروع (إن وجدت) =="
docker rmi "$IMAGE:latest" 2>/dev/null || true

echo "== تحميل الصورة الجديدة من ملف tar =="
docker load -i "$TAR_FILE"

echo "== تشغيل الحاوية على المنفذ $PORT =="
mkdir -p data
docker run -d \
  --name "$CONTAINER" \
  --restart unless-stopped \
  -p "$PORT:8000" \
  -v "$(pwd)/data:/app/data" \
  "$IMAGE:latest"

echo "== تم — يعمل الآن على المنفذ $PORT =="
docker ps --filter "name=$CONTAINER"
