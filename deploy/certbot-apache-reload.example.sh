#!/bin/sh
# Install as a root-owned executable in /etc/letsencrypt/renewal-hooks/deploy/.
# Replace the example certificate lineage with the one used by your private Apache site.
set -eu
case "${RENEWED_LINEAGE:-}" in
    /etc/letsencrypt/live/qdrop.example.com)
        /usr/sbin/apache2ctl configtest
        /bin/systemctl reload apache2
        ;;
esac
