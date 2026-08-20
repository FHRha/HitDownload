FROM python:3.11-alpine

WORKDIR /app

# Установка зависимостей для сборки, если потребуются
# RUN apk add --no-cache gcc musl-dev

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN pip install --no-cache-dir .

# Очистка
# RUN apk del gcc musl-dev

ENV MUSIC_DIR=/music
VOLUME /music
VOLUME /root/.config/hitdl

ENTRYPOINT ["hitdl"]
CMD ["--help"]
