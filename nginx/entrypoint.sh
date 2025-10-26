#!/usr/bin/env sh
set -eu

TEMPLATE_PATH="/etc/nginx/templates/default.conf.template"
OUTPUT_PATH="/etc/nginx/conf.d/default.conf"

if [ ! -f "${TEMPLATE_PATH}" ]; then
    echo "nginx template not found at ${TEMPLATE_PATH}" >&2
    exit 1
fi

ACTIVE_POOL="${ACTIVE_POOL:-blue}"
PORT_VALUE="${PORT:-3000}"

case "${ACTIVE_POOL}" in
    green)
        PRIMARY_UPSTREAM_SERVER="server app_green:${PORT_VALUE} max_fails=1 fail_timeout=5s;"
        BACKUP_UPSTREAM_SERVER="server app_blue:${PORT_VALUE} backup;"
        ;;
    blue|*)
        PRIMARY_UPSTREAM_SERVER="server app_blue:${PORT_VALUE} max_fails=1 fail_timeout=5s;"
        BACKUP_UPSTREAM_SERVER="server app_green:${PORT_VALUE} backup;"
        ;;
esac

export PRIMARY_UPSTREAM_SERVER
export BACKUP_UPSTREAM_SERVER

envsubst '${PRIMARY_UPSTREAM_SERVER} ${BACKUP_UPSTREAM_SERVER}' < "${TEMPLATE_PATH}" > "${OUTPUT_PATH}"

nginx -t
exec nginx -g 'daemon off;'
