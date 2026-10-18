# ---- 构建阶段 ----
FROM node:22-alpine AS build
WORKDIR /app
# 国内镜像源加速（服务器无 clashx，须走国内源）
RUN npm config set registry https://registry.npmmirror.com
COPY package*.json ./
RUN npm install
COPY . .
RUN npm run build

# ---- 运行阶段 ----
FROM node:22-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production
RUN npm config set registry https://registry.npmmirror.com
COPY package*.json ./
RUN npm install --omit=dev
COPY --from=build /app/dist ./dist
EXPOSE 3000
CMD ["node", "dist/main"]
