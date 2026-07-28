.PHONY: install lint test validate-sam build deploy
install:
	uv sync
	uv pip install -r requirements-dev.txt
lint:
	ruff check src tools tests
	ruff format --check src tools tests
test:
	pytest -q
validate-sam:
	sam validate --template infra/template.yaml --lint
build:
	sam build --template infra/template.yaml
deploy: build
	sam deploy --config-file infra/samconfig.toml
