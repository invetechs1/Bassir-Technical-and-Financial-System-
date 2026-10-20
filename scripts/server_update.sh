#!/usr/bin/env bash
# تحديث خادم الإنتاج بأمر واحد (البند 1 و9 في قائمة المهام):
#   نسخة احتياطية ← سحب آخر main ← تثبيت المتطلبات ← فحص النظام ← إعادة التشغيل ← طبيب الخادم
# التشغيل من مجلد المشروع:   bash scripts/server_update.sh
# أول مرة (السكربت ليس على الخادم بعد):
#   git fetch origin main && git show origin/main:scripts/server_update.sh | bash
# متغيرات اختيارية: SERVICE=azoom  BACKUP_REMOTE=user@host:/backups/azoom/  BACKUP_DEST=/var/backups/azoom
set -euo pipefail
# من ملف: انتقل لجذر المشروع؛ من stdin (أول مرة): يُشغَّل من المجلد الحالي
if [ -f "$0" ]; then cd "$(dirname "$0")/.."; fi
[ -d .git ] && [ -f requirements.txt ] || { echo "❌ شغّله من مجلد المشروع (مثل /opt/azoom)"; exit 1; }

SERVICE="${SERVICE:-azoom}"
PY=".venv/bin/python"; [ -x "$PY" ] || PY="python3"
PIP=".venv/bin/pip";   [ -x "$PIP" ] || PIP="$PY -m pip"

echo "== 1) نسخة احتياطية لـ data/ قبل أي تغيير =="
BACKUP_ARGS=()
[ -n "${BACKUP_DEST:-}" ] && BACKUP_ARGS+=(--dest "$BACKUP_DEST")
[ -n "${BACKUP_REMOTE:-}" ] && BACKUP_ARGS+=(--remote "$BACKUP_REMOTE")
if [ -f scripts/backup_data.py ]; then
  "$PY" scripts/backup_data.py "${BACKUP_ARGS[@]}"
else   # نسخة قديمة بلا سكربت النسخ — أرشيف مباشر
  mkdir -p "${BACKUP_DEST:-backups}"
  tar czf "${BACKUP_DEST:-backups}/azoom-data-$(date +%F_%H%M%S).tgz" --exclude=data/exports data
  echo "✅ نسخة احتياطية في ${BACKUP_DEST:-backups}/"
fi

echo "== 2) سحب آخر main =="
PROTECTED=(data/secret.key data/branding)
if [ -n "$(git status --porcelain --untracked-files=no -- . ':!data/secret.key' ':!data/branding')" ]; then
  echo "❌ توجد تعديلات محلية على الخادم — لن أكتب فوقها. اعرضها: git status"; exit 1
fi
PREV=$(git rev-parse HEAD)
# secret.key وشعارات المستأجرين كانت مُتتبَّعة في git ثم أُزيلت من التتبّع؛ سحب ذلك
# التغيير يحذفها من القرص — تُحفظ جانباً وتُعاد بعد السحب فلا تضيع الأسرار والشعارات.
KEEP=$(mktemp -d)
[ -f data/secret.key ] && cp -p data/secret.key "$KEEP/"
[ -d data/branding ] && cp -rp data/branding "$KEEP/"
# نسخة الخادم قد تختلف عن المرفوعة — تُعاد للمُتتبَّع مؤقتاً كي لا يرفض git السحب
git checkout -q -- "${PROTECTED[@]}" 2>/dev/null || true
git fetch origin main
git checkout main
if ! git pull --ff-only origin main; then
  echo "❌ فشل السحب — إعادة الملفات المحمية"
fi
# نسخة الخادم هي المرجع دائماً: تُعاد فوق أي شيء (git قد يحذف data/ إن فرغ)
mkdir -p data
[ -f "$KEEP/secret.key" ] && cp -p "$KEEP/secret.key" data/secret.key && echo "   ↺ data/secret.key محفوظ"
[ -d "$KEEP/branding" ] && mkdir -p data/branding && cp -rp "$KEEP/branding/." data/branding/
chmod 600 data/secret.key 2>/dev/null || true
rm -rf "$KEEP"
git rev-parse -q --verify origin/main >/dev/null && [ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] \
  || { echo "❌ HEAD ليس على origin/main — راجع git status"; exit 1; }
echo "   $(git rev-parse --short "$PREV") ← $(git rev-parse --short HEAD)"

echo "== 3) تثبيت المتطلبات =="
$PIP install -q -r requirements.txt

echo "== 4) فحص النظام الكامل (قاعدة مؤقتة معزولة) =="
if ! "$PY" scripts/system_check.py > /tmp/azoom-system-check.log 2>&1; then
  tail -20 /tmp/azoom-system-check.log
  echo "❌ فشل فحص النظام — لم تُعَد الخدمة. للرجوع: git checkout $PREV"; exit 1
fi
tail -1 /tmp/azoom-system-check.log

echo "== 5) إعادة تشغيل الخدمة =="
if command -v systemctl >/dev/null && systemctl list-unit-files "$SERVICE.service" >/dev/null 2>&1; then
  sudo systemctl restart "$SERVICE"
  sleep 3
  systemctl is-active --quiet "$SERVICE" && echo "✅ $SERVICE يعمل" \
    || { echo "❌ الخدمة لم تقلع: journalctl -u $SERVICE -n 50"; exit 1; }
else
  echo "⚠️ لا توجد خدمة systemd باسم $SERVICE — أعد تشغيل التطبيق يدوياً"
fi

echo "== 6) طبيب الخادم — ما بقي من قائمة المهام =="
"$PY" scripts/server_doctor.py || true
