.PHONY: install lint test validate-sam build deploy lock-requirements check-requirements

# --locked falla si el lock quedó desfasado de pyproject.toml.
install:
	uv sync --locked --group dev --group local

lint:
	uv run ruff check src tools tests
	uv run ruff format --check src tools tests

test:
	uv run pytest -q

# Regenera src/requirements.txt desde uv.lock. Ejecutar tras tocar
# [project.dependencies] en pyproject.toml.
lock-requirements:
	@tmp=$$(mktemp); \
	{ printf '%s\n' \
		'# GENERADO desde uv.lock por `make lock-requirements` - no editar.' \
		'# Las dependencias se declaran en [project.dependencies] de pyproject.toml.' \
		''; \
	  uv export --no-dev --no-hashes --no-emit-project --no-annotate --no-header; \
	} > "$$tmp" \
		&& mv "$$tmp" src/requirements.txt \
		|| { rm -f "$$tmp"; exit 1; }

# Compara sin tocar el fichero: regenerarlo aquí borraría la divergencia que
# se busca detectar.
check-requirements:
	@tmp=$$(mktemp -d); \
	uv export --no-dev --no-hashes --no-emit-project --no-annotate --no-header \
		> "$$tmp/expected.txt"; \
	grep -v '^#' src/requirements.txt | grep -v '^$$' > "$$tmp/actual.txt"; \
	diff -u "$$tmp/expected.txt" "$$tmp/actual.txt"; \
	rc=$$?; rm -rf "$$tmp"; \
	if [ $$rc -ne 0 ]; then \
		echo "::error::src/requirements.txt no coincide con uv.lock. Ejecuta 'make lock-requirements' y commitea."; \
		exit 1; \
	fi

validate-sam:
	sam validate --template infra/template.yaml --lint

build:
	sam build --template infra/template.yaml

deploy: build
	sam deploy --config-file infra/samconfig.toml
