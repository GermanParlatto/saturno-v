.PHONY: install lint test build deploy
install:
	uv sync
lint:
	ruff check src tests
validate-sam:
	sam validate --template infra/template.yaml --lint
build:
	sam build --template infra/template.yaml
deploy: build
	sam deploy --config-file infra/samconfig.toml
