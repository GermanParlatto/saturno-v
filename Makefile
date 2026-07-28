.PHONY: install lint validate-sam build deploy
install:
	uv sync
	uv pip install -r requirements-dev.txt
lint:
	ruff check src tools
	ruff format --check src tools
validate-sam:
	sam validate --template infra/template.yaml --lint
build:
	sam build --template infra/template.yaml
deploy: build
	sam deploy --config-file infra/samconfig.toml
