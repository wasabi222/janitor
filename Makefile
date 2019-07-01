VERSION := 2019.7.1
# Update the image before publishing
export IMAGE ?= 9c6c3997a47d

black:
	black --check --skip-string-normalization .

format:
	black --skip-string-normalization .

down:
	docker-compose -f docker/janitor.yml down --remove-orphans

%:
	docker-compose -f docker/$@.yml up -d
