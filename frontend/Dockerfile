FROM node:22-alpine AS deps
WORKDIR /app
# optional extra CA certificates (corporate TLS proxies) – see certs/README.md
COPY certs/ /tmp/certs/
RUN cat /tmp/certs/*.crt > /tmp/extra-ca.pem 2>/dev/null || true
ENV NODE_EXTRA_CA_CERTS=/tmp/extra-ca.pem
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

FROM node:22-alpine AS build
WORKDIR /app
ARG API_URL=http://api:8000
ENV API_URL=$API_URL NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY frontend .
RUN npm run build

FROM node:22-alpine
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 HOSTNAME=0.0.0.0 PORT=3000
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public
USER node
EXPOSE 3000
CMD ["node", "server.js"]
