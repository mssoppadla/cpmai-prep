FROM node:20-alpine
WORKDIR /app
# .npmrc carries `legacy-peer-deps=true` — see frontend/.npmrc.
# Dotfiles don't match `package*.json`, so list it explicitly.
COPY package.json package-lock.json .npmrc ./
RUN npm ci
COPY . .
EXPOSE 3000
CMD ["npm", "run", "dev"]
