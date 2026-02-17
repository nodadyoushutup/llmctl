FROM node:22-alpine AS build

WORKDIR /app

COPY app/llmctl-studio-frontend/package.json app/llmctl-studio-frontend/package-lock.json ./
RUN npm ci

COPY app/llmctl-studio-frontend/ ./

ARG VITE_API_BASE_URL=
ARG VITE_API_BASE_PATH=/api
ARG VITE_WEB_BASE_PATH=/web
ARG VITE_SOCKET_PATH=/api/socket.io
ARG VITE_SOCKET_NAMESPACE=/rt

ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
ENV VITE_API_BASE_PATH=${VITE_API_BASE_PATH}
ENV VITE_WEB_BASE_PATH=${VITE_WEB_BASE_PATH}
ENV VITE_SOCKET_PATH=${VITE_SOCKET_PATH}
ENV VITE_SOCKET_NAMESPACE=${VITE_SOCKET_NAMESPACE}

RUN npm run build

FROM nginx:1.27-alpine

COPY app/llmctl-studio-frontend/docker/nginx.conf /etc/nginx/nginx.conf
COPY --from=build /app/dist /usr/share/nginx/html/web

EXPOSE 8080

CMD ["nginx", "-g", "daemon off;"]
