# ---- build stage ----
FROM node:20-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

# ---- serve stage ----
FROM nginx:alpine

# Baked in at image-build time (not into the JS bundle — the app only makes
# same-origin relative fetches; nginx proxies them). CI/CD must pass
# --build-arg VITE_API_BASE_URL=<real gateway origin> per environment.
ARG VITE_API_BASE_URL=http://gateway:8000

COPY nginx.conf.template /etc/nginx/templates/default.conf.template
# envsubst substitutes ONLY the named variable — nginx's own $host/$uri/etc.
# runtime variables use the same ${VAR} shell-like syntax and must not be
# touched, or nginx would fail to start.
RUN apk add --no-cache gettext \
    && envsubst '${VITE_API_BASE_URL}' \
         < /etc/nginx/templates/default.conf.template \
         > /etc/nginx/conf.d/default.conf \
    && rm /etc/nginx/templates/default.conf.template \
    && apk del gettext

COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
