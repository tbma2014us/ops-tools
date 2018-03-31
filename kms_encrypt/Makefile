JOBS ?= 1

MAKEFLAGS += -r -j $(JOBS)

.ONESHELL:

.PHONY: dist
dist: build/kms-encrypt.deb

.PHONY: install
install: build/kms-encrypt.deb
	dpkg -i $<

.PHONY: clean
clean:
	rm -rf build pex*

DEBIAN_SRCS := $(wildcard debian/*)
DEBIAN_TARGETS := $(DEBIAN_SRCS:debian/%=build/kms_encrypt/DEBIAN/%)
EXECS = kms-encrypt kms-decrypt kms-decrypt-to-env

build/%.pex : %
	virtualenv pex-build-cache-$<
	pex-build-cache-$</bin/pip install --upgrade pip
	pex-build-cache-$</bin/pip install pex requests boto3 botocore aws_encryption_sdk pyOpenSSL --no-warn-script-location
	pex-build-cache-$</bin/pex -o $@ -m $<:main -r $</requirements.txt --disable-cache -v
	rm -rf pex-build-cache-$< $</*.pyc $</*.egg-info

build/kms_encrypt/usr/bin/kms-encrypt: build/kms_encrypt.pex
	@mkdir -p $(@D)
	cp --preserve=mode $< $@

build/kms_encrypt/usr/bin/kms-decrypt: build/kms_decrypt.pex
	@mkdir -p $(@D)
	cp --preserve=mode $< $@

build/kms_encrypt/usr/bin/kms-decrypt-to-env: build/kms_decrypt_to_env.pex
	@mkdir -p $(@D)
	cp --preserve=mode $< $@

executables: $(addprefix build/kms_encrypt/usr/bin/,$(EXECS))

$(DEBIAN_TARGETS): build/kms_encrypt/DEBIAN/%: debian/%
	@mkdir -p $(@D)
	cp --preserve=mode $< $@

build/kms-encrypt.deb: $(DEBIAN_TARGETS) executables
	fakeroot dpkg-deb --build build/kms_encrypt $@

