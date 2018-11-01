JOBS ?= 1

MAKEFLAGS += -r -j $(JOBS)

.ONESHELL:

.PHONY: dist
dist: build/cloudwatch-metrics.deb

.PHONY: install
install: build/cloudwatch-metrics.deb
	dpkg -i $<

.PHONY: clean
clean:
	rm -rf build

DEBIAN_SRCS := $(wildcard debian/*)
DEBIAN_TARGETS := $(DEBIAN_SRCS:debian/%=build/cloudwatch_metrics/DEBIAN/%)

build/cloudwatch_metrics.pex: cloudwatch_metrics/cloudwatch_metrics.py
	virtualenv pex-build-cache
	pex-build-cache/bin/pip install --upgrade pip
	pex-build-cache/bin/pip install pex requests boto3 botocore --no-warn-script-location
	pex-build-cache/bin/pex \
		-o build/cloudwatch_metrics.pex -e cloudwatch_metrics:main \
		-r cloudwatch_metrics/requirements.txt --disable-cache -v
	rm -rf pex-build-cache

build/cloudwatch_metrics/usr/bin/cloudwatch-metrics: build/cloudwatch_metrics.pex
	@mkdir -p $(@D)
	cp --preserve=mode $< $@

$(DEBIAN_TARGETS): build/cloudwatch_metrics/DEBIAN/%: debian/%
	@mkdir -p $(@D)
	cp --preserve=mode $< $@

build/cloudwatch-metrics.deb: $(DEBIAN_TARGETS) build/cloudwatch_metrics/usr/bin/cloudwatch-metrics
	fakeroot dpkg-deb --build build/cloudwatch_metrics $@
