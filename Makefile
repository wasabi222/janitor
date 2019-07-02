VERSION := $(shell git describe --tags --always --dirty="-dev")
# Update the image before publishing
export IMAGE ?= janitor:$(VERSION)

black:
	black --check --skip-string-normalization .

format:
	black --skip-string-normalization .

build:
	docker build . -t $(IMAGE)

down:
	docker-compose -f docker/janitor.yml down --remove-orphans

%: $(OPTS)
	docker-compose -f docker/$@.yml up -d
