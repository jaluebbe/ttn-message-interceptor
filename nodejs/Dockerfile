FROM node:lts-slim

WORKDIR /usr/src/app

COPY package.json ./
COPY package-lock.json ./

RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi

COPY . .

RUN addgroup --system appgroup && adduser --system appuser --ingroup appgroup
USER appuser

EXPOSE 3000

CMD ["node", "decoders_api.js"]
