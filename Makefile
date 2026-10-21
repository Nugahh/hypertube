.PHONY: all up down logs test re fclean

all: up

# first run: create .env with random secrets
.env:
	cp .env.example .env
	sed -i "s/^SECRET_KEY=.*/SECRET_KEY=$$(openssl rand -hex 32)/; s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=$$(openssl rand -hex 16)/" .env

# data/jackett is created here so it belongs to you, not to root (Docker would create it as root)
up: .env
	mkdir -p data/jackett
	docker compose up --build -d
	@echo "Site:    http://localhost:3000"
	@echo "Jackett: http://localhost:9117"

down:
	docker compose down

logs:
	docker compose logs -f

# tests run inside the backend image: nothing to install on the host
test: .env
	docker compose run --rm --no-deps backend pytest

re: down up

# also deletes the images, the database and everything stored in ./data (Jackett config)
fclean:
	docker compose down -v --rmi local
	rm -rf data
