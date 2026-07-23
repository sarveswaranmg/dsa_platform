#!/bin/sh
set -e
exec alembic upgrade head
