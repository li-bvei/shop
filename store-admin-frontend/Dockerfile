# Build stage — compiles the SPA. VITE_API_BASE_URL is a relative path
# baked in at build time: the browser only ever calls the same origin it's
# served from, and this container's own nginx (see nginx.conf) proxies
# /api/ through to the backend container — so this never needs to know the
# real public domain.
FROM node:20-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN echo "VITE_API_BASE_URL=/api" > .env.production.local
RUN npm run build-only

# Serve stage
FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
