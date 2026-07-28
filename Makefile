.PHONY: install lint test validate-sam build deploy lock-requirements check-requirements \
	seed-sql migrate db-counts

# Directorio con los ficheros fuente del curso (CSV/XLSX). Estan FUERA del repo
# a proposito: lo que se versiona es el SQL generado, no los datos de origen.
DATA_DIR ?= ..
STACK_NAME ?= kapso-whatsapp-bot
AWS_REGION ?= eu-west-1

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

# Regenera src/migrations/003 y 004 desde los CSV/XLSX. Ejecutar tras cambiar
# los datos del curso; el SQL resultante se revisa y se commitea.
seed-sql:
	uv run --group tools python tools/generate_seed.py \
		--nodes "$(DATA_DIR)/tb_nodes.csv" \
		--flow "$(DATA_DIR)/tb_flow_sequence.csv" \
		--assets "$(DATA_DIR)/assets.xlsx"

# Aplica las migraciones pendientes. Idempotente: re-ejecutarlo es un no-op.
# La PRIMERA llamada del dia puede tardar ~1 min mientras el cluster reanuda.
migrate:
	@fn=$$(aws cloudformation describe-stacks \
		--stack-name "$(STACK_NAME)" --region "$(AWS_REGION)" \
		--query 'Stacks[0].Outputs[?OutputKey==`MigrationFunctionName`].OutputValue' \
		--output text); \
	echo "Invocando $$fn ..."; \
	aws lambda invoke --function-name "$$fn" --region "$(AWS_REGION)" \
		--cli-read-timeout 900 --payload '{}' \
		--cli-binary-format raw-in-base64-out /dev/stdout

# Comprobaciones de aceptacion: 70 nodos, 70 posiciones, 42 enriquecidos.
db-counts:
	@cluster=$$(aws cloudformation describe-stacks --stack-name "$(STACK_NAME)" \
		--region "$(AWS_REGION)" --output text \
		--query 'Stacks[0].Outputs[?OutputKey==`DbClusterArn`].OutputValue'); \
	secret=$$(aws cloudformation describe-stacks --stack-name "$(STACK_NAME)" \
		--region "$(AWS_REGION)" --output text \
		--query 'Stacks[0].Outputs[?OutputKey==`DbSecretArn`].OutputValue'); \
	for q in \
		"SELECT count(*) FROM nodes" \
		"SELECT count(*) FROM flow_sequence" \
		"SELECT count(*) FROM nodes WHERE objective IS NOT NULL" \
		"SELECT count(*) FROM nodes WHERE stage IS NULL"; do \
		printf '%-52s' "$$q"; \
		aws rds-data execute-statement --resource-arn "$$cluster" \
			--secret-arn "$$secret" --database "$${DB_NAME:-waku}" \
			--region "$(AWS_REGION)" --sql "$$q" \
			--query 'records[0][0].longValue' --output text; \
	done
