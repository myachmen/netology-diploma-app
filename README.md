# Netology DevOps Diploma — Test Application

Тестовое веб-приложение для дипломного проекта Нетологии.

Приложение представляет собой статическую HTML-страницу, которую отдаёт Nginx внутри Docker-контейнера.

## Технологии

- Nginx
- Docker
- Kubernetes
- Yandex Cloud

## Сборка Docker-образа

```bash
docker build -t netology-diploma-app:1.0.0 .
```

## Локальный запуск

```bash
docker run -d --name diploma-web -p 8080:80 netology-diploma-app:1.0.0
```

Проверка:

```bash
curl -i http://127.0.0.1:8080/
```

Ожидаемый HTTP-статус: `200 OK`.

## Остановка и удаление контейнера

```bash
docker stop diploma-web
docker rm diploma-web
```

## Назначение

Приложение используется для проверки развёртывания в Kubernetes, работы балансировки нагрузки и автоматического обновления через CI/CD.

## Инфраструктура

[Репозиторий инфраструктуры дипломного проекта](https://github.com/myachmen/netology-devops-from-zero-homeworks/tree/diplom-yandexcloud)
