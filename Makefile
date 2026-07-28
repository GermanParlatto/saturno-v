.PHONY: install lint build deploy
install:
	uv sync
lint:
	ruff check src tools
	ruff format --check src tools
validate-sam:
	sam validate --template infra/template.yaml --lint
build:
	sam build --template infra/template.yaml
deploy: build
	sam deploy --config-file infra/samconfig.toml
