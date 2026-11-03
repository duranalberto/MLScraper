#!/usr/bin/env bash
set -euo pipefail

DB_NAME="${DB_NAME:-mlscraper}"
DB_USER="${DB_USER:-mlscraper}"
DB_PASSWORD="${DB_PASSWORD:-mlscraper}"
MYSQL_DATA_DIR="/var/lib/mysql"
MYSQL_RUN_DIR="/run/mysqld"

mkdir -p "${MYSQL_RUN_DIR}" "${MYSQL_DATA_DIR}"
chown -R mysql:mysql "${MYSQL_RUN_DIR}" "${MYSQL_DATA_DIR}"

if [ ! -d "${MYSQL_DATA_DIR}/mysql" ]; then
    echo "Initializing MySQL/MariaDB data directory in ${MYSQL_DATA_DIR}..."
    if command -v mariadb-install-db >/dev/null 2>&1; then
        mariadb-install-db --user=mysql --datadir="${MYSQL_DATA_DIR}" >/dev/null
    elif command -v mysql_install_db >/dev/null 2>&1; then
        mysql_install_db --user=mysql --datadir="${MYSQL_DATA_DIR}" >/dev/null
    else
        mysqld --initialize-insecure --user=mysql --datadir="${MYSQL_DATA_DIR}"
    fi
fi

if ! pgrep -x "mariadbd" >/dev/null 2>&1 && ! pgrep -x "mysqld" >/dev/null 2>&1; then
    echo "Starting MySQL/MariaDB daemon..."
    if command -v service >/dev/null 2>&1 && service mariadb status >/dev/null 2>&1; then
        service mariadb start
    elif command -v service >/dev/null 2>&1 && service mysql status >/dev/null 2>&1; then
        service mysql start
    else
        mysqld_safe --datadir="${MYSQL_DATA_DIR}" --pid-file="${MYSQL_RUN_DIR}/mysqld.pid" >/dev/null 2>&1 &
    fi

    for _ in $(seq 1 30); do
        if mysqladmin ping --silent >/dev/null 2>&1; then
            break
        fi
        sleep 1
    done
fi

mysql -u root <<SQL
CREATE DATABASE IF NOT EXISTS \`${DB_NAME}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS '${DB_USER}'@'localhost' IDENTIFIED BY '${DB_PASSWORD}';
CREATE USER IF NOT EXISTS '${DB_USER}'@'127.0.0.1' IDENTIFIED BY '${DB_PASSWORD}';
CREATE USER IF NOT EXISTS '${DB_USER}'@'%' IDENTIFIED BY '${DB_PASSWORD}';
GRANT ALL PRIVILEGES ON \`${DB_NAME}\`.* TO '${DB_USER}'@'localhost';
GRANT ALL PRIVILEGES ON \`${DB_NAME}\`.* TO '${DB_USER}'@'127.0.0.1';
GRANT ALL PRIVILEGES ON \`${DB_NAME}\`.* TO '${DB_USER}'@'%';
FLUSH PRIVILEGES;
SQL

echo "MySQL database '${DB_NAME}' is ready."
