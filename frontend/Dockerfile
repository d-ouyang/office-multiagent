# ---- 构建阶段：node 构建 Vite 产物 ----
FROM node:20-alpine AS build
WORKDIR /app
# 国内镜像源加速（服务器无 clashx）
RUN npm config set registry https://registry.npmmirror.com
COPY package*.json ./
RUN npm install
COPY . .
RUN npm run build

# ---- 运行阶段：nginx 伺服 dist + 反代 /api → gateway ----
FROM nginx:alpine AS runtime
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
