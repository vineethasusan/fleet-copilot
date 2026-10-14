.PHONY: install data app api test lint eval docker

install:  ## install dependencies
	pip install -r requirements-dev.txt

data:     ## generate the synthetic fleet database
	python scripts/generate_data.py --out data/fleet.db --seed 42

app:      ## run the Streamlit chat UI on :8501
	streamlit run app.py

api:      ## run the REST API on :8000 (docs at /docs)
	uvicorn api:app --reload

test:     ## run unit and pipeline tests (no API key needed)
	RETRIEVER=tfidf pytest -q

lint:
	ruff check .

eval:     ## run the evaluation set against the configured LLM
	python eval/run_eval.py

docker:   ## build and run app + api with Docker
	docker compose up --build
