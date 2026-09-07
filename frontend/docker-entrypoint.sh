#!/bin/sh
set -e

# Default to the docker-compose service name "backend" if not
# overridden -- BACKEND_HOST lets the same image be reused with a
# different backend service name/hostname in other orchestration
# setups (Kubernetes, a different compose file, etc.) without a
# rebuild.
: "${BACKEND_HOST:=backend}"

envsubst '${BACKEND_HOST}' < /etc/nginx/templates/nginx.conf.template > /etc/nginx/conf.d/default.conf

exec nginx -g "daemon off;"
