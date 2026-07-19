COMPOSE := docker compose -f infra/compose/docker-compose.yml

.PHONY: up down seed test-integration logs ps

up:
	$(COMPOSE) up -d

down:
	$(COMPOSE) down

seed:
	$(COMPOSE) --profile seed up seed --abort-on-container-exit

test-integration:
	$(COMPOSE) --profile test up -d
	$(COMPOSE) --profile test run --rm integration-tests || ($(COMPOSE) --profile test down && exit 1)
	$(COMPOSE) --profile test down

logs:
	$(COMPOSE) logs -f --tail=100

ps:
	$(COMPOSE) ps
